"""
ChallengeAgent — invokes the agentic_ops troubleshooting agent to diagnose
the currently broken stack, then scores the diagnosis against ground truth.

The RCA agent sees the symptoms but does NOT know what fault was injected.
This creates a closed-loop eval framework for telecom RCA models.

Requires ANTHROPIC_API_KEY (or equivalent) for the troubleshooting agent.
If unavailable, Challenge Mode is skipped gracefully.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types

from ..scorer import score_diagnosis

log = logging.getLogger("chaos-agent.challenger")

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _get_v3_models() -> str:
    """Read the actual model names from v3 agent definitions."""
    try:
        ops_path = str(_REPO_ROOT / "operate")
        if ops_path not in sys.path:
            sys.path.insert(0, ops_path)

        from agentic_ops_v3.agents.triage import create_triage_agent
        from agentic_ops_v3.agents.synthesis import create_synthesis_agent

        models = set()
        for factory in [create_triage_agent, create_synthesis_agent]:
            agent = factory()
            if hasattr(agent, "model") and agent.model:
                models.add(str(agent.model))

        if models:
            return "+".join(sorted(models))
    except Exception:
        pass
    return "gemini-unknown"


def _parse_diagnosis_json(text: str) -> dict | None:
    """Extract a structured diagnosis dict from v3's free-text output.

    The v3 synthesis agent often returns JSON wrapped in ```json fences.
    This extracts and parses it, returning None if no valid JSON is found.
    """
    # Try to find JSON in ```json ... ``` fences
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find a raw JSON object
    match = re.search(r"\{[^{}]*\"root_cause\"[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # Try the entire text as JSON
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass

    return None


# Known container names in the stack — used to extract affected components
# from free-text diagnosis when JSON parsing fails
_KNOWN_CONTAINERS = {
    "dns", "mongo", "mysql", "nrf", "scp", "ausf", "udr", "udm",
    "amf", "smf", "upf", "pcf", "pcscf", "icscf", "scscf",
    "pyhss", "rtpengine", "nr_gnb", "e2e_ue1", "e2e_ue2",
}


def _extract_components_from_text(text: str) -> list[str]:
    """Scan diagnosis text for mentions of known container names."""
    text_lower = text.lower()
    found = []
    for name in _KNOWN_CONTAINERS:
        # Match the container name as a word boundary (avoid partial matches)
        # e.g., "dns" in "dns container" but not "dnsmasq"
        if re.search(rf"\b{re.escape(name)}\b", text_lower):
            found.append(name)
    return sorted(found)


def _extract_confidence_from_text(text: str) -> str:
    """Extract confidence level from diagnosis text."""
    text_lower = text.lower()
    # Look for explicit confidence statements
    match = re.search(r"confidence[:\s]+['\"]?(high|medium|low)['\"]?", text_lower)
    if match:
        return match.group(1)
    return ""


class ChallengeAgent(BaseAgent):
    """Invokes the RCA agent on the broken stack and scores its diagnosis."""

    name: str = "ChallengeAgent"
    description: str = (
        "Challenge Mode: invokes the troubleshooting agent to diagnose "
        "the injected fault, then scores the diagnosis."
    )

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        scenario = ctx.session.state.get("scenario", {})
        agent_version = ctx.session.state.get("agent_version", "v1.5")

        # Check if challenge mode is enabled for this scenario
        if not scenario.get("challenge_mode", False):
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[types.Part(text="Challenge Mode: skipped (not enabled for this scenario)")],
                ),
            )
            return

        # Check if the RCA agent is available
        if not self._rca_agent_available(agent_version):
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[types.Part(text=(
                        f"Challenge Mode: skipped ({agent_version} agent not available — "
                        "check API keys and imports)"
                    ))],
                ),
            )
            return

        log.info("Challenge Mode: invoking %s agent...", agent_version)

        faults_injected = ctx.session.state.get("faults_injected", [])
        observations = ctx.session.state.get("observations", [])

        # Build a question for the RCA agent based on observed symptoms
        question = self._build_question(scenario, observations)

        start_time = time.time()
        try:
            diagnosis_dict = await self._run_rca_agent(question, agent_version)
        except Exception as e:
            log.error("RCA agent failed: %s", e)
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[types.Part(text=f"Challenge Mode: RCA agent error — {e}")],
                ),
            )
            return

        elapsed = time.time() - start_time

        # Score the diagnosis
        score = score_diagnosis(
            diagnosis=diagnosis_dict,
            injected_faults=faults_injected,
            scenario=scenario,
        )

        if agent_version == "v3":
            rca_model = f"v3-adk/{_get_v3_models()}"
        else:
            rca_model = f"v1.5-pydantic/{os.environ.get('AGENT_MODEL', 'google-vertex:gemini-2.5-pro')}"

        token_usage = diagnosis_dict.get("_token_usage", {})

        challenge_result = {
            "rca_agent_model": rca_model,
            "diagnosis_summary": diagnosis_dict.get("summary", ""),
            "diagnosis_root_cause": diagnosis_dict.get("root_cause", ""),
            "diagnosis_affected_components": diagnosis_dict.get("affected_components", []),
            "diagnosis_confidence": diagnosis_dict.get("confidence", ""),
            "diagnosis_explanation": diagnosis_dict.get("explanation", ""),
            "score": score,
            "time_to_diagnosis_seconds": round(elapsed, 1),
            "token_usage": token_usage,
        }

        msg = (
            f"Challenge Mode complete ({elapsed:.1f}s)\n"
            f"  RCA summary: {diagnosis_dict.get('summary', '?')[:100]}\n"
            f"  Score: {score['total_score']:.0%}\n"
            f"    Root cause correct: {score['root_cause_correct']}\n"
            f"    Component overlap:  {score['component_overlap']:.0%}\n"
            f"    Severity correct:   {score['severity_correct']}"
        )
        log.info("Challenge Mode: score=%.0f%%", score["total_score"] * 100)

        yield Event(
            author=self.name,
            content=types.Content(parts=[types.Part(text=msg)]),
            actions=EventActions(state_delta={"challenge_result": challenge_result}),
        )

    def _rca_agent_available(self, agent_version: str = "v1.5") -> bool:
        """Check if the specified RCA agent can be instantiated."""
        ops_path = str(_REPO_ROOT / "operate")
        if ops_path not in sys.path:
            sys.path.insert(0, ops_path)

        if agent_version == "v3":
            # v3 uses Google ADK (Vertex AI)
            has_key = bool(
                os.environ.get("GOOGLE_CLOUD_PROJECT")
                or os.environ.get("GOOGLE_GENAI_USE_VERTEXAI")
            )
            if not has_key:
                return False
            try:
                from agentic_ops_v3.orchestrator import investigate  # noqa: F401
                return True
            except ImportError:
                return False
        else:
            # v1.5 uses Pydantic AI — defaults to Vertex AI (gemini-2.5-pro)
            # but can also use Anthropic via AGENT_MODEL env var
            has_key = bool(
                os.environ.get("GOOGLE_CLOUD_PROJECT")
                or os.environ.get("ANTHROPIC_API_KEY")
                or os.environ.get("AGENT_MODEL")
            )
            if not has_key:
                return False
            try:
                from agentic_ops.agent import create_agent  # noqa: F401
                return True
            except ImportError:
                return False

    def _build_question(self, scenario: dict, observations: list[dict]) -> str:
        """Build a diagnostic question from observed symptoms."""
        # Collect all notable log lines from observations
        all_logs: dict[str, list[str]] = {}
        for obs in observations:
            for container, lines in obs.get("log_samples", {}).items():
                all_logs.setdefault(container, []).extend(lines)

        # Collect metrics deltas
        all_deltas: dict[str, dict] = {}
        for obs in observations:
            for node, delta in obs.get("metrics_delta", {}).items():
                all_deltas.setdefault(node, {}).update(delta)

        parts = [
            "The 5G SA + IMS stack is experiencing issues. ",
            "Investigate and diagnose the root cause.\n\n",
        ]

        if all_logs:
            parts.append("Recent error logs observed:\n")
            for container, lines in sorted(all_logs.items()):
                for line in lines[:5]:  # Limit per container
                    parts.append(f"  [{container}] {line}\n")

        if all_deltas:
            parts.append("\nMetrics changes detected:\n")
            for node, deltas in sorted(all_deltas.items()):
                for metric, vals in deltas.items():
                    parts.append(
                        f"  [{node}] {metric}: "
                        f"{vals.get('baseline', '?')} → {vals.get('current', '?')}\n"
                    )

        return "".join(parts)

    async def _run_rca_agent(self, question: str, agent_version: str = "v1.5") -> dict:
        """Run the specified troubleshooting agent and return its diagnosis."""
        ops_path = str(_REPO_ROOT / "operate")
        if ops_path not in sys.path:
            sys.path.insert(0, ops_path)

        if agent_version == "v3":
            return await self._run_v3_agent(question)
        return await self._run_v15_agent(question)

    async def _run_v15_agent(self, question: str) -> dict:
        """Run the v1.5 (Pydantic AI) troubleshooting agent."""
        from agentic_ops.agent import create_agent
        from agentic_ops.models import AgentDeps
        from agentic_chaos.tools.observation_tools import _load_env

        env = _load_env()
        pyhss_api = f"http://{env.get('PYHSS_IP', '172.22.0.18')}:8080"
        deps = AgentDeps(repo_root=_REPO_ROOT, env=env, pyhss_api=pyhss_api)

        agent = create_agent()
        result = await agent.run(question, deps=deps)

        if result and result.output:
            out = result.output.model_dump()
            # Attach token usage from pydantic-ai
            usage = result.usage()
            out["_token_usage"] = {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "total_tokens": usage.input_tokens + usage.output_tokens,
                "requests": usage.requests,
                "tool_calls": usage.tool_calls,
            }
            return out

        return {"summary": "Agent produced no output", "affected_components": []}

    async def _run_v3_agent(self, question: str) -> dict:
        """Run the v3 (ADK multi-phase) troubleshooting agent."""
        from agentic_ops_v3.orchestrator import investigate

        result = await investigate(question)

        # v3's diagnosis is often a JSON string (possibly wrapped in ```json fences)
        diagnosis_raw = result.get("diagnosis", "")
        diagnosis_str = str(diagnosis_raw)

        # Try to parse structured JSON from the diagnosis
        parsed = _parse_diagnosis_json(diagnosis_str)

        if parsed:
            components = parsed.get("affected_components", [])
            confidence = parsed.get("confidence", "")
        else:
            components = []
            confidence = ""

        # If JSON parsing didn't yield components, extract them from the text
        # by scanning for known container names mentioned in the diagnosis
        if not components:
            components = _extract_components_from_text(diagnosis_str)

        # If confidence wasn't found, look for it in the text
        if not confidence:
            confidence = _extract_confidence_from_text(diagnosis_str)

        summary = (parsed or {}).get("summary", diagnosis_str[:500]) if diagnosis_str else "Agent produced no output"
        root_cause = (parsed or {}).get("root_cause", diagnosis_str)
        explanation = (parsed or {}).get("explanation", diagnosis_str)

        # Extract token usage from v3's investigation trace
        trace = result.get("investigation_trace", {})
        total_tokens_obj = trace.get("total_tokens", {})
        token_usage = {
            "input_tokens": total_tokens_obj.get("prompt", 0),
            "output_tokens": total_tokens_obj.get("completion", 0),
            "thinking_tokens": total_tokens_obj.get("thinking", 0),
            "total_tokens": total_tokens_obj.get("total", result.get("total_tokens", 0)),
        }
        # Include per-phase breakdown
        phases = trace.get("phases", [])
        if phases:
            token_usage["per_phase"] = [
                {
                    "agent": p.get("agent_name", "?"),
                    "tokens": p.get("tokens", {}).get("total", 0),
                    "tool_calls": len(p.get("tool_calls", [])),
                    "llm_calls": p.get("llm_calls", 0),
                }
                for p in phases
            ]

        return {
            "summary": summary,
            "root_cause": root_cause,
            "affected_components": components,
            "confidence": confidence,
            "explanation": explanation,
            "_token_usage": token_usage,
            "_v3_full_result": result,
        }

    async def _run_live_impl(self, ctx):
        raise NotImplementedError
