# Troubleshooting Agent v2 — Plan Review & Feedback
---

## Executive Summary

The transition to a multi-agent ADK architecture is a significant architectural leap that addresses the quadratic cost and context saturation of v1. The performance estimates (3x token reduction, 6x speed) are realistic given the "distillation" strategy. However, to ensure reliability in "edge case" failures, I've identified several areas for improvement.

---

## 1. Critical Findings

### 1.1 Deterministic Triage Single-Point-of-Failure
**Issue:** Phase 0 is a `BaseAgent` using pure Python logic to decide the `recommended_next_phase`. Telecom failures are often "gray". Metrics might look "Green" (containers running, some packets flowing), but the service is functionally "Red" (e.g., a subtle SIP header mismatch).  
**Risk:** If your Python logic determines the stack is `ready` and misses a subtle anomaly, it might skip the `Core Specialist` or `Data Specialist` entirely, leading to a "False Healthy" diagnosis.  
**Improvement:** Implement an **"LLM Triage Oversight"** step. If the deterministic triage finds no obvious errors, pass the summary to a **Gemini 3.0 Flash-Lite** agent for 1 turn to ask: "The user says there is a problem, but metrics look okay. Which specialists should I send anyway to be safe?"

---

## 2. Major Findings

### 2.1 Synthesis "Fact-Checking" Gap
**Issue:** The Synthesis Agent (Phase 3) receives only distilled `SubDiagnosis` objects, not raw logs. If a Specialist Agent misinterprets a log line (e.g., confuses a `403 Forbidden` with a `404 Not Found`), the Synthesis Agent has no way to verify the "Ground Truth."  
**Risk:** The system will "echo" the specialist's error into the final diagnosis.  
**Improvement:** The `SubDiagnosis` model must include a `raw_evidence_context` field that contains the **exact 10-20 log lines** or **full config block** that led to the finding. This allows the Synthesis Agent to perform a "Second Opinion" check.

### 2.2 Inter-Specialist Blindness in Parallel Execution
**Issue:** Specialists run in parallel via `ParallelAgent`. In complex failures, a finding in the **Core NF Specialist** (e.g., an N4 session failure) is critical context for the **IMS Specialist**.  
**Risk:** The IMS agent will waste its 5-tool budget looking for a SIP error that is actually caused by a PFCP timeout it cannot see.  
**Improvement:** Implement a **"Discovery Broadcast."** If a specialist finds a "High Confidence" root cause candidate, it could write it to a shared `session.state["emergency_notices"]` that other specialists can poll *if* they hit an "Inconclusive" state.

### 2.3 Aggressive Tool Budgets (3-5 calls)
**Issue:** For complex scenarios like a "BYE Storm" or a complex IMS registration sequence involving 5+ NFs, 5 tool calls is very tight. An agent might spend 2 calls just getting the right log tail and 1 call searching for a Call-ID, leaving only 2 calls for actual investigation.  
**Risk:** Specialists may return "Inconclusive" results for complex root causes.  
**Improvement:** Implement **Dynamic Budgets**. If a specialist reports they are "Warm" (found a partial match) but out of turns, the `InvestigationDirector` should allow a +3 turn extension.

### 2.4 Deterministic Dispatch "Stiff Neck" Problem
**Issue:** The plan uses a **BaseAgent (Deterministic Python)** for the Phase 2 Dispatch Logic. While this is fast, it prevents the system from correlating subtle clues across domains.

| **Approach** | **Pros** | **Cons** |
| :--- | :--- | :--- |
| **Deterministic** | Zero latency, zero cost, 100% predictable. | Brittle to "gray" failures; requires manual code updates for new NFs. |
| **LLM-Based** | Superior pattern recognition; adaptive to new NFs; provides a "Strategic Rationale." | Adds 1-2s latency and small token cost (~2-5k). |

**Risk:** If the failure point detected in Phase 1 is in the IMS domain but the *root cause* is in the Core domain (e.g., a PFCP timeout), the deterministic logic will never dispatch the Core Specialist, leading to an incomplete investigation.  
**Improvement:** Combine the **LLM Triage Oversight** (Critical Finding 1.1) and the **Dispatch Logic** into a single **Gemini 3.0 Flash-Lite** turn (Phase 1.5). This "Brain" agent will synthesize the Health + Trace data to decide the specialist list with a strategic rationale.

---

## 3. Minor Findings

### Token optimizations and tool usage caps
**Issue:** It is a bit early to try and optimize for token consumption and tool usage caps.  
**Improvement:** Do not worry too much about token consumption yet. Optimize for reliability and accuracy over token consumption at this point. We'll optimize and improve economics of the agent once it proves to be reliable enough.

---

## 4. Final Review Note
The multi-agent structure is the right path. By adding the **Triage/Dispatch Oversight** (Phase 1.5) and the **Evidence Context** in Phase 2, the system will become significantly more resilient to the "Long Tail" of complex telecom failures.
