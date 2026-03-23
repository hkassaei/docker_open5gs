"""
Phase 2 Router: Strategic Dispatch — LLM-driven specialist selection.

Reads the triage report and trace result, then uses Gemini Flash (1 turn)
to decide which specialist agents to dispatch. Cross-domain correlation
enables dispatching the right specialists even when the failure point
and root cause are in different domains.
"""

from __future__ import annotations

import json
import logging
from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types, Client
from pathlib import Path

log = logging.getLogger("v2.dispatcher")

_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "dispatcher.md"
_DEFAULT_SPECIALISTS = ["ims", "transport"]
_VALID_SPECIALISTS = {"ims", "transport", "core", "subscriber_data"}


class DispatchAgent(BaseAgent):
    """Phase 2 router: uses LLM to strategically select specialist agents."""

    name: str = "DispatchAgent"
    description: str = "Decides which specialist agents to dispatch based on triage and trace."

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        triage = ctx.session.state.get("triage", {})
        trace = ctx.session.state.get("trace", "")

        # Build the LLM prompt with triage + trace context
        system_prompt = _PROMPT_PATH.read_text()
        context = (
            f"## Triage Report\n{json.dumps(triage, indent=2, default=str)[:1500]}\n\n"
            f"## Trace Result\n{trace if isinstance(trace, str) else json.dumps(trace, indent=2, default=str)[:1500]}\n\n"
            f"Which specialists should we dispatch?"
        )

        specialists = _DEFAULT_SPECIALISTS
        rationale = "default fallback"

        try:
            client = Client(vertexai=True)
            response = await client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    types.Content(role="user", parts=[
                        types.Part(text=f"{system_prompt}\n\n{context}")
                    ]),
                ],
            )
            text = response.text.strip()

            # Parse JSON from response
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            parsed = json.loads(text)
            raw_specialists = parsed.get("specialists", [])
            rationale = parsed.get("rationale", "LLM-selected")

            # Validate specialist names
            valid = [s for s in raw_specialists if s in _VALID_SPECIALISTS]
            if valid:
                specialists = valid
            else:
                log.warning("LLM returned no valid specialists: %s, using defaults", raw_specialists)

        except Exception as e:
            log.warning("Dispatch LLM failed (%s), using defaults: %s", e, _DEFAULT_SPECIALISTS)

        log.info("Dispatching specialists: %s (rationale: %s)", specialists, rationale)

        yield Event(
            author=self.name,
            content=types.Content(parts=[types.Part(text=(
                f"Dispatching: {', '.join(specialists)} — {rationale}"
            ))]),
            actions=EventActions(state_delta={
                "dispatch": {
                    "specialists": specialists,
                    "rationale": rationale,
                },
                "emergency_notices": [],  # Initialize for parallel specialists
            }),
        )

    async def _run_live_impl(self, ctx):
        raise NotImplementedError
