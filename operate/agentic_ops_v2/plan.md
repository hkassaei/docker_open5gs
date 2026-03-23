# Troubleshooting Agent v2 — Multi-Agent Implementation Plan

**Date:** 2026-03-20
**Status:** Ready for implementation
**Framework:** Google ADK (same as agentic_chaos)
**Predecessor:** `operate/agentic_ops/` (Pydantic AI single agent, v1/v1.5)

---

## Why v2

The v1.5 single agent was tested against a real failure (UE1→UE2 call failure, `udp_mtu_try_proto=TCP`). Two runs:

| | v1 (6 tools, original prompt) | v1.5 (11 tools, improved prompt) |
|---|---|---|
| Score | 10% | 90% |
| Tokens | 200K | 159K |
| Time | ~2 min | ~1.5 min |
| Root cause | Wrong (blamed I-CSCF Diameter) | Correct (P-CSCF TCP transport) |

v1.5 proved the tools and methodology are right. But the single-agent architecture has structural limits:

1. **Context saturation** — ~37K of useful tool data, but 159K total tokens because the system prompt (~3K) and accumulated conversation history are re-sent on every LLM round. 8 rounds × growing context = quadratic cost.
2. **Methodology not enforced** — v1 had "check both ends" in the system prompt; the agent ignored it. v1.5 improved compliance but it's still advisory, not architectural.
3. **No parallelism** — checking UE1, UE2, metrics, and Diameter state are independent operations serialized into 8 sequential rounds.
4. **No pruning** — no checkpoint where the system asks "given what triage found, which specialists should run?"

v2 solves these with a multi-agent architecture where each phase runs with a clean context, phases are gated, and specialists run in parallel.

### Estimated v2 performance on the same failure

| Phase | Agents | Tokens | Time | Result |
|---|---|---|---|---|
| Phase 0: Triage | 1 (deterministic) | ~8K | ~3s | Stack healthy, IMS stats captured |
| Phase 1: Trace | 1 (LLM) | ~15K | ~5s | UE2 never received Call-ID |
| Phase 2: Specialists | 1-2 (parallel) | ~15K | ~5s | `udp_mtu_try_proto=TCP` + UE2 UDP-only |
| Phase 3: Synthesis | 1 (LLM) | ~10K | ~3s | Correct diagnosis assembled |
| **Total** | | **~50K** | **~16s** | **Correct, ~85%+ score** |

vs. v1.5: 159K tokens, ~90s. A **3x token reduction** and **6x speed improvement**.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                                                                       │
│   User Question                                                       │
│   "UE1 can't call UE2. Both registered. Investigate."                │
│                                                                       │
│   ┌───────────────────────────────────────────────────────────────┐  │
│   │           INVESTIGATION DIRECTOR (ADK SequentialAgent)         │  │
│   │                                                                │  │
│   │   ┌────────────────────────────────────────────────────────┐  │  │
│   │   │  Phase 0: TRIAGE (BaseAgent + LLM Oversight)           │  │  │
│   │   │                                                         │  │  │
│   │   │  Step 1: Deterministic metrics collection               │  │  │
│   │   │    get_nf_metrics, query_prometheus,                    │  │  │
│   │   │    get_network_status, read_env_config                  │  │  │
│   │   │                                                         │  │  │
│   │   │  Step 2: Deterministic classification                   │  │  │
│   │   │    data_plane_status, ims_status, anomalies[]           │  │  │
│   │   │                                                         │  │  │
│   │   │  Step 3: LLM Oversight (Gemini Flash, 1 turn)          │  │  │
│   │   │    If no anomaly found but user reports a problem →     │  │  │
│   │   │    ask LLM: "metrics look healthy, which specialists    │  │  │
│   │   │    should we dispatch to be safe?"                      │  │  │
│   │   │    (catches gray failures deterministic logic misses)   │  │  │
│   │   │                                                         │  │  │
│   │   │  Output → state["triage"]: TriageReport                 │  │  │
│   │   └────────────────────────────────────────────────────────┘  │  │
│   │                          │                                     │  │
│   │                          ▼                                     │  │
│   │   ┌────────────────────────────────────────────────────────┐  │  │
│   │   │  Phase 1: END-TO-END TRACE (LlmAgent, Gemini Flash)   │  │  │
│   │   │                                                         │  │  │
│   │   │  Reads: state["triage"], user question                  │  │  │
│   │   │  Tools: read_container_logs (UE1 + UE2),                │  │  │
│   │   │         search_logs (Call-ID across all containers)     │  │  │
│   │   │                                                         │  │  │
│   │   │  Output → state["trace"]: TraceResult                   │  │  │
│   │   │    call_id, nodes_that_saw_it[],                        │  │  │
│   │   │    nodes_that_did_not[], failure_point,                 │  │  │
│   │   │    error_messages{}                                     │  │  │
│   │   └────────────────────────────────────────────────────────┘  │  │
│   │                          │                                     │  │
│   │                          ▼                                     │  │
│   │   ┌────────────────────────────────────────────────────────┐  │  │
│   │   │  Phase 2: STRATEGIC DISPATCH (LlmAgent, Gemini Flash)  │  │  │
│   │   │                                                         │  │  │
│   │   │  Reads: state["triage"] + state["trace"]                │  │  │
│   │   │  LLM correlates clues across domains to decide which    │  │  │
│   │   │  specialists to run (cross-domain failures need this)   │  │  │
│   │   │                                                         │  │  │
│   │   │  Dispatches selected specialists via ParallelAgent:     │  │  │
│   │   │                                                         │  │  │
│   │   │  ┌──────────────┐ ┌──────────────┐ ┌────────────────┐ │  │  │
│   │   │  │ IMS          │ │ Core NF      │ │ Transport      │ │  │  │
│   │   │  │ Specialist   │ │ Specialist   │ │ Specialist     │ │  │  │
│   │   │  │ (Pro)        │ │ (Pro)        │ │ (Flash)        │ │  │  │
│   │   │  │              │ │              │ │                │ │  │  │
│   │   │  │ logs, kamcmd │ │ logs, prom,  │ │ running_config │ │  │  │
│   │   │  │ run_config   │ │ run_config   │ │ listeners,     │ │  │  │
│   │   │  │              │ │              │ │ kamcmd         │ │  │  │
│   │   │  └──────┬───────┘ └──────┬───────┘ └───────┬────────┘ │  │  │
│   │   │         │                │                  │          │  │  │
│   │   │         └──── emergency_notices (shared) ───┘          │  │  │
│   │   │              High-confidence findings broadcast        │  │  │
│   │   │              to other specialists via state             │  │  │
│   │   │                                                         │  │  │
│   │   │  Also available:                                        │  │  │
│   │   │  ┌──────────────────┐                                  │  │  │
│   │   │  │ Subscriber Data  │  query_subscriber,               │  │  │
│   │   │  │ Specialist       │  query_prometheus                │  │  │
│   │   │  │ (Flash)          │                                  │  │  │
│   │   │  └──────────────────┘                                  │  │  │
│   │   │                                                         │  │  │
│   │   │  Dynamic budgets: initial 3-5 calls per specialist,     │  │  │
│   │   │  +3 extension if specialist reports "warm" finding      │  │  │
│   │   │                                                         │  │  │
│   │   │  Output → state["findings"]: dict[str, SubDiagnosis]   │  │  │
│   │   │    (each includes raw_evidence_context for fact-check)  │  │  │
│   │   └────────────────────────────────────────────────────────┘  │  │
│   │                          │                                     │  │
│   │                          ▼                                     │  │
│   │   ┌────────────────────────────────────────────────────────┐  │  │
│   │   │  Phase 3: SYNTHESIS (LlmAgent, Gemini Pro)             │  │  │
│   │   │                                                         │  │  │
│   │   │  Reads: state["triage"] + state["trace"]                │  │  │
│   │   │         + state["findings"] (with raw_evidence_context) │  │  │
│   │   │  Tools: none (reasoning only)                           │  │  │
│   │   │                                                         │  │  │
│   │   │  Merges specialist findings into final Diagnosis.       │  │  │
│   │   │  Fact-checks specialist interpretations against the     │  │  │
│   │   │  raw evidence context (10-20 log lines per finding).    │  │  │
│   │   │                                                         │  │  │
│   │   │  Output → state["diagnosis"]: Diagnosis                 │  │  │
│   │   │    summary, timeline, root_cause,                       │  │  │
│   │   │    affected_components, recommendation,                 │  │  │
│   │   │    confidence, explanation                              │  │  │
│   │   └────────────────────────────────────────────────────────┘  │  │
│   │                                                                │  │
│   └───────────────────────────────────────────────────────────────┘  │
│                                                                       │
│   Output: Diagnosis (same schema as v1 — GUI compatible)             │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Data Models

```python
# Phase 0 output
class TriageReport(BaseModel):
    stack_phase: str              # "ready" / "partial" / "down"
    data_plane_status: str        # "healthy" / "degraded" / "dead"
    control_plane_status: str     # "healthy" / "degraded" / "down"
    ims_status: str               # "healthy" / "degraded" / "down"
    anomalies: list[str]          # ["GTP packets = 0", "P-CSCF 0 registered contacts"]
    metrics_summary: dict         # compact metrics keyed by NF
    recommended_next_phase: str   # "end_to_end_trace" / "data_plane_probe" / "ims_analysis"

# Phase 1 output
class TraceResult(BaseModel):
    call_id: str                          # extracted from UE logs
    request_type: str                     # "INVITE" / "REGISTER" / etc.
    nodes_that_saw_it: list[str]          # ["e2e_ue1", "pcscf", "scscf", "icscf"]
    nodes_that_did_not: list[str]         # ["e2e_ue2"]
    failure_point: str                    # "between pcscf and e2e_ue2"
    error_messages: dict[str, str]        # {"icscf": "500 Server error on LIR..."}
    originating_ue: str                   # "e2e_ue1"
    terminating_ue: str                   # "e2e_ue2"

# Phase 2 output (per specialist)
class SubDiagnosis(BaseModel):
    specialist: str               # "ims" / "core" / "transport" / "subscriber_data"
    finding: str                  # one-line finding
    evidence: list[str]           # specific log lines or config values
    raw_evidence_context: str     # 10-20 raw log lines or full config block that
                                  # led to the finding — allows Synthesis Agent to
                                  # fact-check the specialist's interpretation
    root_cause_candidate: str     # proposed root cause
    disconfirm_check: str         # what was checked to verify
    confidence: str               # "high" / "medium" / "low"

# Phase 3 output (same as v1 — backward compatible)
class Diagnosis(BaseModel):
    summary: str
    timeline: list[TimelineEvent]
    root_cause: str
    affected_components: list[str]
    recommendation: str
    confidence: str
    explanation: str
```

---

## Shared State Flow

```
session.state keys:

  "user_question"        ← set by runner (user's input)
  "triage"               ← Phase 0: TriageReport (structured, ~500 tokens)
  "trace"                ← Phase 1: TraceResult (structured, ~300 tokens)
  "emergency_notices"    ← Phase 2: list[str] — high-confidence findings broadcast
                            by specialists during parallel execution (see below)
  "findings"             ← Phase 2: {"ims": SubDiagnosis, "transport": SubDiagnosis, ...}
  "diagnosis"            ← Phase 3: Diagnosis (final output, ~500 tokens)
```

Each phase reads the previous phase's structured output — NOT raw logs. The Synthesis Agent receives structured findings plus `raw_evidence_context` from each specialist, allowing it to fact-check interpretations against the source evidence.

### Inter-Specialist Discovery Broadcast

When specialists run in parallel, they can't see each other's findings in real time. This is normally fine — most failures are domain-specific. But in complex cascading failures (e.g., an N4/PFCP timeout causing an IMS call failure), a finding in one specialist is critical context for another.

**Mechanism:** If a specialist finds a high-confidence root cause candidate, it writes a one-line notice to `state["emergency_notices"]`:

```python
# Inside a specialist, when a high-confidence finding is made:
notices = ctx.session.state.get("emergency_notices", [])
notices.append("Core Specialist: PFCP session to UPF timed out — data plane may be affected")
ctx.session.state["emergency_notices"] = notices
```

Other specialists can poll this at the start of each tool call. If they hit an "inconclusive" state and an emergency notice is relevant, they can pivot their remaining budget accordingly. This is a lightweight coordination mechanism — no inter-agent messaging, just shared state.

---

## Agent Specifications

### Phase 0: Triage Agent

**Type:** `BaseAgent` (deterministic metrics collection + LLM oversight for gray failures)

**Step 1 — Deterministic collection (no LLM):**
- `get_nf_metrics()` — full stack health snapshot
- `query_prometheus("fivegs_ep_n3_gtp_indatapktn3upf")` — GTP data plane check
- `get_network_status()` — container up/down
- `read_env_config()` — topology discovery

**Step 2 — Deterministic classification:**
```python
if gtp_in == 0 and gtp_out == 0 and sessions > 0:
    data_plane_status = "dead"
elif pcscf_registered_contacts == 0:
    ims_status = "degraded"
```

**Step 3 — LLM Oversight (Gemini 2.5 Flash, 1 turn):**

If the deterministic check finds no obvious anomaly but the user is reporting a problem, the triage summary is passed to a fast LLM for one turn:

> "The user reports a problem, but metrics look healthy. Here is the metrics summary. Which specialists should we dispatch to be safe? Respond with a JSON list."

This catches "gray" failures where metrics are green but the service is functionally broken (e.g., subtle SIP header mismatch, stale registration state, config drift). The LLM adds ~2-3K tokens and ~2 seconds but prevents the "False Healthy" trap where the deterministic logic skips specialists that are actually needed.

**Token cost:** ~10K (tool results + 1 LLM turn for oversight)

### Phase 1: End-to-End Trace Agent

**Type:** `LlmAgent` (Gemini 2.5 Flash — fast, cheap)
**Model:** `gemini-2.5-flash`
**Tools:**
- `read_container_logs` — read caller and callee UE logs
- `search_logs` — trace Call-ID across all containers

**System prompt (~500 tokens):**
```
You are tracing a SIP/5G request end-to-end across the stack.

Your job:
1. Read the caller UE logs to find the Call-ID and error.
2. Read the callee UE logs to check if the request arrived.
3. Search for the Call-ID across all containers.
4. Report which containers saw the request and which did not.
5. Identify the failure point: the last node that saw it and
   the first node that should have but didn't.

Do NOT diagnose the root cause. Just trace where the request stopped.
```

**Budget:** 3-4 tool calls
**Token cost:** ~15K (3 LLM rounds with small context)

### Phase 2: Specialist Agents

#### IMS Specialist

**Type:** `LlmAgent` (Gemini 2.5 Pro — needs protocol reasoning)
**Model:** `gemini-2.5-pro`
**Tools:**
- `read_container_logs` (restricted to: pcscf, icscf, scscf, pyhss)
- `run_kamcmd` — Diameter peers, usrloc, transaction stats
- `read_running_config` — actual Kamailio config from running container

**System prompt (~400 tokens):**
```
You are an IMS/SIP specialist. You have been given a triage report
and a trace showing where the SIP request stopped.

Investigate the IMS nodes around the failure point. Check:
- Kamailio logs for errors, transaction timeouts
- Diameter peer state (kamcmd cdp.list_peers)
- SIP routing config
- usrloc registration state

Report your finding with evidence. State what you checked to
verify your conclusion AND what would disprove it.
```

**Initial budget:** 5 tool calls (extendable — see Dynamic Budgets below)
**Context input:** TriageReport + TraceResult (~800 tokens) — NOT previous raw logs

#### Transport Specialist

**Type:** `LlmAgent` (Gemini 2.5 Flash — simple checks)
**Model:** `gemini-2.5-flash`
**Tools:**
- `read_running_config` — check `udp_mtu_try_proto`, listen addresses
- `check_process_listeners` — TCP vs UDP listener state
- `run_kamcmd` — transport-related stats

**System prompt (~300 tokens):**
```
You are a transport-layer specialist. A SIP request was sent to a
destination but never received. Your job is to determine if the
delivery failure is caused by a transport-layer issue.

Check:
1. What transport protocol the sending node uses (UDP/TCP/TLS)
2. What transport the receiving node listens on
3. The udp_mtu_try_proto setting (TCP causes silent failure to UDP-only UEs)
4. Any listen address mismatches
```

**Initial budget:** 3 tool calls (extendable)
**Dispatched when:** Phase 1 trace shows `nodes_that_did_not` includes a UE (request sent but not received)

#### Core NF Specialist

**Type:** `LlmAgent` (Gemini 2.5 Pro)
**Model:** `gemini-2.5-pro`
**Tools:**
- `read_container_logs` (restricted to: amf, smf, upf, nrf, pcf)
- `query_prometheus` — 5G core metrics
- `read_running_config` — Open5GS YAML configs

**System prompt (~400 tokens):**
```
You are a 5G core specialist. Investigate the 5G core NFs around
the failure point. Check AMF registration, SMF session management,
UPF data plane, PFCP associations, and GTP-U tunnel state.
```

**Initial budget:** 5 tool calls (extendable)
**Dispatched when:** Triage shows data plane or control plane issues

#### Subscriber Data Specialist

**Type:** `LlmAgent` (Gemini 2.5 Flash)
**Model:** `gemini-2.5-flash`
**Tools:**
- `query_subscriber` — MongoDB + PyHSS subscriber lookup
- `query_prometheus` — subscriber count metrics

**System prompt (~200 tokens):**
```
You are a subscriber data specialist. Check if the subscriber
exists in both the 5G core (MongoDB) and IMS (PyHSS) databases
with correct credentials and provisioning.
```

**Initial budget:** 3 tool calls (extendable)
**Dispatched when:** Triage or trace suggest authentication/registration failures

### Dynamic Budgets

Specialists start with an initial budget (3-5 tool calls). If a specialist reports it is "warm" — it found a partial match but needs more investigation to confirm — the orchestrator grants a **+3 call extension**. This prevents premature "inconclusive" results on complex failures (e.g., BYE storms, multi-hop IMS registration sequences) while still providing a soft guidance that encourages focus.

```python
# After specialist returns:
if sub_diagnosis.confidence == "low" and "partial" in sub_diagnosis.finding.lower():
    # Grant extension and re-run the specialist with updated context
    specialist.budget += 3
    re_run(specialist)
```

**Note on token optimization:** At this stage, we optimize for reliability and accuracy, not token consumption. Hard budget caps are avoided — better to spend extra tokens and get the right diagnosis than to save tokens and miss the root cause. Token economics will be optimized once the agent proves reliable.

### Phase 2 Dispatch Logic (LlmAgent — strategic routing)

The dispatcher is an `LlmAgent` (Gemini 2.5 Flash, 1 turn) that receives the triage report and trace result and decides which specialists to dispatch. This replaces the original deterministic Python routing.

**Why LLM over deterministic:** Telecom failures often cross domain boundaries. A PFCP timeout (core domain) can manifest as an IMS call failure (IMS domain). Deterministic routing based on `failure_point` would dispatch only the IMS specialist, missing the core root cause. The LLM can correlate subtle clues across the triage anomalies and trace errors to make a strategic dispatch decision.

**System prompt (~300 tokens):**
```
You are the investigation strategist. Based on the triage report
(stack health, anomalies) and the end-to-end trace (where the
request stopped, error messages), decide which specialists to dispatch.

Available specialists:
- ims: SIP/Diameter/Kamailio analysis (for IMS signaling failures)
- transport: UDP/TCP transport layer checks (for delivery failures)
- core: 5G core NF analysis (for data/control plane failures)
- subscriber_data: Subscriber provisioning checks (for auth/registration failures)

Respond with a JSON object:
{"specialists": ["ims", "transport"], "rationale": "Request stopped between P-CSCF and UE2, suggesting delivery + possible transport issue"}

When in doubt, include more specialists rather than fewer — a missed
specialist costs more than an extra one.
```

**Model:** `gemini-2.5-flash` (1 turn, ~3K tokens)
**Fallback:** If the LLM response is unparseable, fall back to `["ims", "transport"]` (the most common combination)

### Phase 3: Synthesis Agent

**Type:** `LlmAgent` (Gemini 2.5 Pro — needs reasoning to merge and fact-check findings)
**Model:** `gemini-2.5-pro`
**Tools:** None — reasoning only
**Input:** All structured outputs from previous phases:
- TriageReport (metrics overview)
- TraceResult (where the request stopped)
- SubDiagnosis from each specialist (including `raw_evidence_context` — the exact log lines and config values that led to each finding, enabling the Synthesis Agent to perform a "second opinion" check and catch misinterpretations)
- SubDiagnosis from each specialist that ran

**System prompt (~400 tokens):**
```
You are synthesizing findings from multiple investigation phases into
a final diagnosis.

You will receive:
- A triage report (stack health overview)
- A trace result (where the request stopped)
- Specialist findings (what each domain expert found)

Produce a Diagnosis with: summary, timeline, root_cause,
affected_components, recommendation, confidence, explanation.

The explanation should be geared towards a network operations center (NOC) engineer — the engineer aims to understand what has happened and what action to take to resolve the issue.
Explain WHY the root cause caused the observed symptoms.
```

**Output:** `Diagnosis` (same schema as v1 — GUI `/ws/investigate` endpoint compatible)

---

## Tools: Reuse from v1.5

All 11 tools from `agentic_ops/tools.py` are reused as-is. The tool implementations are framework-agnostic async functions — they work from ADK agents the same way they work from Pydantic AI.

| Tool | Used by |
|---|---|
| `read_env_config` | Triage |
| `get_network_status` | Triage |
| `get_nf_metrics` | Triage |
| `query_prometheus` | Triage, Core Specialist |
| `read_container_logs` | Trace, IMS Specialist, Core Specialist |
| `search_logs` | Trace |
| `run_kamcmd` | IMS Specialist, Transport Specialist |
| `read_running_config` | IMS Specialist, Core Specialist, Transport Specialist |
| `check_process_listeners` | Transport Specialist |
| `query_subscriber` | Subscriber Data Specialist |
| `read_config` | (available but rarely needed — `read_running_config` preferred) |

---

## Directory Structure

```
operate/agentic_ops_v2/
├── plan.md                    # This document
├── __init__.py
├── orchestrator.py            # InvestigationDirector (SequentialAgent)
├── models.py                  # TriageReport, TraceResult, SubDiagnosis, Diagnosis
├── agents/
│   ├── __init__.py
│   ├── triage.py              # Phase 0: BaseAgent (deterministic metrics triage)
│   ├── tracer.py              # Phase 1: LlmAgent (end-to-end Call-ID trace)
│   ├── dispatcher.py          # Phase 2 router: LlmAgent (strategic specialist selection)
│   ├── ims_specialist.py      # Phase 2: LlmAgent (SIP/Diameter/Kamailio)
│   ├── transport_specialist.py # Phase 2: LlmAgent (UDP/TCP/listeners)
│   ├── core_specialist.py     # Phase 2: LlmAgent (5G core NFs)
│   ├── subscriber_data_specialist.py     # Phase 2: LlmAgent (subscriber provisioning)
│   └── synthesis.py           # Phase 3: LlmAgent (merge findings → Diagnosis)
├── tools.py                   # Thin wrappers: import from agentic_ops.tools
├── prompts/
│   ├── tracer.md              # Phase 1 system prompt
│   ├── dispatcher.md          # Phase 2 dispatch strategy prompt
│   ├── ims_specialist.md      # IMS specialist prompt
│   ├── transport_specialist.md # Transport specialist prompt
│   ├── core_specialist.md     # Core NF specialist prompt
│   ├── subscriber_data_specialist.md     # Subscriber data specialist prompt
│   └── synthesis.md           # Synthesis prompt
└── tests/
    ├── test_models.py         # Pydantic model tests
    ├── test_triage.py         # Phase 0 logic tests (deterministic, no LLM)
    ├── test_dispatcher.py     # Dispatch logic tests (deterministic)
    └── test_e2e.py            # Full pipeline against live stack
```

---

## Implementation Phases

### Phase A: Models + Triage + Trace (Week 1)

- [ ] `models.py` — TriageReport, TraceResult, SubDiagnosis (with `raw_evidence_context`), Diagnosis
- [ ] `tools.py` — import wrappers from `agentic_ops.tools`
- [ ] `agents/triage.py` — deterministic metrics collection + LLM oversight for gray failures
- [ ] `agents/tracer.py` — LlmAgent, Call-ID end-to-end trace
- [ ] `prompts/tracer.md` — focused system prompt (~500 tokens)
- [ ] Tests for triage logic (deterministic path + LLM oversight trigger) and models
- [ ] **Verify:** Triage produces correct TriageReport against live stack, including gray-failure detection

### Phase B: Specialists + Dispatcher (Week 2)

- [ ] `agents/dispatcher.py` — LlmAgent strategic routing (Gemini Flash, 1 turn)
- [ ] `prompts/dispatcher.md` — dispatch strategy prompt
- [ ] `agents/ims_specialist.py` — IMS/SIP investigation with emergency_notices broadcast
- [ ] `agents/transport_specialist.py` — UDP/TCP transport checks
- [ ] `agents/core_specialist.py` — 5G core investigation with emergency_notices broadcast
- [ ] `agents/subscriber_data_specialist.py` — subscriber provisioning checks
- [ ] `prompts/*.md` — specialist system prompts (each instructs on raw_evidence_context and disconfirm_check)
- [ ] Dynamic budget extension logic in orchestrator
- [ ] Tests for dispatch strategy (mock triage + trace inputs → expected specialist lists)

### Phase C: Orchestrator + Synthesis + Integration (Week 3)

- [ ] `agents/synthesis.py` — merge findings with fact-checking via raw_evidence_context
- [ ] `orchestrator.py` — InvestigationDirector SequentialAgent with dynamic budgets
- [ ] Emergency notices coordination between parallel specialists
- [ ] GUI integration — wire `/ws/investigate` to v2 orchestrator
- [ ] End-to-end test against the UE1→UE2 call failure scenario
- [ ] **Verify:** Correct diagnosis with high reliability. Token optimization deferred.

---

## Design Principles

1. **Metrics first, always.** Phase 0 triage is architectural, not advisory. Deterministic collection + LLM oversight for gray failures.

2. **Check the destination.** Phase 1 trace exists to enforce "did the request reach UE2?" — the lesson the v1 agent missed.

3. **Structured summaries with evidence context.** Each phase distills its output into structured models. But specialists also include `raw_evidence_context` (10-20 log lines / config blocks) so the Synthesis Agent can fact-check interpretations against source evidence.

4. **Specialists have clean context.** Each specialist starts with only the triage + trace summaries (~800 tokens) plus its own tool results. No accumulated log dumps from other phases.

5. **Reliability over token economy.** Optimize for correct diagnosis first. Tool budgets are soft guidance with dynamic extensions, not hard caps. Token optimization comes after the agent proves reliable.

6. **LLM-driven strategic dispatch.** The dispatcher uses Gemini Flash (1 turn) to decide which specialists to run, because telecom failures cross domain boundaries. Deterministic fallback if LLM response is unparseable.

7. **Hypothesis disconfirmation is structural.** SubDiagnosis requires a `disconfirm_check` field — each specialist must report what evidence would prove it wrong.

8. **Inter-specialist coordination via emergency notices.** Specialists running in parallel can broadcast high-confidence findings to `state["emergency_notices"]`, allowing other specialists to pivot if they hit an inconclusive state.

9. **Same tools, different prompts.** All 11 tools from v1.5 are reused. Specialists differ in which tools they carry and what their system prompt tells them to focus on.

10. **Same Diagnosis output.** v2 produces the same `Diagnosis` schema as v1. The GUI's `/ws/investigate` endpoint works without changes.

