"""
Challenge Mode Scorer — compares an RCA agent's Diagnosis against known ground truth.

The chaos platform knows exactly what fault was injected. The RCA agent does NOT
know — it only sees symptoms. The scorer evaluates how well the RCA agent
diagnosed the problem.

Scoring dimensions:
  - root_cause_correct: Did the agent identify the right component/failure?
  - component_overlap:  Jaccard similarity of affected components
  - severity_correct:   Did it assess severity accurately?
  - confidence_calibrated: High confidence + correct = well-calibrated
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger("chaos-scorer")


def score_diagnosis(
    diagnosis: dict,
    injected_faults: list[dict],
    scenario: dict,
) -> dict:
    """Score an RCA diagnosis against the known injected faults.

    Args:
        diagnosis: The RCA agent's Diagnosis (as dict with keys:
            summary, root_cause, affected_components, confidence, explanation).
        injected_faults: List of fault dicts from the episode (with target, fault_type).
        scenario: The scenario dict (with expected_symptoms, description).

    Returns:
        Scoring dict with root_cause_correct, component_overlap,
        severity_correct, confidence_calibrated, total_score.
    """
    # Ground truth: which containers were targeted
    truth_components = set()
    truth_targets = set()
    for f in injected_faults:
        target = f.get("target", "")
        truth_targets.add(target)
        truth_components.add(target)

    # RCA agent's answer
    rca_components = set(diagnosis.get("affected_components", []))
    rca_root_cause = diagnosis.get("root_cause", "").lower()
    rca_confidence = diagnosis.get("confidence", "low").lower()

    # --- Scoring ---

    # 1. Root cause correctness: does the RCA mention any of the targeted containers?
    root_cause_correct = any(
        target.lower() in rca_root_cause
        for target in truth_targets
    )
    # Also check for fault type keywords in root cause
    fault_type_keywords = _extract_fault_keywords(injected_faults)
    root_cause_has_fault_type = any(
        kw in rca_root_cause for kw in fault_type_keywords
    )

    # 2. Component overlap: recall-based (did the agent find all injected targets?)
    #    We use recall instead of Jaccard because agents correctly identifying
    #    cascade victims (e.g., pyhss/icscf when dns was killed) shouldn't be
    #    penalized for listing extra affected components.
    if truth_components:
        intersection = truth_components & rca_components
        component_overlap = len(intersection) / len(truth_components)
    elif not rca_components:
        component_overlap = 1.0  # Both empty = perfect match
    else:
        component_overlap = 0.0  # Agent listed components but none were injected

    # 3. Severity correctness: map fault types to expected severity
    expected_severity = _expected_severity(injected_faults)
    rca_severity = _infer_severity_from_diagnosis(diagnosis)
    severity_correct = expected_severity == rca_severity

    # 4. Confidence calibration: high confidence + correct = good
    is_correct = root_cause_correct
    confidence_calibrated = (
        (rca_confidence == "high" and is_correct)
        or (rca_confidence == "medium")
        or (rca_confidence == "low" and not is_correct)
    )

    # 5. Total score (weighted)
    total_score = (
        (0.40 * float(root_cause_correct))
        + (0.25 * component_overlap)
        + (0.15 * float(severity_correct))
        + (0.10 * float(root_cause_has_fault_type))
        + (0.10 * float(confidence_calibrated))
    )

    result = {
        "root_cause_correct": root_cause_correct,
        "root_cause_has_fault_type": root_cause_has_fault_type,
        "component_overlap": round(component_overlap, 3),
        "truth_components": sorted(truth_components),
        "rca_components": sorted(rca_components),
        "severity_correct": severity_correct,
        "expected_severity": expected_severity,
        "rca_severity": rca_severity,
        "confidence_calibrated": confidence_calibrated,
        "rca_confidence": rca_confidence,
        "total_score": round(total_score, 3),
    }

    log.info(
        "Challenge score: %.1f%% (root_cause=%s, components=%.0f%%, severity=%s)",
        total_score * 100,
        root_cause_correct,
        component_overlap * 100,
        severity_correct,
    )
    return result


def _extract_fault_keywords(faults: list[dict]) -> list[str]:
    """Extract keywords that the RCA should mention based on fault types."""
    keywords = []
    for f in faults:
        ft = f.get("fault_type", "")
        if "kill" in ft or "stop" in ft:
            keywords.extend(["kill", "crash", "down", "stopped", "dead", "exited"])
        elif "pause" in ft:
            keywords.extend(["pause", "frozen", "hung", "unresponsive", "timeout"])
        elif "latency" in ft:
            keywords.extend(["latency", "delay", "slow", "timeout"])
        elif "loss" in ft:
            keywords.extend(["loss", "packet loss", "drop"])
        elif "partition" in ft:
            keywords.extend(["partition", "unreachable", "network", "connectivity"])
        elif "corruption" in ft:
            keywords.extend(["corrupt", "malformed"])
        elif "bandwidth" in ft:
            keywords.extend(["bandwidth", "throttle", "slow", "congestion"])
    return keywords


def _expected_severity(faults: list[dict]) -> str:
    """Infer expected severity from fault types."""
    for f in faults:
        ft = f.get("fault_type", "")
        if "kill" in ft or "stop" in ft:
            return "down"
    # Network faults and pauses are typically "degraded"
    return "degraded"


def _infer_severity_from_diagnosis(diagnosis: dict) -> str:
    """Infer severity from the RCA text."""
    text = (
        diagnosis.get("root_cause", "")
        + " " + diagnosis.get("summary", "")
        + " " + diagnosis.get("explanation", "")
    ).lower()

    if any(w in text for w in ["down", "dead", "crash", "killed", "fatal", "outage"]):
        return "down"
    if any(w in text for w in ["degraded", "slow", "timeout", "latency", "loss"]):
        return "degraded"
    return "healthy"
