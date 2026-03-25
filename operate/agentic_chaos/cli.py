"""
CLI entry point for the Agentic Chaos Monkey platform.

Usage:
    # Set env vars first:
    export GOOGLE_CLOUD_PROJECT="your-project"
    export GOOGLE_CLOUD_LOCATION="northamerica-northeast1"
    export GOOGLE_GENAI_USE_VERTEXAI="TRUE"

    # Run a scenario:
    python -m agentic_chaos.cli run "P-CSCF Latency" --agent v1.5

    # List available scenarios:
    python -m agentic_chaos.cli list-scenarios

    # List recorded episodes (scans agent_logs directories):
    python -m agentic_chaos.cli list-episodes

    # Show an episode:
    python -m agentic_chaos.cli show-episode run_20260324_143022_pcscf_latency

    # Emergency: heal all active faults:
    python -m agentic_chaos.cli heal-all
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_OPERATE_DIR = Path(__file__).resolve().parents[1]  # operate/

_AGENT_LOG_DIRS = {
    "v1.5": _OPERATE_DIR / "agentic_ops" / "docs" / "agent_logs",
    "v3": _OPERATE_DIR / "agentic_ops_v3" / "docs" / "agent_logs",
}


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(name)s: %(message)s",
    )
    # Quiet down noisy libraries
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


# -------------------------------------------------------------------------
# Commands
# -------------------------------------------------------------------------

async def cmd_run(args: argparse.Namespace) -> int:
    """Run a chaos scenario."""
    from .orchestrator import run_scenario
    from .scenarios.library import get_scenario

    try:
        scenario = get_scenario(args.scenario)
    except KeyError as e:
        print(str(e), file=sys.stderr)
        return 1

    agent_version = args.agent
    print(f"Running scenario: {scenario.name}")
    print(f"  Agent: {agent_version}")
    print(f"  Category: {scenario.category.value}")
    print(f"  Blast radius: {scenario.blast_radius.value}")
    print(f"  Faults: {len(scenario.faults)}")
    print(f"  Description: {scenario.description}")
    print()

    episode = await run_scenario(scenario, agent_version=agent_version)

    print()
    print("=" * 60)
    print("EPISODE COMPLETE")
    print("=" * 60)
    print(f"  ID:            {episode.get('episode_id', '?')}")
    print(f"  Duration:      {episode.get('duration_seconds', 0):.1f}s")
    print(f"  Faults:        {len(episode.get('faults', []))}")
    print(f"  Observations:  {len(episode.get('observations', []))}")

    symptoms = any(o.get("symptoms_detected") for o in episode.get("observations", []))
    print(f"  Symptoms:      {symptoms}")
    print(f"  Resolution:    {episode.get('resolution', {}).get('heal_method', '?')}")
    print(f"  RCA label:     {episode.get('rca_label', {}).get('failure_domain', '?')}")

    ep_path = episode.get("episode_path", "?")
    print(f"  Episode file:  {ep_path}")

    challenge = episode.get("challenge_result")
    if challenge and challenge.get("score"):
        score = challenge["score"]
        print()
        print("  Agent Evaluation:")
        print(f"    Score:        {score.get('total_score', 0):.0%}")
        print(f"    Root cause:   {'correct' if score.get('root_cause_correct') else 'WRONG'}")
        print(f"    Components:   {score.get('component_overlap', 0):.0%} overlap")
        print(f"    Severity:     {'correct' if score.get('severity_correct') else 'WRONG'}")
        print(f"    Diagnosis:    {challenge.get('diagnosis_summary', '?')[:120]}")

    md_path = episode.get("markdown_path")
    if md_path:
        print(f"\n  Markdown report: {md_path}")

    return 0


async def cmd_list_scenarios(args: argparse.Namespace) -> int:
    """List all available scenarios."""
    from .scenarios.library import list_scenarios

    scenarios = list_scenarios()

    print(f"{'Name':<35} {'Category':<12} {'Blast':<12} {'Faults':<6}")
    print("-" * 70)
    for s in scenarios:
        print(f"{s['name']:<35} {s['category']:<12} {s['blast_radius']:<12} {s['faults']:<6}")

    print(f"\n{len(scenarios)} scenarios available.")
    print("Run with: python -m agentic_chaos.cli run \"<scenario name>\"")
    return 0


async def cmd_list_episodes(args: argparse.Namespace) -> int:
    """List all recorded episodes from agent_logs directories."""
    # Collect all episode JSONs across both agent log dirs
    entries: list[tuple[str, Path]] = []  # (agent_version, filepath)
    for version, logs_dir in _AGENT_LOG_DIRS.items():
        if logs_dir.exists():
            for f in logs_dir.glob("run_*.json"):
                entries.append((version, f))

    # Sort by filename descending (most recent first)
    entries.sort(key=lambda x: x[1].name, reverse=True)

    if not entries:
        print("No episodes recorded yet.")
        return 0

    print(f"{'Agent':<7} {'File':<50} {'Duration':<10} {'Faults':<8} {'Score':<8} {'Symptoms'}")
    print("-" * 95)

    for version, f in entries:
        try:
            with open(f) as fp:
                ep = json.load(fp)
            dur = ep.get("duration_seconds", 0)
            faults = len(ep.get("faults", []))
            symptoms = any(o.get("symptoms_detected") for o in ep.get("observations", []))
            challenge = ep.get("challenge_result")
            score = ""
            if challenge and challenge.get("score"):
                score = f"{challenge['score'].get('total_score', 0):.0%}"
            print(f"{version:<7} {f.stem:<50} {dur:>7.1f}s  {faults:<8} {score:<8} {symptoms}")
        except (json.JSONDecodeError, KeyError):
            print(f"{version:<7} {f.stem:<50} (corrupted)")

    print(f"\n{len(entries)} episodes recorded.")
    return 0


async def cmd_show_episode(args: argparse.Namespace) -> int:
    """Show details of a specific episode."""
    episode_id = args.episode_id

    # Search both agent_logs directories for a match
    matches: list[Path] = []
    for logs_dir in _AGENT_LOG_DIRS.values():
        if not logs_dir.exists():
            continue
        # Try exact match first
        exact = logs_dir / f"{episode_id}.json"
        if exact.exists():
            matches.append(exact)
        else:
            # Partial match
            matches.extend(logs_dir.glob(f"*{episode_id}*.json"))

    if len(matches) == 1:
        filepath = matches[0]
    elif len(matches) > 1:
        print(f"Ambiguous: {len(matches)} matches for '{episode_id}':", file=sys.stderr)
        for m in matches:
            print(f"  {m.parent.parent.parent.name}/{m.stem}", file=sys.stderr)
        return 1
    else:
        print(f"Episode not found: {episode_id}", file=sys.stderr)
        return 1

    with open(filepath) as f:
        ep = json.load(f)

    print(json.dumps(ep, indent=2, default=str))
    return 0


async def cmd_heal_all(args: argparse.Namespace) -> int:
    """Emergency: heal all active faults."""
    from .fault_registry import FaultRegistry

    registry = FaultRegistry()
    await registry.initialize()

    active = await registry.get_active_faults()
    if not active:
        print("No active faults.")
        return 0

    print(f"Found {len(active)} active faults:")
    for f in active:
        print(f"  {f.fault_id}: {f.fault_type} on {f.target}")

    count = await registry.heal_all(method="manual_cli")
    print(f"\nHealed {count} faults.")
    return 0


# -------------------------------------------------------------------------
# Argument parser
# -------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentic_chaos",
        description="Agentic Chaos Monkey — controlled fault injection for 5G SA + IMS",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")

    sub = parser.add_subparsers(dest="command", required=True)

    # run
    p_run = sub.add_parser("run", help="Run a chaos scenario")
    p_run.add_argument("scenario", help="Scenario name (use list-scenarios to see options)")
    p_run.add_argument(
        "--agent", required=True, choices=["v1.5", "v3"],
        help="Agent version to evaluate (v1.5 or v3)",
    )

    # list-scenarios
    sub.add_parser("list-scenarios", help="List available scenarios")

    # list-episodes
    sub.add_parser("list-episodes", help="List recorded episodes")

    # show-episode
    p_show = sub.add_parser("show-episode", help="Show episode details")
    p_show.add_argument("episode_id", help="Episode ID (or partial match)")

    # heal-all
    sub.add_parser("heal-all", help="Emergency: heal all active faults")

    return parser


# -------------------------------------------------------------------------
# Main
# -------------------------------------------------------------------------

def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    _setup_logging(args.verbose)

    commands = {
        "run": cmd_run,
        "list-scenarios": cmd_list_scenarios,
        "list-episodes": cmd_list_episodes,
        "show-episode": cmd_show_episode,
        "heal-all": cmd_heal_all,
    }

    cmd_func = commands[args.command]
    return asyncio.run(cmd_func(args))


if __name__ == "__main__":
    sys.exit(main())
