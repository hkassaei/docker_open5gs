# When More Agents Make Things Worse: Lessons from Debugging a 5G Network with AI

*We built a multi-agent AI system to troubleshoot a 5G core network. It was slower, more expensive, and gave worse advice than the single-agent version it was supposed to replace. Here's what went wrong — and what it taught us about when to decompose a problem across agents.*

---

## The Setup

We operate a containerized 5G SA + IMS stack — Open5GS for the core, Kamailio for the IMS (P-CSCF, I-CSCF, S-CSCF), PyHSS for subscriber data, and UERANSIM for simulated UEs. About 20 containers, three network layers, two authentication domains, and a SIP call path that bounces through six network functions before reaching the destination.

When something breaks — and things break often — a human operator has to dig through logs across a dozen containers, correlate SIP Call-IDs, check Prometheus metrics, inspect Kamailio internal state, and reason about transport protocols. A typical investigation takes 30-60 minutes.

We wanted to automate this with an AI agent.

## Version 1.5: The Single Agent That Worked

Our first working system was straightforward: one Pydantic AI agent, 11 tools, a carefully written system prompt, and Gemini 2.5 Pro as the backbone. The prompt encoded a 7-step investigation methodology:

1. **Discover the environment and check metrics FIRST** — "The metrics snapshot is your radiograph."
2. **Check both ends** of the affected flow — caller AND callee.
3. **Extract the Call-ID and trace it end-to-end** across all containers.
4. **Trace upstream from the failure point.**
5. **Check infrastructure state** — running configs, process listeners, Kamailio internals.
6. **Verify subscriber provisioning.**
7. **Disconfirm your hypothesis** before concluding.

The prompt also included a table of known failure patterns — things like "SIP INVITE not delivered" with the exact symptoms, root cause, and where to look. This was hard-won operational knowledge baked into the agent's instructions.

We tested it against a real production failure: UE1 tries to call UE2, the call fails with a `500 Server error` at the I-CSCF. The root cause? A Kamailio setting called `udp_mtu_try_proto = TCP` on the P-CSCF. When the SIP INVITE message (with SDP body, ~1,676 bytes) exceeded the 1,300-byte UDP MTU threshold, Kamailio silently switched to TCP delivery. But the destination UE only listened on UDP. The INVITE was never delivered. The timeout cascaded backward through four hops:

```
P-CSCF sends INVITE via TCP
  → UE2 doesn't receive (no TCP listener)
    → P-CSCF times out
      → S-CSCF gets 408
        → I-CSCF failure_route: "select next S-CSCF" (only one exists → fails)
          → I-CSCF returns 500 to UE1
```

The 500 error the operator sees is **four hops away** from the actual failure point. This is the kind of problem that eats hours of human debugging time.

The v1.5 agent nailed it. Seven tool calls. 159K tokens. Correct root cause (`udp_mtu_try_proto = TCP`), correct recommendation ("change it to UDP on the P-CSCF"), correct causal chain. **Score: 90%.**

## "We Should Build a Multi-Agent System"

The single agent worked, but we saw limitations. What about problems where one context window isn't enough? What about parallelizing independent investigations? What about enforcing investigation discipline through architecture rather than prompting?

We had good reasons to try multi-agent. Our earlier design reflections had identified real problems:

> A single agent follows the most "interesting" thread, not the most diagnostic one. SIP CSeq timing analysis is fascinating. GTP packet counters are boring. The manual investigation spent 30 minutes on the fascinating one. The boring one had the answer.

So we built v2: a 5-phase pipeline using Google's Agent Development Kit (ADK), with specialized agents for each investigation phase:

```
                    ┌─────────────────┐
                    │  Investigation  │
                    │    Director     │
                    │ (SequentialAgent)│
                    └────────┬────────┘
                             │
       ┌─────────┬───────────┼───────────┬──────────┐
       │         │           │           │          │
   Phase 0   Phase 1    Phase 2     Phase 2     Phase 3
   Triage    Tracer     Dispatch    Specialists  Synthesis
   (no LLM)  (Flash)    (Flash)    (Parallel)    (Pro)
                                    ├─ IMS
                                    ├─ Transport
                                    ├─ Core
                                    └─ Subscriber
```

- **Triage Agent** (deterministic): Collects metrics, classifies health, flags anomalies. No LLM needed for the common cases.
- **Tracer** (Gemini Flash): Extracts the Call-ID, searches all containers, identifies where the request stopped.
- **Dispatcher** (Gemini Flash): Reads triage + trace results, decides which specialists to invoke.
- **Specialist Team** (parallel): Domain experts — IMS, Transport, Core, Subscriber Data — each with focused tool sets and domain-specific prompts.
- **Synthesis** (Gemini Pro): Fact-checks specialist findings against raw evidence, produces the final diagnosis.

The architecture was elegant. The prompts were sharp. The synthesis agent even had instructions to cross-check specialist conclusions against raw evidence and flag inconsistencies.

We were confident this would outperform v1.5.

## The Results

We tested v2 against the exact same failure — the `udp_mtu_try_proto = TCP` scenario.

| Metric | v1.5 (Single Agent) | v2 (Multi-Agent) |
|--------|---------------------|-------------------|
| **Score** | 90% | 88% |
| **Root cause identified** | Yes | Yes |
| **Tokens consumed** | 159,000 | **1,478,000** |
| **Recommendation** | Correct: "change config on P-CSCF" | **Wrong**: "configure UE2 to listen on TCP" |
| **Tool calls** | 7 | Dozens across 5 phases |

The multi-agent system consumed **9.3x more tokens**, scored **2 points lower**, and gave a **wrong recommendation** — all while correctly identifying the root cause. It found the problem but prescribed the wrong fix.

Let that sink in: a system that was architecturally more sophisticated, had more specialized knowledge, and ran more investigation in parallel... performed worse on every meaningful dimension.

## What Went Wrong

Three distinct failure modes compounded into the overall degradation.

### 1. The Token Explosion: Context Duplication Is Multiplicative

ADK's `SequentialAgent` doesn't distill context between phases — it accumulates. Each phase inherits the full conversation history from all prior phases, then adds its own tool outputs on top.

Here's the token math:

```
Phase 0 (Triage):     ~20K  (metrics dump into state)
Phase 1 (Tracer):     ~80K  (reads logs from 6 containers + all of Phase 0)
Phase 2 (Dispatch):   ~90K  (Phase 0 + Phase 1 context + dispatch reasoning)
Phase 2 (Specialists): 4 × ~150K  (EACH specialist gets ALL prior context
                                    + makes their own tool calls)
Phase 3 (Synthesis):  ~200K  (everything above + synthesis reasoning)
─────────────────────────────────────
Total:                ~1,478K tokens
```

The v1.5 agent, by contrast, made 7 targeted tool calls with `grep` filtering. When it checked the P-CSCF config, it ran `read_running_config(container="pcscf", grep="udp_mtu")` — which returned 2 lines, about 20 tokens. The v2 Transport Specialist read the same config without filtering, getting thousands of tokens of irrelevant configuration.

Worse: four specialists ran in parallel but read overlapping containers. The IMS Specialist read P-CSCF logs. The Transport Specialist also read P-CSCF config. Both were investigating the same container from different angles, but the ADK framework counted every token independently.

**The overhead isn't additive — it's multiplicative.** Each phase re-sends everything that came before, and parallelism creates duplicate reads rather than shared ones.

### 2. Information Loss at Agent Boundaries: The Wrong Recommendation

This was the most consequential failure.

The v1.5 single agent held the full evidence chain in one context window. It discovered `udp_mtu_try_proto = TCP` through its own investigation, understood that this was a single configuration parameter on one server, and naturally concluded: *change the config on the P-CSCF.* The fix was obvious because the agent had the full investigative context.

The v2 system decomposed this reasoning across agents:

- The **Transport Specialist** found: "P-CSCF sends TCP because `udp_mtu_try_proto = TCP`. UE2 only listens on UDP."
- The **Synthesis Agent** received this finding as a summary.

The Synthesis Agent saw two facts: "P-CSCF sends TCP" and "UE2 only listens on UDP." Both facts are correct. But without the investigative journey — without having personally discovered that `udp_mtu_try_proto` is a trivially changeable Kamailio config parameter — the Synthesis Agent chose the wrong fix direction: "configure UE2 to listen on TCP."

From the Synthesis Agent's perspective, both fixes resolve the mismatch. It didn't know that:
- Changing one Kamailio config line on one server is a 30-second fix.
- Making every UE client listen on TCP requires changing client software, testing registration flows, and ensuring TCP keepalives work through the GTP tunnel.

**When you decompose a single reasoning chain across agents, the synthesis agent gets conclusions without the investigative journey.** It knows *what* was found but not the relative difficulty, risk, or correctness of each fix direction. The "fixability signal" — the intuitive sense that one fix is obviously easier — lives in the investigative context that was lost at the agent boundary.

### 3. Parallelism Created Redundant Work, Not Efficiency

The design assumed that four specialists running in parallel would be faster than one agent running sequentially. In practice:

- The **IMS Specialist** read P-CSCF logs and ran `kamcmd` against Kamailio.
- The **Transport Specialist** read P-CSCF config and checked process listeners.
- The **Core Specialist** checked 5G core status (irrelevant to this SIP-layer failure).
- The **Subscriber Data Specialist** verified subscriber provisioning (also irrelevant).

Two of the four specialists did useful work. Both investigated the same component (P-CSCF). The other two consumed tokens investigating perfectly healthy subsystems.

Meanwhile, the v1.5 single agent followed a linear but efficient path: metrics first, then both UE logs, then Call-ID trace, then pivot to transport check when the trace showed the INVITE never reached UE2. Seven calls. No wasted work. The investigation discipline came from the prompt, not the architecture.

## The Fundamental Tension

```
SINGLE AGENT (v1.5)                  MULTI-AGENT (v2)

┌────────────────────────┐       ┌────────┐   ┌────────┐   ┌──────────┐
│ One context window     │       │ Triage │ → │ Tracer │ → │Specialist│
│ Full evidence chain    │       │(summary│   │(summary│   │ (summary)│
│ Direct reasoning       │       │  out)  │   │  out)  │   │          │
│ 7 targeted tool calls  │       └────────┘   └────────┘   └────┬─────┘
│ 159K tokens            │                                      │
│ Correct recommendation │       ┌──────────────────────────────┘
│                        │       │ Synthesis Agent
└────────────────────────┘       │ - Sees summaries, not evidence
                                 │ - Lost: WHY P-CSCF sends TCP
                                 │ - Lost: config is trivially fixable
                                 │ - Result: wrong fix direction
                                 │ - 1,478K tokens
                                 └──────────────────────────────────
```

Here's the irony: the multi-agent architecture was designed to solve the v1 problem — undisciplined investigation, chasing wrong hypotheses, filling the context window with irrelevant logs. But v1.5 had *already solved that problem* with better prompting. The 7-step investigation methodology and known failure patterns table enforced the same discipline that the multi-agent architecture was supposed to provide.

The architecture solved a problem that no longer existed, while creating new problems that didn't exist before.

## When Multi-Agent Helps vs. Hurts

This isn't an argument against multi-agent systems. It's an argument for understanding when decomposition helps and when it hurts.

**Multi-agent helps when:**
- The problem genuinely can't fit in one context window (our 5G stack logs can, in 159K tokens).
- Sub-problems are truly independent — no specialist needs another specialist's findings to do its job.
- The "synthesis" step is trivial — assembling independent results, not reasoning about causal chains.
- You need different trust levels or capabilities per phase (e.g., one agent writes code, another reviews it).

**Multi-agent hurts when:**
- A single well-prompted agent can handle the problem (most troubleshooting fits in one context window).
- The reasoning chain is causal — A causes B causes C — and decomposing it loses the causal signal.
- Specialists have overlapping scope (our IMS and Transport specialists both investigated the P-CSCF).
- The synthesis step requires "fixability intuition" that only comes from the investigative journey.
- The framework doesn't distill context between phases (ADK's SequentialAgent accumulates; it doesn't summarize).

### The Context Distillation Problem

The core technical issue is that ADK's `SequentialAgent` passes the full conversation forward. What's needed is aggressive summarization at each phase boundary:

```
Phase 1 output (what ADK does):
  "Here's the complete conversation including all tool calls,
   raw log outputs, and intermediate reasoning..."  [80K tokens]

Phase 1 output (what's needed):
  "Call-ID KbLunzr traced across stack. INVITE seen in pcscf,
   scscf, icscf. NOT seen in e2e_ue2. Failure point: between
   P-CSCF and UE2. P-CSCF sent via TCP (evidence: udp_mtu_try_proto=TCP
   in kamailio_pcscf.cfg line 412, trivially configurable).
   UE2 listens on UDP only (evidence: ss -tlnp shows port 5060/udp)."
   [200 tokens]
```

The second version preserves the *investigative context* — not just what was found, but why it matters and how fixable it is. This is what the Synthesis Agent needs to make a correct recommendation.

## Five Lessons for Agent Architects

**1. Start with a single well-prompted agent.** You will be surprised how far 11 tools and a good system prompt can take you. Our v1.5 prompt was 145 lines and included known failure patterns, a mandatory investigation methodology, and a disconfirmation step. That's cheaper to build and maintain than a 5-phase multi-agent pipeline.

**2. Don't decompose causal reasoning.** If the diagnosis requires tracing a causal chain (timeout → cascading error → misleading symptom), keep that chain in one context window. The moment you split "P-CSCF sends TCP because of `udp_mtu_try_proto`" from "therefore change `udp_mtu_try_proto`," you've lost the fixability signal.

**3. If you must use multi-agent, invest in context distillation.** The #1 technical investment for multi-agent systems isn't better specialists — it's better summaries between phases. Every phase boundary should produce a structured, token-efficient summary that preserves not just findings but investigative context (what was checked, what was easy vs. hard, what the evidence actually showed).

**4. Measure tokens, not just accuracy.** Our v2 scored 88% — only 2 points below v1.5. If we'd only measured accuracy, we might have shipped it. But at 9.3x the token cost and with a wrong recommendation, v2 is strictly worse. Token efficiency is a first-class metric for agent systems.

**5. Parallelism only helps when work is truly independent.** Four specialists reading overlapping containers is worse than one agent reading them sequentially with grep filters. Before parallelizing, check whether your "independent" agents actually have independent scope.

## Where We Go From Here

We're not abandoning multi-agent. We're being more surgical about when to use it:

- **Triage stays deterministic.** No LLM needed to check if containers are running or metrics are zero. This was the one part of v2 that was unambiguously good.
- **Single-agent investigation for most failures.** The v1.5 architecture — one agent, 11 tools, disciplined prompt — handles the common case well.
- **Multi-agent only for true parallel work.** When we need to probe every network hop simultaneously, or run a chaos experiment while monitoring symptoms, multi-agent adds real value.
- **Context distillation as infrastructure.** If we do multi-agent, we'll build explicit summarization at each phase boundary — not rely on the framework to pass raw context.

The meta-lesson is older than AI: **don't optimize what you haven't measured, and don't complicate what already works.** A single agent with good instructions outperformed a sophisticated multi-agent pipeline — not because single agents are always better, but because the problem didn't need decomposition, and decomposition has costs that are easy to underestimate.

---

*This post is based on real experiments running AI agents against a containerized 5G SA + IMS stack (Open5GS, Kamailio, PyHSS, UERANSIM). The failure scenario — a SIP transport mismatch caused by `udp_mtu_try_proto = TCP` — was a real production issue that took 40 minutes of manual debugging to diagnose. The agents were tested against this exact failure, with full scoring and token accounting.*

*Tools: Pydantic AI (v1.5), Google ADK (v2), Gemini 2.5 Pro/Flash via Vertex AI.*
