# Plan: Context Isolation for Multi-Agent Pipeline (v3)

## Context

The v2 multi-agent troubleshooting system consumes ~985K tokens per investigation (6.2x worse than v1.5's 159K) and produces wrong diagnoses. Root cause: ADK's SequentialAgent forwards the full conversation history (every LLM turn, tool call, tool response) to every subsequent agent. By the time specialists run, each inherits 125-252K tokens of accumulated noise, causing attention dilution and hallucinations.

The user's analysis (`MAS_PERFORMANCE_ANALYSIS.md`) identifies three fixes: context isolation, data distillation, and dynamic parallelism. ADK natively supports running agents in separate sessions with shared structured state — `create_session(state={...})` gives a blank conversation history with pre-populated state, and LlmAgent instructions resolve `{placeholder}` variables from session state.

**This is implemented as a new v3 system (`operate/agentic_ops_v3/`) — the existing v2 code is left untouched.** v3 reuses v2's tools, models, and prompts (with modifications) but replaces the orchestrator architecture entirely.

---

## Implementation Strategy

Step 3 (session-per-phase orchestration) is a **custom workflow** — ADK has no built-in support for running pipeline phases in isolated sessions. ADK's `SequentialAgent` and `ParallelAgent` are the native orchestration primitives, but they share one session with one conversation history. There is no "run this agent in an isolated session and pass only structured state forward."

What ADK *does* provide that we compose into the custom workflow:

| ADK Building Block | What It Does | How We Use It |
|---|---|---|
| `InMemorySessionService.create_session(state={...})` | Creates a fresh session with pre-populated state and blank conversation history | One new session per phase, seeded with prior phase outputs |
| `Runner` | Runs any `BaseAgent` against any session | One Runner per phase, scoped to that phase's agent |
| `{placeholder}` in LlmAgent `instruction` | Resolves variables from `session.state`, NOT from conversation history | Specialists see triage/trace data via `{triage}` and `{trace}` without inheriting raw tool outputs |
| `output_key` on LlmAgent | Saves the agent's final output text to `session.state[key]` | Each phase's output automatically lands in state for the next phase to consume |

The `_run_phase()` helper is ~40 lines of custom code that composes these primitives. It creates a Runner + Session, runs the agent, collects trace data, and returns the updated state dict. The `investigate()` function calls `_run_phase()` sequentially, passing the state forward — effectively a hand-rolled SequentialAgent with session boundaries between each step.

The existing `create_investigation_director()` (which returns a standard ADK SequentialAgent) is preserved unchanged for ADK web UI compatibility. The two code paths coexist: `adk web` uses the native SequentialAgent (single session, full history accumulation), while `investigate()` uses the custom session-per-phase approach (context isolated).

---

## Implementation Steps

### Step 1: Tool Truncation (`tools.py`)

Add `_truncate_output()` helper and apply it to the two biggest offenders:

- `search_logs`: cap at 10KB (currently returns 68KB)
- `read_container_logs` without grep: cap at 10KB (currently returns 20KB)

Truncation keeps the **tail** (most recent lines) and discards from the **beginning** (oldest lines), cutting at the nearest line boundary. Docker logs are chronological — the most recent entries at the bottom are the ones relevant to the failure. A prefix warning is prepended: `... truncated (N older lines omitted). Use grep to narrow your search.`

**File:** `agentic_ops_v2/tools.py`

### Step 2: Prompt Templates — Add State Placeholders

ADK resolves `{variable_name}` from `session.state` in LlmAgent instructions. `{name?}` is optional (empty string if missing). Update all prompts to receive prior phase data via placeholders instead of conversation history.

**`prompts/tracer.md`** — Add at the top:
```
## Triage findings (from previous phase)
{triage}
```

**`prompts/dispatcher.md`** — Add `{triage}` and `{trace}` sections. Add structured output format:
```
DISPATCH: ims, transport
```

**`prompts/ims_specialist.md`**, **`transport_specialist.md`**, **`core_specialist.md`**, **`subscriber_data_specialist.md`** — Each gets:
```
## Context from prior phases
### Triage Report
{triage}
### End-to-End Trace
{trace}
```

**`prompts/synthesis.md`** — Gets all placeholders:
```
{triage}, {trace}, {dispatch}, {finding_ims?}, {finding_transport?}, {finding_core?}, {finding_subscriber_data?}
```
The `?` suffix makes specialist findings optional (not all run every time).

### Step 3: Session-Per-Phase Orchestrator (`orchestrator.py`)

Replace the single SequentialAgent + single Session with explicit phase-by-phase execution. Each phase gets its own session (fresh conversation history) seeded with structured state from prior phases.

**New `_run_phase()` helper:**
- Creates a Runner + Session for one agent
- Seeds the session with accumulated state dict
- Runs the agent, collects trace (tokens, tool calls, timing)
- Streams events via `on_event` callback
- Returns updated state + PhaseTrace

**Rewritten `investigate()`:**
```
state = {user_question}
state, trace = _run_phase(triage_agent, state, ...)      # Session A
state, trace = _run_phase(tracer_agent, state, ...)       # Session B (no Triage history)
state, trace = _run_phase(dispatch_agent, state, ...)     # Session C
specialists = _parse_dispatch_output(state["dispatch"])   # Dynamic selection
state, trace = _run_phase(ParallelAgent(specialists), ...) # Session D
state, trace = _run_phase(synthesis_agent, state, ...)    # Session E
```

Each session inherits structured state (the `output_key` text from prior agents) but NOT conversation history (tool calls, tool responses, LLM reasoning turns).

**`_parse_dispatch_output()`** — Parse dispatcher's text output for specialist names:
1. Primary: look for `DISPATCH: ims, transport` structured line
2. Fallback: keyword scan for specialist names in the text
3. Ultimate fallback: `["ims", "transport"]`

**Preserve `create_investigation_director()`** — Keep the existing SequentialAgent factory unchanged for ADK web UI compatibility (`agent.py` imports it). The two paths coexist: `adk web` uses SequentialAgent (single session), `investigate()` uses session-per-phase (context isolated).

### Step 4: Tests

- **`tests/test_tools.py`** (new) — `_truncate_output()` helper: under limit unchanged, over limit truncates at line boundary, empty input.
- **`tests/test_dispatcher.py`** — Update: verify `{triage}` and `{trace}` placeholders in instruction, verify `DISPATCH:` format instruction present.
- **`tests/test_orchestrator.py`** (new) — `_parse_dispatch_output()`: structured format, keyword fallback, garbage input → default. Verify `create_investigation_director()` still returns valid SequentialAgent.
- **`tests/test_triage.py`** — No changes needed.

---

## Files to Modify

| File | Change |
|---|---|
| `agentic_ops_v2/tools.py` | Add `_truncate_output()`, apply to `search_logs` and `read_container_logs` |
| `agentic_ops_v2/orchestrator.py` | Add `_run_phase()`, `_parse_dispatch_output()`, rewrite `investigate()` |
| `agentic_ops_v2/prompts/tracer.md` | Add `{triage}` section |
| `agentic_ops_v2/prompts/dispatcher.md` | Add `{triage}`, `{trace}` sections + `DISPATCH:` output format |
| `agentic_ops_v2/prompts/ims_specialist.md` | Add `{triage}`, `{trace}` sections |
| `agentic_ops_v2/prompts/transport_specialist.md` | Add `{triage}`, `{trace}` sections |
| `agentic_ops_v2/prompts/core_specialist.md` | Add `{triage}`, `{trace}` sections |
| `agentic_ops_v2/prompts/subscriber_data_specialist.md` | Add `{triage}`, `{trace}` sections |
| `agentic_ops_v2/prompts/synthesis.md` | Add all finding placeholders |
| `agentic_ops_v2/tests/test_tools.py` | New — truncation tests |
| `agentic_ops_v2/tests/test_orchestrator.py` | New — dispatch parsing + director compat tests |
| `agentic_ops_v2/tests/test_dispatcher.py` | Update — placeholder and format tests |

---

## Expected Impact

| Metric | Before | After (estimated) | Reduction |
|---|---|---|---|
| Total tokens | 985K | ~100K | ~90% |
| Specialist prompt tokens | 125-252K each | ~5-10K each | ~95% |
| Specialists invoked | 4 (always) | 2 (dynamic) | 50% |
| search_logs result size | 68KB | 10KB | 85% |
| Diagnosis accuracy | Wrong (3/3 runs) | Should improve (less noise = less hallucination) |

The 90% token reduction comes from three multiplicative effects:
1. **No conversation history inheritance** — eliminates cumulative context growth
2. **Tool output truncation** — search_logs 68KB → 10KB
3. **Dynamic parallelism** — 4 specialists → 2 (only those the dispatcher selects)

---

## Verification

1. `cd operate && .venv/bin/python -m pytest agentic_ops_v2/tests/ -v` — All tests pass
2. Run investigation with the TCP mismatch fault active:
   ```
   GOOGLE_CLOUD_PROJECT=eod-sbox-entitlement-server \
   GOOGLE_CLOUD_LOCATION=northamerica-northeast1 \
   GOOGLE_GENAI_USE_VERTEXAI=TRUE \
   .venv/bin/python -c "
   import asyncio; from agentic_ops_v2.orchestrator import investigate
   r = asyncio.run(investigate('UE1 cannot call UE2'))
   t = r['investigation_trace']
   for p in t['phases']:
       print(f\"{p['agent_name']:<30s} {p['tokens']['total']:>10,} tokens\")
   "
   ```
3. Check auto-persisted JSON in `agentic_ops_v2/docs/agent_logs/`
4. Verify total tokens < 150K (target: ~100K)
5. Verify Transport Specialist is dispatched and its finding reaches Synthesis
6. Start GUI server, run from GUI, verify trace panel renders correctly
