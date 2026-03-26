"""
Challenge Mode Scorer — LLM-based evaluation of RCA agent diagnosis.

The chaos platform knows exactly what fault was injected. The RCA agent does NOT
know — it only sees symptoms. The scorer uses an LLM to evaluate how well the
RCA agent diagnosed the problem, comparing the raw diagnosis text against
ground truth.

Scoring dimensions:
  - root_cause_correct: Did the agent identify the right component/failure?
  - component_overlap:  Did it name the right container(s)?
  - severity_correct:   Did it assess severity accurately?
  - fault_type_identified: Did it identify the class of failure?
  - confidence_calibrated: Is confidence justified by evidence quality?
  - ranking_position:   Where did the correct cause rank in the agent's list?
"""

from __future__ import annotations

import json
import logging
import os

log = logging.getLogger("chaos-scorer")

_SCORER_MODEL = "gemini-2.5-flash"

_SCORER_PROMPT = """\
You are an evaluation judge for a telecom troubleshooting agent. Your job is to
score how well the agent diagnosed a fault that was injected into a 5G SA + IMS
network stack.

You will receive:
1. GROUND TRUTH — what was actually injected (this is 100% reliable)
2. AGENT DIAGNOSIS — the agent's raw output (this is what you are evaluating)

Score the diagnosis on these dimensions. For each, provide a boolean or numeric
score AND a one-sentence rationale explaining your judgment.

## Scoring Dimensions

1. **root_cause_correct** (bool): Did the agent identify the actual injected
   fault as the root cause (or primary cause)? The agent doesn't need to use
   the exact same words — semantic equivalence counts. For example, "DNS
   container crashed" = "dns service is down" = "BIND9 exited". If the agent
   listed multiple candidates, the correct cause must be ranked as the
   primary/top candidate to score True.

2. **component_overlap** (float 0.0-1.0): Did the agent name the correct
   container(s) that were targeted by the fault? Score 1.0 if all injected
   targets were identified. Do NOT penalize the agent for also listing
   downstream/cascading components — only check that the injected targets
   are present.

3. **severity_correct** (bool): Did the agent's assessment of severity match
   the actual impact? Container kills/stops = "down"/"outage"/"crashed".
   Network faults (latency/loss/corruption) = "degraded"/"slow"/"impaired".

4. **fault_type_identified** (bool): Did the agent identify the CLASS of
   failure? For container_kill: crash/down/exited/killed. For
   network_latency: delay/latency/slow/netem. For network_loss: packet
   loss/drops. For network_partition: unreachable/partitioned. For
   container_pause: frozen/hung/unresponsive.

5. **confidence_calibrated** (bool): Is the agent's stated confidence level
   appropriate given the quality of its diagnosis? High confidence + correct
   diagnosis = well calibrated. High confidence + wrong diagnosis = poorly
   calibrated. Low confidence + correct = also poorly calibrated (under-confident).

6. **ranking_position** (int or null): If the agent returned multiple ranked
   candidates/causes, what position (1-based) is the correct cause? 1 = top
   candidate, null = correct cause not listed at all. If the agent returned
   only one cause, use 1 if correct, null if wrong.

## Output Format

Return ONLY a JSON object (no markdown fences, no extra text):

{
  "root_cause_correct": true/false,
  "root_cause_rationale": "...",
  "component_overlap": 0.0-1.0,
  "component_rationale": "...",
  "severity_correct": true/false,
  "severity_rationale": "...",
  "fault_type_identified": true/false,
  "fault_type_rationale": "...",
  "confidence_calibrated": true/false,
  "confidence_rationale": "...",
  "ranking_position": 1/2/3/null,
  "ranking_rationale": "...",
  "total_score": 0.0-1.0,
  "summary": "One-sentence overall assessment"
}

Compute total_score as:
  0.40 × root_cause_correct
+ 0.25 × component_overlap
+ 0.15 × severity_correct
+ 0.10 × fault_type_identified
+ 0.10 × confidence_calibrated
"""


async def score_diagnosis(
    diagnosis_text: str,
    injected_faults: list[dict],
    scenario: dict,
) -> dict:
    """Score an RCA diagnosis using an LLM judge.

    Args:
        diagnosis_text: The raw diagnosis text from the RCA agent (unparsed).
        injected_faults: List of fault dicts from the episode (with target, fault_type, params).
        scenario: The scenario dict (with name, description, expected_symptoms).

    Returns:
        Scoring dict with all dimensions, rationales, and total_score.
    """
    # Build ground truth summary
    fault_descriptions = []
    for f in injected_faults:
        params = f.get("params", {})
        params_str = f" with params {params}" if params else ""
        fault_descriptions.append(
            f"- {f.get('fault_type', '?')} on container '{f.get('target', '?')}'{params_str}"
        )

    ground_truth = (
        f"Scenario: {scenario.get('name', '?')}\n"
        f"Description: {scenario.get('description', '?')}\n"
        f"Injected faults:\n" + "\n".join(fault_descriptions) + "\n"
        f"Expected symptoms: {', '.join(scenario.get('expected_symptoms', []))}"
    )

    # Build the evaluation prompt
    user_message = (
        f"## GROUND TRUTH\n\n{ground_truth}\n\n"
        f"## AGENT DIAGNOSIS\n\n{diagnosis_text}"
    )

    try:
        result = await _call_scorer_llm(user_message)
        log.info(
            "LLM score: %.0f%% (root_cause=%s, components=%.0f%%)",
            result.get("total_score", 0) * 100,
            result.get("root_cause_correct"),
            result.get("component_overlap", 0) * 100,
        )
        return result
    except Exception as e:
        log.error("LLM scorer failed, falling back to zero score: %s", e)
        return _fallback_score(str(e))


async def _call_scorer_llm(user_message: str) -> dict:
    """Call the LLM scorer and parse the response."""
    from google import genai
    from google.genai import types

    client = genai.Client(
        vertexai=os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").upper() == "TRUE",
        project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "northamerica-northeast1"),
    )

    response = await client.aio.models.generate_content(
        model=_SCORER_MODEL,
        contents=user_message,
        config=types.GenerateContentConfig(
            system_instruction=_SCORER_PROMPT,
            temperature=0.0,
            response_mime_type="application/json",
        ),
    )

    text = response.text.strip()

    # Parse the JSON response
    parsed = json.loads(text)

    # Validate and ensure required fields
    required_bools = ["root_cause_correct", "severity_correct",
                      "fault_type_identified", "confidence_calibrated"]
    for key in required_bools:
        if key not in parsed:
            parsed[key] = False

    if "component_overlap" not in parsed:
        parsed["component_overlap"] = 0.0

    if "total_score" not in parsed:
        # Recompute from components
        parsed["total_score"] = round(
            0.40 * float(parsed.get("root_cause_correct", False))
            + 0.25 * float(parsed.get("component_overlap", 0))
            + 0.15 * float(parsed.get("severity_correct", False))
            + 0.10 * float(parsed.get("fault_type_identified", False))
            + 0.10 * float(parsed.get("confidence_calibrated", False)),
            3,
        )

    return parsed


def _fallback_score(error_msg: str) -> dict:
    """Return a zero score when the LLM scorer fails."""
    return {
        "root_cause_correct": False,
        "root_cause_rationale": f"Scorer failed: {error_msg}",
        "component_overlap": 0.0,
        "component_rationale": "Scorer failed",
        "severity_correct": False,
        "severity_rationale": "Scorer failed",
        "fault_type_identified": False,
        "fault_type_rationale": "Scorer failed",
        "confidence_calibrated": False,
        "confidence_rationale": "Scorer failed",
        "ranking_position": None,
        "ranking_rationale": "Scorer failed",
        "total_score": 0.0,
        "summary": f"LLM scorer failed: {error_msg}",
    }
