# Multi-Agent Observability Architecture

How we built deep visibility into a 5-phase AI troubleshooting pipeline so we could understand — and fix — its behavior.

---

## Why This Exists

We built a multi-agent system to troubleshoot a containerized 5G SA + IMS network. Five phases, eight agents, four running in parallel. When we tested it against a real failure, it consumed 1.47 million tokens — 9.3x more than the single-agent system it replaced — and gave a wrong recommendation despite correctly identifying the root cause.

The problem? We had no visibility into what was happening inside the pipeline. All we got was a single number: `total_tokens = 1,478,204`. We couldn't tell which agent was the token hog, which tool calls were redundant, or where the information loss occurred that led to the wrong fix recommendation.

This observability system was built to answer three questions:
1. **Which agent consumed how many tokens?** (Cost attribution)
2. **What did each agent actually do?** (Tool calls, state changes, outputs)
3. **How did context flow between phases?** (The causal chain from evidence to conclusion)

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Investigation Director                          │
│                     (ADK SequentialAgent)                            │
│                                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────┐ │
│  │ Phase 0  │→ │ Phase 1  │→ │ Phase 2  │→ │ Phase 2  │→ │Phase │ │
│  │ Triage   │  │ Tracer   │  │ Dispatch │  │Specialists│  │  3   │ │
│  │(no LLM)  │  │ (Flash)  │  │ (Flash)  │  │(Parallel) │  │Synth │ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────┘ │
│       │              │             │              │            │     │
│       ▼              ▼             ▼              ▼            ▼     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    Event Stream                               │   │
│  │  Each event carries: author, usage_metadata, content,         │   │
│  │  actions.state_delta, timestamp                               │   │
│  └──────────────────────┬───────────────────────────────────────┘   │
└─────────────────────────┼───────────────────────────────────────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │   Trace Collector     │
              │   (orchestrator.py)   │
              │                       │
              │  Per-agent:           │
              │  - TokenBreakdown     │
              │  - ToolCallTrace[]    │
              │  - State keys written │
              │  - Duration           │
              │  - LLM call count     │
              │  - Output summary     │
              └───────────┬───────────┘
                          │
                ┌─────────┴─────────┐
                ▼                   ▼
        ┌──────────────┐   ┌──────────────┐
        │  WebSocket    │   │  Result Dict │
        │  Live Stream  │   │  (JSON)      │
        │  → GUI        │   │  → Logs      │
        └──────────────┘   └──────────────┘
```

---

## Data Model

The observability system is built on four Pydantic models that compose into a complete investigation trace. All defined in `agentic_ops_v2/models.py`.

### TokenBreakdown

The atomic unit of token accounting. Splits a token count into the categories that matter for cost and optimization.

```python
class TokenBreakdown(BaseModel):
    prompt: int = 0       # Input tokens (context sent to the LLM)
    completion: int = 0   # Output tokens (LLM response)
    thinking: int = 0     # Reasoning tokens (Gemini extended thinking)
    total: int = 0        # Sum of all token types
```

**Why the split matters:** A phase with high prompt tokens and low completion tokens is sending too much context. A phase with high thinking tokens is doing extended reasoning. The ratio tells you where to optimize — you can't shrink what you can't see.

### ToolCallTrace

Records a single tool invocation by an agent — what was called, with what arguments, and how much data came back.

```python
class ToolCallTrace(BaseModel):
    name: str          # "read_container_logs", "search_logs", etc.
    args: str = ""     # Stringified arguments (truncated to 200 chars)
    result_size: int = 0  # Character count of the return value
    timestamp: float = 0.0
```

**Why result_size matters:** A `read_container_logs` call returning 50KB of raw logs is the single biggest contributor to context bloat. Tracking result sizes reveals which tool calls are the token sinks.

### PhaseTrace

The per-agent observability record. One PhaseTrace per agent that executed during the investigation.

```python
class PhaseTrace(BaseModel):
    agent_name: str             # "TriageAgent", "IMSSpecialist", etc.
    started_at: float = 0.0
    finished_at: float = 0.0
    duration_ms: int = 0        # Wall-clock duration
    tokens: TokenBreakdown      # Full token accounting
    tool_calls: list[ToolCallTrace]  # Every tool invocation
    llm_calls: int = 0          # Number of LLM round-trips
    output_summary: str = ""    # First 500 chars of agent output
    state_keys_written: list[str]  # Session state keys modified
```

**Key insight:** `llm_calls` tells you how many times the agent went back and forth with the LLM. A specialist making 8 LLM calls is doing iterative tool-use reasoning; one making 1 call either got it right immediately or gave up.

### InvestigationTrace

The top-level container that ties everything together.

```python
class InvestigationTrace(BaseModel):
    question: str = ""           # The original troubleshooting question
    started_at: float = 0.0
    finished_at: float = 0.0
    duration_ms: int = 0
    total_tokens: TokenBreakdown # Aggregate across all phases
    phases: list[PhaseTrace]     # Ordered agent executions
    invocation_chain: list[str]  # Agent names in execution order
```

### Relationships

```
InvestigationTrace
├── total_tokens: TokenBreakdown (aggregate)
├── invocation_chain: ["TriageAgent", "EndToEndTracer", ...]
└── phases: list[PhaseTrace]
    ├── PhaseTrace (TriageAgent)
    │   ├── tokens: TokenBreakdown
    │   ├── tool_calls: []          (no tools — deterministic)
    │   ├── llm_calls: 0            (or 1 if LLM oversight triggered)
    │   └── state_keys_written: ["triage", "env_config"]
    ├── PhaseTrace (EndToEndTracer)
    │   ├── tokens: TokenBreakdown
    │   ├── tool_calls: [read_container_logs×2, search_logs×1]
    │   └── state_keys_written: ["trace"]
    ├── PhaseTrace (DispatchAgent)
    │   ├── tokens: TokenBreakdown
    │   └── state_keys_written: ["dispatch"]
    ├── PhaseTrace (IMSSpecialist)       ┐
    │   ├── tool_calls: [run_kamcmd, ...] │ These run
    │   └── state_keys_written: [...]     │ in parallel
    ├── PhaseTrace (TransportSpecialist)  │
    │   └── ...                           ┘
    └── PhaseTrace (SynthesisAgent)
        ├── tokens: TokenBreakdown
        ├── tool_calls: []          (no tools — reasoning only)
        └── state_keys_written: ["diagnosis"]
```

---

## How Events Flow Through the System

### ADK Event Stream

Google ADK's `SequentialAgent` yields `Event` objects as sub-agents execute. Each event carries rich metadata that we previously discarded:

| Event Field | What It Contains | What We Extract |
|---|---|---|
| `event.author` | Sub-agent name (e.g., "IMSSpecialist") | Phase attribution |
| `event.usage_metadata.prompt_token_count` | Input tokens for this LLM call | Token accounting |
| `event.usage_metadata.candidates_token_count` | Output tokens | Token accounting |
| `event.usage_metadata.thoughts_token_count` | Reasoning tokens | Token accounting |
| `event.content.parts[].function_call` | Tool name + args | Tool call tracking |
| `event.content.parts[].function_response` | Tool return value | Result size tracking |
| `event.content.parts[].text` | Agent text output | Output summary |
| `event.actions.state_delta` | State keys modified | State tracking |
| `event.timestamp` | When the event was emitted | Duration calculation |

### Collection Logic

The trace collector in `orchestrator.py` processes every event in the stream:

```
for each event:
  1. Skip orchestration wrappers (InvestigationDirector, SpecialistTeam, user)
  2. If new author → create PhaseTrace, record start time, emit phase_start
  3. If usage_metadata → accumulate prompt/completion/thinking tokens
  4. If function_call → record ToolCallTrace
  5. If function_response → attach result_size to matching ToolCallTrace
  6. If text → capture output_summary (first 500 chars)
  7. If state_delta → record which state keys were written
```

### Phase Timing

ADK doesn't emit explicit "phase started" / "phase ended" events. We infer timing from event timestamps:

- **Phase N starts** when we see the first event from that agent.
- **Phase N ends** when Phase N+1 starts (the first event from the next agent).
- **The last phase ends** at the overall run completion time.

This is approximate but sufficient — the wall-clock duration of each phase is dominated by LLM latency and tool execution, not event processing.

### Parallel Agent Handling

When the `SpecialistTeam` (ParallelAgent) runs, events from all four specialists are interleaved in the stream. The collector handles this correctly because it keys on `event.author` — each specialist's events carry its own name regardless of interleaving order.

For parallel agents, the "started_at" and "finished_at" timestamps overlap. The duration reflects wall-clock time for that agent, which may include time waiting for the LLM while other agents are also running.

---

## Live Streaming Architecture

The investigation trace isn't just collected at the end — it's streamed live to the GUI as events happen.

### Callback Mechanism

`investigate()` accepts an optional `on_event` async callback:

```python
async def investigate(question: str, on_event=None) -> dict:
```

The WebSocket handler in `server.py` provides a callback that forwards events directly:

```python
async def on_event(evt: dict) -> None:
    await _ws_send(ws, evt)
```

### Event Types Streamed

| WebSocket Message Type | When Emitted | What It Contains |
|---|---|---|
| `phase_start` | First event from a new agent | `agent` name |
| `tool_call` | Agent invokes a tool | `agent`, `name`, `args` |
| `tool_result` | Tool returns | `agent`, `name`, `preview` (200 chars) |
| `text` | Agent produces text output | `agent`, `content` (300 chars) |
| `diagnosis` | Synthesis complete | Full Diagnosis object |
| `investigation_trace` | Run complete | Full InvestigationTrace object |
| `usage` | Run complete | `total_tokens` (backward compat) |

### Data Flow

```
ADK Event Stream
      │
      ▼
  Trace Collector (orchestrator.py)
      │
      ├──→ on_event callback ──→ WebSocket ──→ GUI (live progress)
      │                                         - Phase indicators
      │                                         - Tool call log
      │                                         - Agent output
      │
      └──→ Result dict ──→ WebSocket ──→ GUI (trace panel)
           - InvestigationTrace          - Per-agent table
           - Diagnosis                   - Token bar charts
           - Findings                    - Expandable details
```

---

## GUI Trace Panel

The investigation trace renders as a collapsible panel below the diagnosis in the V2 investigation modal.

### Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ Investigation Trace   8 agents · 278,104 tokens · 47.4s  ▼     │
├─────────────────────────────────────────────────────────────────┤
│ Agent                Duration  Tokens    Tools LLM  Distribution│
│─────────────────────────────────────────────────────────────────│
│ TriageAgent           0.8s     1,204       0    0  ██           │
│ EndToEndTracer       12.3s    45,200       4    3  ████████     │
│ DispatchAgent         1.1s     3,100       0    1  █            │
│ IMSSpecialist         8.7s    52,400       3    4  █████████    │
│ TransportSpecialist   6.2s    38,100       2    3  ███████      │
│ CoreSpecialist        5.1s    28,300       2    2  █████        │
│ SubscriberDataSpec    3.4s    18,600       1    1  ███          │
│ SynthesisAgent        9.8s    91,200       0    1  ████████████ │
│─────────────────────────────────────────────────────────────────│
│ ■ prompt  ■ completion  ■ thinking                              │
└─────────────────────────────────────────────────────────────────┘
```

### Expandable Row Detail

Clicking any agent row reveals:

```
┌─────────────────────────────────────────────────────────────────┐
│ Tokens: prompt 35,000 · completion 3,100                        │
│ State: finding_transport                                        │
│ Tool calls:                                                     │
│   read_running_config({"container":"pcscf","grep":"udp_mtu"})   │
│     → 0.2KB                                                    │
│   check_process_listeners({"container":"e2e_ue2"})              │
│     → 0.2KB                                                    │
│ Output: Transport mismatch: P-CSCF sends TCP because            │
│   udp_mtu_try_proto=TCP but UE2 only listens on UDP...          │
└─────────────────────────────────────────────────────────────────┘
```

### Token Distribution Bar

Each row has a stacked bar chart showing the prompt/completion/thinking ratio:

- **Blue (prompt):** Context sent to the LLM — the biggest cost driver. High prompt tokens relative to completion means the agent is receiving too much context.
- **Green (completion):** LLM response tokens. Proportional to how much the agent wrote.
- **Orange (thinking):** Reasoning tokens from Gemini's extended thinking mode. These indicate complex reasoning steps.

The bar width is scaled relative to the agent with the most tokens, so you can visually spot the token hog.

---

## What We Couldn't See Before vs. Now

### Before (single total_tokens counter)

```
Investigation complete · 1,478,204 tokens
```

That's it. One number. Is the Synthesis Agent consuming most of the tokens because it receives the entire conversation history? Is one specialist making redundant tool calls? Is the Tracer reading massive log files unfiltered? No way to tell.

### After (per-agent investigation trace)

```
TriageAgent              800ms      1,204 tokens    0 tools   0 LLM
EndToEndTracer         12,300ms    45,200 tokens    4 tools   3 LLM
  read_container_logs(e2e_ue1)           → 12.3KB
  read_container_logs(e2e_ue2)           → 8.1KB
  search_logs(Call-ID across all)        → 15.7KB
  search_logs(Call-ID refined)           → 4.2KB
DispatchAgent           1,100ms     3,100 tokens    0 tools   1 LLM
IMSSpecialist           8,700ms    52,400 tokens    3 tools   4 LLM
  read_container_logs(pcscf, grep=...)   → 6.8KB
  run_kamcmd(pcscf, cdp.list_peers)      → 0.3KB
  read_running_config(scscf)             → 22.1KB  ← TOKEN HOG
TransportSpecialist     6,200ms    38,100 tokens    2 tools   3 LLM
  read_running_config(pcscf, grep=udp)   → 0.2KB   ← efficient grep
  check_process_listeners(e2e_ue2)       → 0.2KB
CoreSpecialist          5,100ms    28,300 tokens    2 tools   2 LLM
SubscriberDataSpec      3,400ms    18,600 tokens    1 tools   1 LLM
SynthesisAgent          9,800ms    91,200 tokens    0 tools   1 LLM
────────────────────────────────────────────────────────────────
                       47,400ms   278,104 tokens   12 tools  15 LLM
```

Now we can see:
- The **IMSSpecialist** read an unfiltered S-CSCF config (22.1KB) — that's ~5,500 tokens of unnecessary context.
- The **SynthesisAgent** consumed 91K tokens — it receives the full accumulated context from all prior phases.
- The **TransportSpecialist** used grep filtering and kept its tool results under 0.5KB — that's the efficient pattern.
- **CoreSpecialist** and **SubscriberDataSpecialist** consumed 47K tokens combined investigating healthy subsystems.

---

## Design Decisions

### Why Per-Agent, Not Per-LLM-Call

We track at the agent level, not the individual LLM call level. Each agent may make multiple LLM calls (tool-use loops), and we aggregate those into a single PhaseTrace.

**Rationale:** The actionable insight is "this agent is expensive" not "this specific LLM call within this agent was expensive." You optimize at the agent level — better prompts, grep filters on tools, fewer tool-use rounds.

We do track `llm_calls` count per agent so you can see if an agent is doing excessive back-and-forth.

### Why event.author, Not Callbacks

ADK offers both `before_agent_callback`/`after_agent_callback` hooks and the event stream with `event.author`. We chose the event stream because:

1. **Callbacks fire at agent boundaries** — you get start/end but not the per-tool-call granularity.
2. **Events carry usage_metadata** — the token counts are on the events, not available in callbacks.
3. **Single processing loop** — one `async for event` loop handles everything instead of callbacks plus event processing.

### Why Inferred Timing

ADK doesn't provide explicit "agent started" / "agent finished" signals. We infer timing from event timestamps (phase N ends when phase N+1 begins). This means:

- For sequential phases, timing is accurate (each phase produces at least one event).
- For parallel phases, timing shows wall-clock duration including LLM wait time.
- If an agent produces zero events (edge case), it won't appear in the trace.

An alternative would be `before_agent_callback` + `after_agent_callback` to get precise boundaries, but that requires wiring callbacks onto every agent at construction time. The event-stream approach is simpler and handles new agents without code changes.

### Why Stream + Batch

We both stream events live (for the GUI progress view) and collect the full trace (for the post-investigation table). This dual approach serves different needs:

- **Live stream:** "What is the system doing right now?" — shows phase transitions and tool calls as they happen.
- **Batch trace:** "What did the system do?" — enables comparison across runs, identifies patterns, supports the cost optimization loop.

---

## Integration Points

### Files Modified

| File | Change |
|---|---|
| `agentic_ops_v2/models.py` | Added TokenBreakdown, ToolCallTrace, PhaseTrace, InvestigationTrace |
| `agentic_ops_v2/orchestrator.py` | Rewrote `investigate()` with per-agent trace collection and `on_event` callback |
| `gui/server.py` | Rewrote `handle_investigate_v2` to stream live events and send trace |
| `gui/index.html` | Added trace panel rendering, phase_start handling, expandable rows |

### Backward Compatibility

The `usage` WebSocket message (with `total_tokens`) is still sent after the trace for clients that only understand the old protocol. The `investigation_trace` message is new and ignored by older clients.

The `investigate()` function's return dict still contains `total_tokens` as a top-level integer alongside the new `investigation_trace` dict.

---

## Future Work

**Context distillation metrics.** The trace shows us *how many* tokens each phase consumed but not *why*. A future enhancement would track how much of each phase's prompt tokens came from prior phase context vs. tool results vs. the system prompt. This would directly inform the context summarization work needed to reduce the 9.3x token overhead.

**Trace persistence.** Currently, the trace exists only in the WebSocket session and server logs. Saving traces as JSON files alongside investigation results would enable cross-run comparison and regression detection.

**OpenTelemetry export.** ADK has built-in OTel support (`google.adk.telemetry`). Exporting spans to Cloud Trace or a local collector like Jaeger would give distributed tracing visualization without custom GUI work.
