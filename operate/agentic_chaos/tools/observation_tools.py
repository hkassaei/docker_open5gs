"""
Observation tools — metrics snapshots, log capture, delta computation, blast radius.

These tools collect the "before" and "during" data that makes episodes valuable
as training data. They reuse existing infrastructure:
  - MetricsCollector from operate/gui/metrics.py
  - NetworkTopology from operate/gui/topology.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from ._common import ALL_CONTAINERS, CORE_CONTAINERS, LOG_CONTAINERS, shell

log = logging.getLogger("chaos-tools.observe")

# Add the gui directory to the import path so we can reuse MetricsCollector and topology
_GUI_DIR = Path(__file__).resolve().parents[2] / "gui"
_REPO_ROOT = Path(__file__).resolve().parents[3]

# Lazy imports to avoid circular / missing-path issues at module level
_metrics_collector = None
_env_cache: dict[str, str] | None = None


def _load_env() -> dict[str, str]:
    """Load .env and e2e.env, caching the result."""
    global _env_cache
    if _env_cache is not None:
        return _env_cache

    env: dict[str, str] = {**os.environ}
    for envfile in [_REPO_ROOT / ".env", _REPO_ROOT / "operate" / "e2e.env"]:
        if envfile.exists():
            for line in envfile.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    _env_cache = env
    return env


def _get_metrics_collector():
    """Lazily create a MetricsCollector instance."""
    global _metrics_collector
    if _metrics_collector is not None:
        return _metrics_collector

    # Add gui dir to path for import
    gui_str = str(_GUI_DIR)
    if gui_str not in sys.path:
        sys.path.insert(0, gui_str)

    from metrics import MetricsCollector
    _metrics_collector = MetricsCollector(_load_env())
    return _metrics_collector


# -------------------------------------------------------------------------
# Metrics snapshot
# -------------------------------------------------------------------------

_METRICS_TIMEOUT = 15  # seconds

async def snapshot_metrics() -> dict[str, dict]:
    """Capture a full metrics snapshot from all NFs.

    Returns:
        Dict of node_id → {metrics, badge, source} — same shape as
        MetricsCollector.collect().

    Returns empty dict if collection times out.
    """
    collector = _get_metrics_collector()
    # Force a fresh collection by resetting the cache timestamp
    collector._cache_ts = 0.0
    try:
        return await asyncio.wait_for(collector.collect(), timeout=_METRICS_TIMEOUT)
    except asyncio.TimeoutError:
        log.warning("Metrics collection timed out after %ds", _METRICS_TIMEOUT)
        return {}


# -------------------------------------------------------------------------
# Container status snapshot
# -------------------------------------------------------------------------

async def snapshot_container_status() -> dict[str, str]:
    """Return status of all known containers.

    Returns:
        Dict of container_name → 'running'/'exited'/'absent'.
    """
    async def _status(name: str) -> tuple[str, str]:
        rc, output = await shell(
            f"docker inspect -f '{{{{.State.Status}}}}' {name}"
        )
        return name, output.strip() if rc == 0 else "absent"

    results = await asyncio.gather(*[_status(c) for c in ALL_CONTAINERS])
    return dict(results)


def determine_phase(statuses: dict[str, str]) -> str:
    """Determine stack phase from container statuses.

    Returns 'ready', 'partial', or 'down'.
    """
    core_up = all(statuses.get(c) == "running" for c in CORE_CONTAINERS)
    gnb_up = statuses.get("nr_gnb") == "running"
    ues_up = all(statuses.get(c) == "running" for c in ("e2e_ue1", "e2e_ue2"))

    if core_up and gnb_up and ues_up:
        return "ready"
    elif core_up:
        return "partial"
    return "down"


# -------------------------------------------------------------------------
# Log capture
# -------------------------------------------------------------------------

async def snapshot_logs(
    containers: list[str] | None = None,
    tail: int = 50,
) -> dict[str, list[str]]:
    """Capture recent log lines from containers.

    Args:
        containers: List of container names. If None, captures from LOG_CONTAINERS.
        tail: Number of recent lines per container.

    Returns:
        Dict of container_name → [log lines].
    """
    targets = containers if containers is not None else LOG_CONTAINERS

    async def _logs(name: str) -> tuple[str, list[str]]:
        rc, output = await shell(f"docker logs --tail {int(tail)} {name} 2>&1")
        lines = output.splitlines() if rc == 0 and output else []
        return name, lines

    results = await asyncio.gather(*[_logs(c) for c in targets])
    return dict(results)


# -------------------------------------------------------------------------
# Metrics delta computation
# -------------------------------------------------------------------------

def compute_metrics_delta(
    baseline: dict[str, dict],
    current: dict[str, dict],
) -> dict[str, dict]:
    """Compute per-node, per-metric deltas between two snapshots.

    Args:
        baseline: Metrics snapshot from before fault injection.
        current: Metrics snapshot from during/after fault.

    Returns:
        Dict of node_id → {metric_name: {baseline, current, delta}}.
        Only includes metrics that exist in both snapshots and have changed.
    """
    delta: dict[str, dict] = {}

    for node_id in set(baseline) | set(current):
        b_metrics = baseline.get(node_id, {}).get("metrics", {})
        c_metrics = current.get(node_id, {}).get("metrics", {})

        node_delta: dict[str, dict] = {}
        for key in set(b_metrics) | set(c_metrics):
            if key.startswith("_"):
                continue
            b_val = b_metrics.get(key)
            c_val = c_metrics.get(key)
            if b_val is None or c_val is None:
                continue
            if not isinstance(b_val, (int, float)) or not isinstance(c_val, (int, float)):
                continue
            diff = c_val - b_val
            if diff != 0:
                node_delta[key] = {
                    "baseline": b_val,
                    "current": c_val,
                    "delta": diff,
                }

        if node_delta:
            delta[node_id] = node_delta

    return delta


# -------------------------------------------------------------------------
# Blast radius (reuse topology.impact_of)
# -------------------------------------------------------------------------

async def compute_blast_radius(node_id: str) -> dict:
    """Compute which edges and nodes are affected if a node goes down.

    Reuses NetworkTopology.impact_of() from operate/gui/topology.py.

    Args:
        node_id: Container name (e.g. 'pcscf', 'amf').

    Returns:
        {node, broken_edges: [...], affected_nodes: [...]}
    """
    gui_str = str(_GUI_DIR)
    if gui_str not in sys.path:
        sys.path.insert(0, gui_str)

    from topology import build_topology
    env = _load_env()
    topo = await build_topology(env)
    return topo.impact_of(node_id)
