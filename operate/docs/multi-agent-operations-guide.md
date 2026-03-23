# Operating the Multi-Agent Troubleshooting System

A hands-on guide to running, observing, and interpreting the v2 multi-agent investigation pipeline.

---

## Prerequisites

**Infrastructure:**
- Docker Compose stack running (Open5GS, Kamailio, PyHSS, UERANSIM)
- At least two UEs registered (e2e_ue1, e2e_ue2)
- Python venv at `operate/.venv` with ADK and dependencies installed

**GCP/Vertex AI:**
- Google Cloud project with Vertex AI API enabled
- Application Default Credentials configured (`gcloud auth application-default login`)
- Environment variable: `GOOGLE_GENAI_USE_VERTEXAI=TRUE`
- Region configured (e.g., `GOOGLE_CLOUD_LOCATION=northamerica-northeast1`)

**Verify readiness:**

```bash
cd operate

# Check the stack is up
.venv/bin/python -c "
import asyncio
from agentic_ops.tools import get_network_status
print(asyncio.run(get_network_status()))
"

# Check Vertex AI credentials
.venv/bin/python -c "
from google.genai import Client
c = Client(vertexai=True)
r = c.models.generate_content(model='gemini-2.5-flash', contents='Say hello')
print(r.text)
"
```

---

## Three Ways to Run an Investigation

### 1. GUI (Recommended for Live Observation)

Start the GUI server:

```bash
cd operate
.venv/bin/python gui/server.py
```

Open `http://localhost:8073` in your browser. Click **Investigate V2** (purple button). Type a question like:

> Why can't UE1 call UE2? Both are registered but calls fail immediately.

The modal shows three areas:
- **Progress log** (top) — live stream of phase transitions, tool calls, and agent output
- **Diagnosis** (middle) — the final structured diagnosis with timeline, root cause, and recommendation
- **Investigation Trace** (bottom) — per-agent metrics table with token breakdown

### 2. ADK Web UI (For Agent Development)

The ADK development UI provides session management and event inspection:

```bash
cd operate
.venv/bin/adk web agentic_ops_v2 --port 8075
```

Open `http://localhost:8075`. Select the `InvestigationDirector` agent. Type your question in the chat. The ADK UI shows the raw event stream from all sub-agents.

**Note:** The ADK UI doesn't show the per-agent token breakdown — that's a feature of our custom GUI. Use ADK UI for prompt development and debugging; use our GUI for operational observation.

### 3. Python API (For Scripting and Testing)

```python
import asyncio
from agentic_ops_v2.orchestrator import investigate

async def main():
    result = await investigate("UE1 can't call UE2. Both registered.")

    # The diagnosis
    print(result["diagnosis"])

    # Per-agent trace
    trace = result["investigation_trace"]
    for phase in trace["phases"]:
        print(f"{phase['agent_name']:30s} {phase['duration_ms']:6d}ms "
              f"{phase['tokens']['total']:8d} tokens "
              f"{len(phase['tool_calls']):2d} tools "
              f"{phase['llm_calls']:2d} LLM calls")

asyncio.run(main())
```

---

## Understanding the Live Progress Stream

When an investigation runs, the progress log shows events in real time. Here's how to read it:

```
▶ TriageAgent                              ← Phase started
▶ EndToEndTracer                           ← New phase
  [EndToEndTracer] 🔧 read_container_logs({"container":"e2e_ue1","tail":200})
    ↳ read_container_logs: [17:25:30.123] REGISTER sip:ims...
  [EndToEndTracer] 🔧 read_container_logs({"container":"e2e_ue2","tail":200})
    ↳ read_container_logs: [17:25:28.456] REGISTER sip:ims...
  [EndToEndTracer] 🔧 search_logs({"pattern":"KbLunzrYAuev"})
    ↳ search_logs: pcscf: [17:25:35] INVITE sip:0100002222...
  [EndToEndTracer] Call-ID KbLunzrYAuev found in pcscf, scscf, icscf...
▶ DispatchAgent                            ← Dispatch deciding specialists
  [DispatchAgent] Dispatching: ims, transport — trace shows delivery...
▶ IMSSpecialist                            ← Specialists run in parallel
▶ TransportSpecialist                      ← (both start ~simultaneously)
  [IMSSpecialist] 🔧 run_kamcmd({"container":"pcscf","command":"cdp.list_peers"})
  [TransportSpecialist] 🔧 read_running_config({"container":"pcscf","grep":"udp_mtu"})
    ↳ read_running_config: udp_mtu_try_proto = TCP
  [TransportSpecialist] 🔧 check_process_listeners({"container":"e2e_ue2"})
▶ SynthesisAgent                           ← Final synthesis
  [SynthesisAgent] The root cause is a transport protocol mismatch...
```

**What to watch for:**

- **Phase transitions (▶)** — Each cyan line marks a new agent starting. If there's a long gap between phases, the previous agent is still running LLM calls.
- **Tool calls (🔧)** — Purple lines show what each agent is investigating. Check if multiple agents are reading the same containers (redundant work).
- **Tool results (↳)** — Gray lines show what came back. Large results mean large context accumulation.
- **Agent reasoning** — Text output from agents shows their intermediate thinking.

---

## Reading the Investigation Trace

After the investigation completes, the trace panel appears below the diagnosis. Here's how to interpret it.

### The Summary Line

```
Investigation Trace   8 agents · 278,104 tokens · 47.4s
```

- **8 agents** — How many distinct agents executed (including Triage, which uses no LLM).
- **278,104 tokens** — Total across all agents. Compare against v1.5's ~159K baseline to judge overhead.
- **47.4s** — Wall-clock time from first event to last.

### The Agent Table

| Column | What It Means |
|---|---|
| **Agent** | Which agent ran. Click to expand details. |
| **Duration** | Wall-clock time this agent was active. For parallel agents, this includes LLM wait time. |
| **Tokens** | Total tokens consumed by this agent (prompt + completion + thinking). |
| **Tools** | Number of tool invocations. Zero for Triage (deterministic) and Synthesis (reasoning only). |
| **LLM** | Number of LLM round-trips. A specialist with 4+ LLM calls is doing iterative tool-use reasoning. |
| **Distribution** | Stacked bar showing prompt (blue) / completion (green) / thinking (orange) ratio. |

### What Healthy Looks Like

A well-behaved investigation typically shows:

```
TriageAgent              0.8s     1,200 tokens    0 tools   0 LLM
EndToEndTracer           8.0s    30,000 tokens    3 tools   2 LLM
DispatchAgent            1.0s     2,500 tokens    0 tools   1 LLM
TransportSpecialist      5.0s    25,000 tokens    2 tools   2 LLM
SynthesisAgent           6.0s    40,000 tokens    0 tools   1 LLM
─────────────────────────────────────────────────────────────
Total                   20.8s    98,700 tokens    5 tools   6 LLM
```

Characteristics of a healthy trace:
- **Triage is fast and cheap** — under 2 seconds, under 2K tokens (it's mostly deterministic).
- **Tracer uses 2-4 tool calls** — read both UE logs, search for Call-ID, maybe one refinement.
- **Only relevant specialists run** — if the failure is transport-related, you see Transport + IMS, not all four.
- **Synthesis is the biggest single consumer** — it receives all prior context. This is expected.
- **Total under 150K** — comparable to the v1.5 single-agent baseline.

### Red Flags in the Trace

**A specialist with 20K+ result_size on a tool call:**
```
IMSSpecialist
  read_running_config({"container":"scscf"}) → 22.1KB
```
That's an unfiltered config read dumping ~5,500 tokens into context. Fix: add a `grep` parameter.

**All four specialists running when only one or two are needed:**
```
IMSSpecialist           8.7s    52,400 tokens
TransportSpecialist     6.2s    38,100 tokens
CoreSpecialist          5.1s    28,300 tokens   ← investigating healthy core
SubscriberDataSpec      3.4s    18,600 tokens   ← subscribers are fine
```
The Dispatcher should have selected only IMS + Transport. Check the dispatch rationale.

**Synthesis consuming more than all specialists combined:**
```
SynthesisAgent          9.8s   191,200 tokens   0 tools   1 LLM
```
This means the accumulated context from all prior phases is massive. The fix is context distillation — summarizing prior phase outputs before passing them to synthesis.

**An agent making 6+ LLM calls:**
```
EndToEndTracer          25.0s   120,000 tokens   8 tools   6 LLM
```
The agent is in an iterative loop — reading logs, not finding what it needs, trying different searches. Check if the Call-ID extraction prompt is working correctly.

---

## The Investigation Pipeline, Phase by Phase

### Phase 0: Triage (TriageAgent)

**What it does:** Collects metrics from Prometheus, Kamailio (kamcmd), RTPEngine, PyHSS, and MongoDB. Classifies stack health deterministically. No LLM needed for common cases.

**What to look for in the trace:**
- Should consume near-zero tokens (it's deterministic Python, not LLM).
- Exception: if no anomalies are detected but the user reports a problem, LLM oversight kicks in (1 LLM call to gemini-2.5-flash).
- State keys written: `triage`, `env_config`.

**Triage output in the result dict:**
```json
{
  "stack_phase": "ready",
  "data_plane_status": "healthy",
  "ims_status": "healthy",
  "anomalies": [],
  "recommended_next_phase": "end_to_end_trace"
}
```

If `anomalies` is empty but the user sees a failure, the triage correctly identified this as a "gray failure" — everything looks healthy at the metrics level, but something is broken at the application level.

### Phase 1: Tracer (EndToEndTracer)

**What it does:** Extracts the SIP Call-ID from UE1's logs, searches for it across all containers, and identifies where the request stopped.

**What to look for in the trace:**
- Should read both UE logs (2 tool calls minimum).
- Should search for Call-ID across all containers (1-2 search_logs calls).
- The `failure_point` in the output is the most important finding — it tells every subsequent phase where to focus.

**Common issue:** If the Tracer extracts the Via branch parameter (z9hG4bK...) instead of the actual Call-ID header, it won't find matches in other containers. The tracer prompt explicitly warns about this, but check the output if the trace seems wrong.

### Phase 2: Dispatch (DispatchAgent)

**What it does:** Reads the triage + trace results and decides which specialists to invoke. Uses gemini-2.5-flash for a single JSON response.

**What to look for in the trace:**
- Should be fast (1 LLM call, ~1-3K tokens).
- Check `state_keys_written` includes `dispatch`.
- If it falls back to defaults (`["ims", "transport"]`), the LLM dispatch failed — check server logs.

### Phase 2: Specialists (Parallel)

**What they do:** Domain experts investigate their area using specialized tools and prompts.

| Specialist | Model | Tools | Focus |
|---|---|---|---|
| IMSSpecialist | gemini-2.5-pro | read_container_logs, run_kamcmd, read_running_config | SIP/Diameter, Kamailio state |
| TransportSpecialist | gemini-2.5-flash | read_running_config, check_process_listeners, run_kamcmd | TCP/UDP, MTU, listeners |
| CoreSpecialist | gemini-2.5-pro | read_container_logs, query_prometheus, read_running_config | AMF/SMF/UPF, GTP, PFCP |
| SubscriberDataSpecialist | gemini-2.5-flash | query_subscriber, query_prometheus | MongoDB, PyHSS provisioning |

**What to look for in the trace:**
- Specialists run in parallel — their start times overlap.
- Each writes to its own state key (`finding_ims`, `finding_transport`, etc.).
- Check tool result sizes — grep-filtered calls should be small (<1KB), unfiltered config reads will be large.
- The `output_summary` in the expanded detail shows the specialist's conclusion.

### Phase 3: Synthesis (SynthesisAgent)

**What it does:** Reads all prior phase outputs, fact-checks specialist findings against raw evidence, and produces the final Diagnosis.

**What to look for in the trace:**
- Uses gemini-2.5-pro with no tools (reasoning only).
- Should be 1 LLM call. If more, something unusual happened.
- This is typically the most expensive phase because it receives all prior context.
- State key written: `diagnosis`.

**The synthesis prompt instructs the agent to:**
1. Cross-check specialist conclusions against `raw_evidence_context`.
2. Weight findings with direct evidence over absence-of-evidence reasoning.
3. Give extra weight to Transport Specialist findings when the trace shows "sent but never received."
4. Look at evidence quality, not error codes — a 500 error may be a cascading symptom, not the root cause.

---

## Interpreting Token Costs

### Token Breakdown Per Phase

Expand any agent row in the trace panel to see the prompt/completion split:

```
Tokens: prompt 35,000 · completion 3,100
```

**High prompt, low completion** = the agent received a lot of context but didn't generate much output. This is the norm for specialists — they receive the conversation history plus their tool results, then produce a short finding.

**Roughly equal prompt and completion** = the agent is generating substantial output. This is typical for the Synthesis Agent writing a detailed explanation.

**Thinking tokens present** = Gemini's extended thinking mode is active. These tokens represent internal reasoning that doesn't appear in the output but contributes to better answers.

### Cost Estimation

Approximate Vertex AI pricing (as of early 2026):

| Model | Input (per 1M tokens) | Output (per 1M tokens) |
|---|---|---|
| gemini-2.5-flash | ~$0.15 | ~$0.60 |
| gemini-2.5-pro | ~$1.25 | ~$5.00 |

For a typical investigation at 150K tokens:
- ~120K input tokens across flash + pro ≈ $0.05-$0.15
- ~30K output tokens ≈ $0.02-$0.15
- **Total: ~$0.10-$0.30 per investigation**

For the 1.47M token run we observed:
- **Total: ~$1.00-$3.00 per investigation** — 10x more expensive

The trace panel lets you see which agents are driving cost so you can optimize the expensive ones.

---

## Troubleshooting the Troubleshooting System

### "The investigation hangs at a specific phase"

Check the server console logs. Look for:
```
Phase started: EndToEndTracer
```
followed by no further output. The agent is likely stuck in an LLM tool-use loop — making a call, not finding what it needs, trying again. The `llm_calls` count in the trace will be high when it finally completes.

**Fix:** Check if the target containers are running and producing logs. An agent that can't find any Call-ID in empty logs will loop.

### "The Dispatcher falls back to defaults"

The server logs will show:
```
Dispatch LLM failed (error), using defaults: ['ims', 'transport']
```

Common causes:
- Vertex AI authentication expired (`gcloud auth application-default login`)
- Quota exhausted (check GCP console)
- Gemini model returned non-JSON response (rare but possible)

### "Token count is much higher than expected"

Use the trace panel to identify the culprit:

1. **One specialist with huge tokens** → Check its tool calls. Is it reading unfiltered configs? Add grep filters.
2. **Synthesis has 2-3x more tokens than all specialists combined** → The accumulated context is too large. This is the core multi-agent overhead problem.
3. **All specialists have similar high token counts** → The Dispatcher is selecting too many specialists. Check the dispatch rationale.

### "The diagnosis is wrong but the trace shows correct findings"

This is the information-loss-at-boundaries problem. The specialist found the right evidence, but the Synthesis Agent interpreted it incorrectly.

**Check the expanded detail** for the relevant specialist — look at `output_summary`. Does it include the "fixability signal" (e.g., "this is a single config parameter on the P-CSCF, trivially changed")?

If the specialist's output is too terse, the synthesis agent won't have enough context to make the right recommendation. The fix is improving the specialist's prompt to include actionability in its findings.

### "Some agents don't appear in the trace"

The trace collector skips orchestration wrapper agents (`InvestigationDirector`, `SpecialistTeam`). If a real agent is missing, it produced zero events — which means:
- It was a `BaseAgent` that yielded no events (check its `_run_async_impl`).
- The LLM call failed silently.
- The Dispatcher didn't select it (check `state["dispatch"]["specialists"]`).

---

## Server Logs

The orchestrator produces structured logs showing the per-agent breakdown:

```
INFO  v2.orchestrator  Investigation trace: 8 agents, 278104 total tokens, 47400 ms
INFO  v2.orchestrator    TriageAgent                       800 ms     1204 tokens  0 tool calls  0 LLM calls
INFO  v2.orchestrator    EndToEndTracer                  12300 ms    45200 tokens  4 tool calls  3 LLM calls
INFO  v2.orchestrator    DispatchAgent                    1100 ms     3100 tokens  0 tool calls  1 LLM calls
INFO  v2.orchestrator    IMSSpecialist                    8700 ms    52400 tokens  3 tool calls  4 LLM calls
INFO  v2.orchestrator    TransportSpecialist              6200 ms    38100 tokens  2 tool calls  3 LLM calls
INFO  v2.orchestrator    CoreSpecialist                   5100 ms    28300 tokens  2 tool calls  2 LLM calls
INFO  v2.orchestrator    SubscriberDataSpecialist         3400 ms    18600 tokens  1 tool calls  1 LLM calls
INFO  v2.orchestrator    SynthesisAgent                   9800 ms    91200 tokens  0 tool calls  1 LLM calls
```

These logs are always produced regardless of whether the GUI is connected. Use them for post-hoc analysis and automated monitoring.

---

## Key Metrics to Track Across Runs

| Metric | Healthy Range | Concerning | What It Means |
|---|---|---|---|
| Total tokens | 80K-200K | >500K | Multi-agent overhead is dominating |
| Triage tokens | 0-2K | >10K | LLM oversight is firing unnecessarily |
| Tracer tool calls | 2-4 | >6 | Call-ID extraction failing, agent searching |
| Specialist count | 1-2 | 4 | Dispatcher over-selecting |
| Synthesis tokens | 30-50% of total | >60% | Context accumulation problem |
| Total duration | 20-60s | >120s | LLM latency or tool timeouts |
| Largest tool result | <5KB | >20KB | Unfiltered log/config dump |

---

## Quick Reference

**Start the GUI:**
```bash
cd operate && .venv/bin/python gui/server.py
```

**Start the ADK dev UI:**
```bash
cd operate && .venv/bin/adk web agentic_ops_v2 --port 8075
```

**Run investigation from command line:**
```bash
cd operate && .venv/bin/python -c "
import asyncio
from agentic_ops_v2.orchestrator import investigate
r = asyncio.run(investigate('Why can\'t UE1 call UE2?'))
t = r['investigation_trace']
for p in t['phases']:
    print(f\"{p['agent_name']:30s} {p['tokens']['total']:8d} tokens\")
"
```

**Run tests:**
```bash
cd operate && .venv/bin/python -m pytest agentic_ops_v2/tests/ -v
```

**Check which agents are registered for ADK web:**
```bash
cd operate && .venv/bin/python -c "
from agentic_ops_v2.agent import root_agent
print(root_agent.name, ':', [a.name for a in root_agent.sub_agents])
"
```
