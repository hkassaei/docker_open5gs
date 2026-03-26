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

        # Get the raw diagnosis text for the LLM scorer
        diagnosis_text = diagnosis_dict.get("_raw_diagnosis", "")
        if not diagnosis_text:
            # Fallback: reconstruct from parsed fields
            diagnosis_text = diagnosis_dict.get("root_cause", diagnosis_dict.get("summary", ""))

        # Score the diagnosis using LLM judge
        score = await score_diagnosis(
            diagnosis_text=diagnosis_text,
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
            "diagnosis_text": diagnosis_text,
            "score": score,
            "time_to_diagnosis_seconds": round(elapsed, 1),
            "token_usage": token_usage,
        }

        total = score.get("total_score", 0)
        msg = (
            f"Challenge Mode complete ({elapsed:.1f}s)\n"
            f"  Score: {total:.0%}\n"
            f"    Root cause correct: {score.get('root_cause_correct')}\n"
            f"    Component overlap:  {score.get('component_overlap', 0):.0%}\n"
            f"    Severity correct:   {score.get('severity_correct')}\n"
            f"  Scorer summary: {score.get('summary', '?')}"
        )
        log.info("Challenge Mode: score=%.0f%%", total * 100)

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
            # Include the full diagnosis as raw text for the LLM scorer
            out["_raw_diagnosis"] = json.dumps(out, indent=2, default=str)
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

        return {"_raw_diagnosis": "Agent produced no output"}

    async def _run_v3_agent(self, question: str) -> dict:
        """Run the v3 (ADK multi-phase) troubleshooting agent."""
        from agentic_ops_v3.orchestrator import investigate

        result = await investigate(question)

        # The raw diagnosis text — passed directly to the LLM scorer
        diagnosis_raw = str(result.get("diagnosis", ""))

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
            "_raw_diagnosis": diagnosis_raw,
            "_token_usage": token_usage,
        }

    async def _run_live_impl(self, ctx):
        raise NotImplementedError
