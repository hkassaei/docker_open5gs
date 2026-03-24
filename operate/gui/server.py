#!/usr/bin/env python3
"""
VoNR Learning Tool — Backend Server

A lightweight aiohttp server that wraps docker/docker-compose commands
and streams logs via WebSocket so the browser GUI can control the
full 5G SA + IMS + UERANSIM stack.

Usage:
    cd docker_open5gs
    operate/.venv/bin/python operate/gui/server.py
"""

import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path

from aiohttp import web

from metrics import MetricsCollector

log = logging.getLogger("vonr-gui")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]  # docker_open5gs/
SCRIPTS = REPO_ROOT / "operate" / "scripts"
GUI_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Environment — load .env and e2e.env so compose interpolation works
# ---------------------------------------------------------------------------
def _load_dotenv(path: Path) -> dict[str, str]:
    env = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env

_env = {**os.environ, **_load_dotenv(REPO_ROOT / ".env"), **_load_dotenv(REPO_ROOT / "operate" / "e2e.env")}

def _ims_domain() -> str:
    mcc = _env.get("MCC", "001")
    mnc = _env.get("MNC", "01")
    if len(mnc) == 3:
        return f"ims.mnc{mnc}.mcc{mcc}.3gppnetwork.org"
    return f"ims.mnc0{mnc}.mcc{mcc}.3gppnetwork.org"

IMS_DOMAIN = _ims_domain()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _EmptyParts:
    """Sentinel with an empty .parts list for safe getattr fallback."""
    parts: list = []

_empty_resp = _EmptyParts()
_empty_req = _EmptyParts()

async def _kill_proc(proc: asyncio.subprocess.Process):
    """Kill a subprocess, ignoring errors if it already exited."""
    try:
        proc.kill()
    except (ProcessLookupError, OSError):
        pass
    await proc.wait()


async def _ws_send(ws: web.WebSocketResponse, data: dict) -> bool:
    """Send JSON over WebSocket. Returns False if the connection is gone."""
    if ws.closed:
        return False
    try:
        await ws.send_json(data)
        return True
    except (ConnectionResetError, ConnectionError, ConnectionAbortedError):
        return False


async def _run(cmd: str, cwd: str | None = None) -> tuple[int, str, str]:
    """Run a shell command, return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd or str(REPO_ROOT),
        env=_env,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")


async def _run_stream(cmd: str, ws: web.WebSocketResponse, label: str) -> int:
    """Run a shell command, streaming combined output line-by-line over ws."""
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(REPO_ROOT),
        env=_env,
    )
    try:
        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode(errors="replace").rstrip("\n")
            if not await _ws_send(ws, {"type": "progress", "label": label, "line": text}):
                break
        await proc.wait()
        return proc.returncode or 0
    except Exception:
        await _kill_proc(proc)
        raise


REQUIRED_CONTAINERS = [
    "mongo", "nrf", "scp", "ausf", "udr", "udm", "amf", "smf", "upf",
    "pcf", "dns", "mysql", "pyhss", "icscf", "scscf", "pcscf", "rtpengine",
]
UE_CONTAINERS = ["e2e_ue1", "e2e_ue2"]
GNB_CONTAINER = "nr_gnb"

async def _container_status(name: str) -> str:
    """Return 'running', 'exited', or 'absent'."""
    rc, out, _ = await _run(f"docker inspect -f '{{{{.State.Status}}}}' {name}")
    if rc != 0:
        return "absent"
    return out.strip()


# ---------------------------------------------------------------------------
# API handlers
# ---------------------------------------------------------------------------

async def handle_index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(GUI_DIR / "index.html")


async def handle_status(request: web.Request) -> web.Response:
    """Return the status of every relevant container."""
    tasks = {}
    for name in REQUIRED_CONTAINERS + [GNB_CONTAINER] + UE_CONTAINERS:
        tasks[name] = asyncio.create_task(_container_status(name))
    results = {name: await t for name, t in tasks.items()}

    # Determine phase
    core_up = all(results.get(c) == "running" for c in REQUIRED_CONTAINERS)
    gnb_up = results.get(GNB_CONTAINER) == "running"
    ues_up = all(results.get(c) == "running" for c in UE_CONTAINERS)

    if core_up and gnb_up and ues_up:
        phase = "ready"
    elif core_up:
        phase = "partial"
    else:
        phase = "down"

    return web.json_response({"phase": phase, "containers": results})


# Track deploy/teardown locks
_deploy_lock = asyncio.Lock()


async def _ws_run_script(request: web.Request, script_name: str, label: str, start_msg: str) -> web.WebSocketResponse:
    """Common handler for WebSocket endpoints that run a script and stream output."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    if _deploy_lock.locked():
        await _ws_send(ws, {"type": "error", "message": "Another operation is in progress"})
        await ws.close()
        return ws

    async with _deploy_lock:
        script = str(SCRIPTS / script_name)
        await _ws_send(ws, {"type": "progress", "label": label, "line": start_msg})
        rc = await _run_stream(f"bash {script}", ws, label)
        if rc == 0:
            await _ws_send(ws, {"type": "done", "success": True})
        else:
            await _ws_send(ws, {"type": "done", "success": False, "message": f"Script exited with code {rc}"})

    await ws.close()
    return ws


async def handle_deploy(request: web.Request) -> web.WebSocketResponse:
    return await _ws_run_script(request, "e2e-vonr-test.sh", "deploy", "Starting full stack deployment...")

async def handle_deploy_ues(request: web.Request) -> web.WebSocketResponse:
    return await _ws_run_script(request, "deploy-ues.sh", "deploy-ues", "Deploying UEs...")

async def handle_teardown_ues(request: web.Request) -> web.WebSocketResponse:
    return await _ws_run_script(request, "teardown-ues.sh", "teardown-ues", "Tearing down UEs...")

async def handle_teardown_stack(request: web.Request) -> web.WebSocketResponse:
    return await _ws_run_script(request, "teardown-stack.sh", "teardown-stack", "Tearing down full stack...")


async def handle_ue_action(request: web.Request) -> web.Response:
    """Send a pjsua command to a UE container."""
    ue = request.match_info["ue"]  # "ue1" or "ue2"
    action = request.match_info["action"]
    container = f"e2e_{ue}"

    status = await _container_status(container)
    if status != "running":
        return web.json_response({"ok": False, "error": f"{container} is not running"}, status=400)

    if action == "call":
        # Two-step: send 'm', wait 2s, send SIP URI
        target_imsi = _env.get("UE2_IMSI") if ue == "ue1" else _env.get("UE1_IMSI")
        sip_uri = f"sip:{target_imsi}@{IMS_DOMAIN}"
        cmd = (
            f"docker exec {container} bash -c \"echo m >> /tmp/pjsua_cmd\" && "
            f"sleep 2 && "
            f"docker exec {container} bash -c \"echo '{sip_uri}' >> /tmp/pjsua_cmd\""
        )
    elif action == "hangup":
        cmd = f"docker exec {container} bash -c \"echo h >> /tmp/pjsua_cmd\""
    elif action == "answer":
        cmd = f"docker exec {container} bash -c \"echo a >> /tmp/pjsua_cmd\""
    elif action == "hold":
        cmd = f"docker exec {container} bash -c \"echo H >> /tmp/pjsua_cmd\""
    elif action == "unhold":
        cmd = f"docker exec {container} bash -c \"echo v >> /tmp/pjsua_cmd\""
    else:
        return web.json_response({"ok": False, "error": f"Unknown action: {action}"}, status=400)

    rc, out, err = await _run(cmd)
    if rc == 0:
        return web.json_response({"ok": True, "action": action, "ue": ue})
    return web.json_response({"ok": False, "error": err or out}, status=500)


async def handle_topology(request: web.Request) -> web.Response:
    """Return the live network topology as a JSON graph."""
    from topology import build_topology
    topo = await build_topology(_env)
    return web.json_response(topo.to_dict())


async def handle_metrics(request: web.Request) -> web.Response:
    """Return live metrics for all NFs (Prometheus + IMS stats)."""
    collector: MetricsCollector = request.app["metrics"]
    data = await collector.collect()
    return web.json_response(data)


async def handle_metrics_history(request: web.Request) -> web.Response:
    """Return metrics history for a single node (for sparklines)."""
    node_id = request.match_info["node_id"]
    collector: MetricsCollector = request.app["metrics"]
    return web.json_response(collector.history(node_id))


async def handle_explain(request: web.Request) -> web.Response:
    """Send container logs to Claude Code CLI and return a plain-English explanation."""
    body = await request.json()
    logs = body.get("logs", "")
    container = body.get("container", "")
    if not logs.strip():
        return web.json_response({"ok": False, "error": "No logs provided"}, status=400)

    # Truncate to keep prompt reasonable
    lines = logs.splitlines()
    if len(lines) > 500:
        lines = lines[-500:]
        logs = "\n".join(lines)

    # Build a container-aware prompt
    _NF_CONTEXT = {
        "amf":       "the AMF (Access and Mobility Management Function) in a 5G SA core",
        "smf":       "the SMF (Session Management Function) in a 5G SA core",
        "upf":       "the UPF (User Plane Function) in a 5G SA core",
        "nrf":       "the NRF (NF Repository Function / service discovery) in a 5G SA core",
        "scp":       "the SCP (Service Communication Proxy) in a 5G SA core",
        "ausf":      "the AUSF (Authentication Server Function) in a 5G SA core",
        "udm":       "the UDM (Unified Data Management) in a 5G SA core",
        "udr":       "the UDR (Unified Data Repository) in a 5G SA core",
        "pcf":       "the PCF (Policy Control Function) in a 5G SA core",
        "pcscf":     "the P-CSCF (Proxy-CSCF / SIP edge proxy) in the IMS",
        "icscf":     "the I-CSCF (Interrogating-CSCF) in the IMS",
        "scscf":     "the S-CSCF (Serving-CSCF) in the IMS",
        "pyhss":     "PyHSS (the Home Subscriber Server) in the IMS",
        "rtpengine": "RTPEngine (the media relay / RTP proxy) in the IMS",
        "mongo":     "MongoDB (the subscriber data store for the 5G core)",
        "mysql":     "MySQL (the subscriber data store for the IMS)",
        "dns":       "the DNS server for the IMS/5G network",
        "nr_gnb":    "the gNB (UERANSIM gNodeB / 5G base station)",
        "e2e_ue1":   "UE1 (UERANSIM UE + pjsua VoIMS client)",
        "e2e_ue2":   "UE2 (UERANSIM UE + pjsua VoIMS client)",
    }
    nf_desc = _NF_CONTEXT.get(container, f"the '{container}' container")

    prompt = (
        f"Explain these logs from {nf_desc} in a VoNR (Voice over New Radio) / "
        f"IMS deployment (Open5GS + Kamailio + UERANSIM). "
        "Walk through what happened step by step. Keep it concise but informative. "
        "Highlight anything notable — successful operations, errors, warnings, "
        "or unusual behavior.\n\n"
        f"Logs:\n{logs}"
    )

    # Use claude CLI with --print for non-interactive single-shot output.
    # Unset CLAUDECODE to allow running from within a Claude Code session.
    env = {**os.environ}
    env.pop("CLAUDECODE", None)
    env.pop("CLAUDE_CODE_ENTRY_POINT", None)
    env.pop("ANTHROPIC_API_KEY", None)

    # Resolve full path to claude binary since venv may not inherit PATH
    import shutil
    claude_bin = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")

    proc = await asyncio.create_subprocess_exec(
        claude_bin, "--print",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await proc.communicate(prompt.encode())

    out = stdout.decode(errors="replace").strip()
    err = stderr.decode(errors="replace").strip()

    if proc.returncode == 0 and out:
        return web.json_response({"ok": True, "explanation": out})
    else:
        error = err or out or f"claude exited with code {proc.returncode}"
        return web.json_response({"ok": False, "error": error}, status=500)


# ---------------------------------------------------------------------------
# AI Agent — Telecom Troubleshooting (Pydantic AI)
# ---------------------------------------------------------------------------

async def handle_investigate(request: web.Request) -> web.WebSocketResponse:
    """WebSocket endpoint for the AI troubleshooting agent.

    The client sends a JSON message with {"question": "..."} and receives
    streamed progress events followed by a final diagnosis.
    """
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    # Wait for the user's question
    msg = await ws.receive_json()
    question = msg.get("question", "").strip()
    if not question:
        await _ws_send(ws, {"type": "error", "message": "No question provided"})
        await ws.close()
        return ws

    try:
        # Lazy import to avoid startup cost if agent is never used
        sys.path.insert(0, str(REPO_ROOT / "operate"))
        from agentic_ops.agent import create_agent  # type: ignore[import-untyped]
        from agentic_ops.models import AgentDeps  # type: ignore[import-untyped]

        agent = create_agent()
        deps = AgentDeps(
            repo_root=REPO_ROOT,
            env=_env,
            pyhss_api=f"http://{_env.get('PYHSS_IP', 'localhost')}:8080",
        )

        await _ws_send(ws, {"type": "status", "message": "Starting investigation..."})

        # Import message part types for isinstance checks
        from pydantic_ai.messages import ToolCallPart, TextPart, ToolReturnPart

        # Track tool calls for the agent log
        tool_call_log: list[dict] = []

        # Run the agent with streaming via iter()
        # agent.iter() yields graph nodes: UserPromptNode, ModelRequestNode,
        # CallToolsNode, End. We inspect each node's data to extract events.
        async with agent.iter(question, deps=deps) as agent_run:
            async for node in agent_run:
                if ws.closed:
                    break

                node_name = type(node).__name__

                if node_name == "CallToolsNode":
                    # CallToolsNode contains the model's response with tool calls and/or text
                    for part in getattr(node, "model_response", _empty_resp).parts:
                        if isinstance(part, ToolCallPart):
                            tool_call_log.append({
                                "name": part.tool_name,
                                "args": str(part.args)[:200],
                            })
                            await _ws_send(ws, {
                                "type": "tool_call",
                                "name": part.tool_name,
                                "args": str(part.args),
                            })
                        elif isinstance(part, TextPart):
                            await _ws_send(ws, {
                                "type": "text",
                                "content": part.content,
                            })

                elif node_name == "ModelRequestNode":
                    # ModelRequestNode contains tool return results from the previous step
                    for part in getattr(node, "request", _empty_req).parts:
                        if isinstance(part, ToolReturnPart):
                            content = str(part.content)
                            preview = content[:200] + "..." if len(content) > 200 else content
                            # Attach result size to last matching tool call
                            for tc in reversed(tool_call_log):
                                if tc["name"] == part.tool_name and "result_size" not in tc:
                                    tc["result_size"] = len(content)
                                    break
                            await _ws_send(ws, {
                                "type": "tool_result",
                                "name": part.tool_name,
                                "preview": preview,
                            })

        # Send the final diagnosis
        result = agent_run.result
        if result and result.output:
            diag = result.output
            await _ws_send(ws, {
                "type": "diagnosis",
                "summary": diag.summary,
                "timeline": [e.model_dump() for e in diag.timeline],
                "root_cause": diag.root_cause,
                "affected_components": diag.affected_components,
                "recommendation": diag.recommendation,
                "confidence": diag.confidence,
                "explanation": diag.explanation,
            })
            # Send usage stats
            usage = result.usage()
            await _ws_send(ws, {
                "type": "usage",
                "total_tokens": usage.total_tokens if usage else 0,
            })

            # Persist agent log
            _persist_v1_run(question, diag, usage, tool_call_log)
        else:
            await _ws_send(ws, {
                "type": "error",
                "message": "Agent did not produce a diagnosis.",
            })

    except Exception as exc:
        log.exception("Investigation failed")
        await _ws_send(ws, {"type": "error", "message": str(exc)})

    await ws.close()
    return ws


def _persist_v1_run(question: str, diag, usage, tool_call_log: list[dict]) -> None:
    """Save v1.5 single-agent investigation result to docs/agent_logs/."""
    try:
        import json as _json
        from datetime import datetime as _dt

        logs_dir = REPO_ROOT / "operate" / "agentic_ops" / "docs" / "agent_logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        result = {
            "version": "v1.5",
            "question": question,
            "diagnosis": {
                "summary": diag.summary,
                "timeline": [e.model_dump() for e in diag.timeline],
                "root_cause": diag.root_cause,
                "affected_components": diag.affected_components,
                "recommendation": diag.recommendation,
                "confidence": diag.confidence,
                "explanation": diag.explanation,
            },
            "token_usage": {
                "total_tokens": usage.total_tokens if usage else 0,
                "input_tokens": getattr(usage, "input_tokens", 0) if usage else 0,
                "output_tokens": getattr(usage, "output_tokens", 0) if usage else 0,
                "requests": getattr(usage, "requests", 0) if usage else 0,
                "tool_calls_count": getattr(usage, "tool_calls", 0) if usage else 0,
            },
            "tool_calls": tool_call_log,
        }

        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        path = logs_dir / f"run_{ts}.json"
        with open(path, "w") as f:
            _json.dump(result, f, indent=2, default=str)
        log.info("v1.5 trace persisted to %s", path)
    except Exception:
        log.warning("Failed to persist v1.5 trace", exc_info=True)


async def handle_investigate_v2(request: web.Request) -> web.WebSocketResponse:
    """WebSocket endpoint for the v2 multi-agent troubleshooting system.

    Streams live per-agent trace events (phase_start, phase_complete,
    tool_call, tool_result, text) as they happen, then sends the
    diagnosis, full investigation trace, and token usage.
    """
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    msg = await ws.receive_json()
    question = msg.get("question", "").strip()
    if not question:
        await _ws_send(ws, {"type": "error", "message": "No question provided"})
        await ws.close()
        return ws

    try:
        sys.path.insert(0, str(REPO_ROOT / "operate"))
        from agentic_ops_v2.orchestrator import investigate

        await _ws_send(ws, {"type": "status", "message": "Starting v2 multi-agent investigation..."})

        # Live event callback — streams trace events to the WebSocket as
        # they are emitted by the orchestrator's event loop.
        async def on_event(evt: dict) -> None:
            await _ws_send(ws, evt)

        result = await investigate(question, on_event=on_event)

        # Send diagnosis
        diagnosis = result.get("diagnosis")
        if diagnosis and isinstance(diagnosis, str):
            await _ws_send(ws, {
                "type": "diagnosis",
                "summary": diagnosis[:200] if len(diagnosis) > 200 else diagnosis,
                "timeline": [],
                "root_cause": diagnosis,
                "affected_components": [],
                "recommendation": "",
                "confidence": "medium",
                "explanation": diagnosis,
            })
        elif diagnosis and isinstance(diagnosis, dict):
            await _ws_send(ws, {
                "type": "diagnosis",
                "summary": diagnosis.get("summary", ""),
                "timeline": diagnosis.get("timeline", []),
                "root_cause": diagnosis.get("root_cause", ""),
                "affected_components": diagnosis.get("affected_components", []),
                "recommendation": diagnosis.get("recommendation", ""),
                "confidence": diagnosis.get("confidence", "medium"),
                "explanation": diagnosis.get("explanation", ""),
            })
        else:
            await _ws_send(ws, {
                "type": "diagnosis",
                "summary": "Investigation complete — see phase results above",
                "timeline": [],
                "root_cause": str(result.get("findings", {})),
                "affected_components": [],
                "recommendation": "",
                "confidence": "medium",
                "explanation": "",
            })

        # Send the full investigation trace
        inv_trace = result.get("investigation_trace", {})
        await _ws_send(ws, {
            "type": "investigation_trace",
            "trace": inv_trace,
        })

        # Send token usage (backward compat)
        await _ws_send(ws, {
            "type": "usage",
            "total_tokens": result.get("total_tokens", 0),
        })

    except Exception as exc:
        log.exception("v2 investigation failed")
        await _ws_send(ws, {"type": "error", "message": str(exc)})

    await ws.close()
    return ws


async def handle_investigate_v3(request: web.Request) -> web.WebSocketResponse:
    """WebSocket endpoint for the v3 context-isolated multi-agent system."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    msg = await ws.receive_json()
    question = msg.get("question", "").strip()
    if not question:
        await _ws_send(ws, {"type": "error", "message": "No question provided"})
        await ws.close()
        return ws

    try:
        sys.path.insert(0, str(REPO_ROOT / "operate"))
        from agentic_ops_v3.orchestrator import investigate

        await _ws_send(ws, {"type": "status", "message": "Starting v3 context-isolated investigation..."})

        async def on_event(evt: dict) -> None:
            await _ws_send(ws, evt)

        result = await investigate(question, on_event=on_event)

        # Send diagnosis
        diagnosis = result.get("diagnosis")
        if diagnosis and isinstance(diagnosis, str):
            await _ws_send(ws, {
                "type": "diagnosis",
                "summary": diagnosis[:200] if len(diagnosis) > 200 else diagnosis,
                "timeline": [],
                "root_cause": diagnosis,
                "affected_components": [],
                "recommendation": "",
                "confidence": "medium",
                "explanation": diagnosis,
            })
        elif diagnosis and isinstance(diagnosis, dict):
            await _ws_send(ws, {
                "type": "diagnosis",
                "summary": diagnosis.get("summary", ""),
                "timeline": diagnosis.get("timeline", []),
                "root_cause": diagnosis.get("root_cause", ""),
                "affected_components": diagnosis.get("affected_components", []),
                "recommendation": diagnosis.get("recommendation", ""),
                "confidence": diagnosis.get("confidence", "medium"),
                "explanation": diagnosis.get("explanation", ""),
            })
        else:
            await _ws_send(ws, {
                "type": "diagnosis",
                "summary": "Investigation complete — see phase results above",
                "timeline": [],
                "root_cause": str(result.get("findings", {})),
                "affected_components": [],
                "recommendation": "",
                "confidence": "medium",
                "explanation": "",
            })

        # Send the full investigation trace
        inv_trace = result.get("investigation_trace", {})
        await _ws_send(ws, {
            "type": "investigation_trace",
            "trace": inv_trace,
        })

        # Send token usage
        await _ws_send(ws, {
            "type": "usage",
            "total_tokens": result.get("total_tokens", 0),
        })

    except Exception as exc:
        log.exception("v3 investigation failed")
        await _ws_send(ws, {"type": "error", "message": str(exc)})

    await ws.close()
    return ws


async def handle_active_faults(request: web.Request) -> web.Response:
    """Return active faults from the chaos monkey fault registry (data-ready for GUI)."""
    try:
        sys.path.insert(0, str(REPO_ROOT / "operate"))
        from agentic_chaos.fault_registry import FaultRegistry
        registry = FaultRegistry()
        await registry.initialize()
        faults = await registry.get_active_faults()
        return web.json_response([
            {
                "fault_id": f.fault_id,
                "fault_type": f.fault_type,
                "target": f.target,
                "params": f.params,
                "injected_at": f.injected_at.isoformat(),
                "ttl_seconds": f.ttl_seconds,
                "expires_at": f.expires_at.isoformat(),
                "verified": f.verified,
            }
            for f in faults
        ])
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_logs_ws(request: web.Request) -> web.WebSocketResponse:
    """WebSocket endpoint that streams docker logs for a container."""
    container = request.match_info["container"]
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    proc = await asyncio.create_subprocess_exec(
        "docker", "logs", "-f", "--tail", "100", container,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    try:
        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode(errors="replace").rstrip("\n")
            if not await _ws_send(ws, {"type": "log", "container": container, "line": text}):
                break
    finally:
        await _kill_proc(proc)

    await ws.close()
    return ws


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
def create_app() -> web.Application:
    app = web.Application()
    app["metrics"] = MetricsCollector(_env)
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/status", handle_status)
    app.router.add_get("/api/topology", handle_topology)
    app.router.add_get("/api/metrics", handle_metrics)
    app.router.add_get("/api/metrics/history/{node_id}", handle_metrics_history)
    app.router.add_get("/ws/deploy", handle_deploy)
    app.router.add_get("/ws/deploy-ues", handle_deploy_ues)
    app.router.add_get("/ws/teardown-ues", handle_teardown_ues)
    app.router.add_get("/ws/teardown-stack", handle_teardown_stack)
    app.router.add_post("/api/ue/{ue}/{action}", handle_ue_action)
    app.router.add_post("/api/explain", handle_explain)
    app.router.add_get("/ws/investigate", handle_investigate)
    app.router.add_get("/ws/investigate-v2", handle_investigate_v2)
    app.router.add_get("/ws/investigate-v3", handle_investigate_v3)
    app.router.add_get("/ws/logs/{container}", handle_logs_ws)
    app.router.add_get("/api/chaos/faults", handle_active_faults)
    return app


def main():
    port = int(os.environ.get("GUI_PORT", "8073"))
    app = create_app()
    print(f"VoNR Learning Tool starting on http://0.0.0.0:{port}")
    print(f"Repo root: {REPO_ROOT}")
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
