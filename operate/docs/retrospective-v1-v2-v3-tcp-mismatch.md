# Retrospective: Three Generations of AI Agents vs. One TCP/UDP Mismatch

*11 runs. 3 architectures. 0 correct diagnoses.*

---

## The Failure We Tried to Find

A single Kamailio configuration parameter — `udp_mtu_try_proto = TCP` on the P-CSCF — causes SIP INVITE messages larger than 1,300 bytes to be sent via TCP. The destination UEs (pjsua) only listen on UDP. The INVITE is silently dropped. A timeout cascades backward through four IMS nodes, surfacing as a `500 Server error on LIR select next S-CSCF` at the I-CSCF.

The fix: change one line on one server. `udp_mtu_try_proto = UDP`.

Every version of our AI agent failed to find it.

---

## The Runs

| # | Version | Tokens | Duration | Diagnosis | What Went Wrong |
|---|---------|--------|----------|-----------|-----------------|
| 1 | v2 | 1,079K | 141s | Wrong | Context poisoning — 97.5% prompt tokens. All specialists drowned in inherited history. |
| 2 | v2 | 985K | 146s | Wrong | Tracer distillation helped marginally. ADK still forwarded 68KB search_logs to every agent. |
| 3 | v3 | 149K | 142s | Wrong | Context isolation worked (85% token reduction). Transport found the right answer but Synthesis dismissed it — too terse vs IMS Specialist's verbose output. |
| 4 | v3 | 87K | 92s | Wrong | Domain Laws prompts improved structure. Dispatcher didn't select Transport — fixated on GTP=0. |
| 5 | v3 | 90K | 155s | Wrong | Same as #4. GTP=0 dominated dispatch reasoning. Transport never ran. |
| 6 | v3 | 102K | 92s | Wrong | Made transport mandatory in prompt. LLM ignored the instruction. Only IMS dispatched. |
| 7 | v3 | 75K | 101s | Wrong | Made transport mandatory in code. Transport ran but checked the wrong container (scscf instead of pcscf/e2e_ue2). Tracer framed failure as I-CSCF error. |
| 8 | v3 | 135K | 92s | Wrong | Added DELIVERY_FAILURE vs PROCESSING_FAILURE classification to tracer output. Tracer classified as PROCESSING_FAILURE because it never checked UE2. |
| 9 | v1.5 | 140K | ~90s | Wrong | The "gold standard" single agent also failed. Same Diameter I_Open theory. Checked UE2 but still concluded I-CSCF Diameter was the root cause. |

Every single run — across three architectures, six prompt revisions, and two code enforcement fixes — converged on the same wrong answer: *the I-CSCF Diameter connection to the HSS is in `I_Open` state.*

---

## Why They All Failed: The Red Herring

The Diameter `I_Open` state between the I-CSCF and HSS is a real anomaly in the stack. It's visible via `kamcmd cdp.list_peers` and it correlates perfectly with the `500 Server error on LIR` that every agent observes. The causal chain looks airtight:

```
I_Open state → LIR can't be sent → S-CSCF selection fails → 500 error → call fails
```

But it's wrong. Both UEs registered successfully through the same I-CSCF → HSS Diameter path moments before the call attempt. If Diameter were truly broken, registration (which uses UAR messages on the same connection) would have failed too. The `I_Open` state is either transient, a display artifact, or a pre-existing condition that doesn't actually block message exchange.

No version of the agent asked: *"If Diameter is broken, how did registration succeed?"*

The actual causal chain:

```
udp_mtu_try_proto=TCP → large INVITE sent via TCP → UE2 listens UDP only
→ INVITE silently dropped → P-CSCF times out → cascades as 408→500 at I-CSCF
```

The 500 at the I-CSCF is a symptom four hops away from the actual failure point.

---

## What We Built and What We Learned

### v1.5: The Single Agent (Pydantic AI + Gemini Pro)

One agent, 11 tools, a 145-line system prompt with a known failure patterns table and a 7-step investigation methodology.

**Architecture:**
```
User Question → [Single LLM Agent with 11 tools] → Diagnosis
```

**Strengths:** Simple. 140K tokens. Follows a disciplined investigation sequence (metrics → both UEs → Call-ID trace → infrastructure check). Checks UE2 — the one step that v3's tracer kept skipping.

**Weakness:** Found `I_Open`, stopped investigating. The disconfirmation step in the prompt ("ask what would prove you wrong") was ignored when the LLM found a compelling explanation. A single agent has no architectural checkpoint to force hypothesis testing.

**Lesson:** A well-prompted single agent is surprisingly capable, but prompt instructions are suggestions, not guarantees. When the LLM finds a satisfying answer, it stops — even if the prompt says to keep going.

### v2: The Multi-Agent Pipeline (ADK SequentialAgent)

Five phases, eight agents, four running in parallel. Designed to enforce investigation discipline through architecture.

**Architecture:**
```
Triage → Tracer → Dispatcher → [IMS | Transport | Core | Subscriber] → Synthesis
         (all in one ADK session, sharing conversation history)
```

**Strengths:** Specialist agents with focused prompts and domain-specific tools. Parallel execution of independent investigations.

**Fatal flaw:** ADK's SequentialAgent passes the full conversation history — every LLM turn, every tool call, every tool response — to every subsequent agent. By the time specialists ran, each inherited 125-250K tokens of accumulated noise. The Tracer's 68KB `search_logs` result was forwarded to every downstream agent.

**The numbers tell the story:**

| Agent | Prompt Tokens | Own Tool Data | Inherited Noise |
|---|---|---|---|
| TriageAgent | 10K | 6.5KB | 0 |
| EndToEndTracer | 128K | 90KB | ~10K |
| DispatchAgent | 61K | 0 | ~128K |
| Each Specialist | 125-253K | 0.2-4.3KB | 125-253K |
| SynthesisAgent | 67K | 0 | ~67K |

The specialists received 125-253K tokens of context to read 0.2-4.3KB of new data. 97.5% of all tokens were prompt tokens — the agents were drowning in noise, causing attention dilution and hallucinations.

**Lesson:** In a multi-agent pipeline, context management is not optional — it's the primary engineering challenge. Without session isolation, multi-agent is strictly worse than single-agent.

### v3: Context-Isolated Pipeline (Custom Session-Per-Phase)

Same five phases and agent types, but each phase runs in its own ADK session. Only structured state (the `output_key` text) flows between phases — no conversation history leaks.

**Architecture:**
```
Session A: Triage      → state["triage"]
Session B: Tracer      → state["trace"]     (sees triage via {triage} placeholder)
Session C: Dispatcher  → state["dispatch"]  (sees triage + trace)
Session D: Specialists → state["finding_*"] (sees triage + trace, fresh conversation)
Session E: Synthesis   → state["diagnosis"] (sees all findings, fresh conversation)
```

**The token reduction was dramatic:**

| Agent | v2 Tokens | v3 Tokens | Reduction |
|---|---|---|---|
| TriageAgent | 18K | 5K | -72% |
| EndToEndTracer | 131K | 22-55K | -58-83% |
| DispatchAgent | 64K | 3K | **-95%** |
| TransportSpecialist | 127K | 6-11K | **-91-95%** |
| IMSSpecialist | 193K | 6-44K | **-77-97%** |
| CoreSpecialist | 255K | 5-19K | **-93-98%** |
| SynthesisAgent | 71K | 4-5K | **-93%** |
| **Total** | **985K** | **75-135K** | **86-92%** |

The Dispatcher — which in v2 consumed 64K tokens just to read accumulated context and make a routing decision — dropped to 3K tokens. It now reads only the distilled triage and trace text from state placeholders.

**But the diagnosis was still wrong,** for reasons that had nothing to do with tokens or architecture. The pipeline hit a sequence of new bottlenecks, each requiring its own fix:

1. **Dispatcher ignored transport** — fixated on GTP=0 → fixed with code enforcement
2. **Transport checked wrong container** — tracer framed failure as I-CSCF error → fixed with classification framework
3. **Tracer skipped UE2 check** — found I-CSCF 500 and stopped → same LLM compliance failure

**Lesson:** Context isolation solves the token/cost/noise problem completely. But it doesn't solve the reasoning problem — that lives in prompts, and prompts are suggestions that LLMs can ignore.

---

## The Whack-a-Mole Pattern

Each fix we applied uncovered the next bottleneck:

```
v2: Context poisoning → v3: Session isolation (fixed tokens)
v3 run 1: Synthesis dismissed Transport → Updated Synthesis Hierarchy of Truth
v3 run 2: Dispatcher skipped Transport → Updated GTP=0 interpretation
v3 run 3: Dispatcher STILL skipped Transport → Enforced in code
v3 run 4: Transport checked wrong container → Added tracer classification
v3 run 5: Tracer classified wrong → Tracer skipped UE2 check
v3 run 6: v1.5 also fails → The Diameter I_Open red herring fools everyone
```

The pattern reveals a fundamental principle: **any step that must always happen cannot be left to LLM discretion.** We learned this twice:
- The Dispatcher was told "always include transport" in the prompt. The LLM ignored it. We enforced it in code.
- The Tracer was told "immediately check UE2." The LLM ignored it when it found the I-CSCF 500 first.

Prompts are heuristics. Code is deterministic. Critical investigation steps belong in code.

---

## The Scoreboard

| Metric | v1.5 | v2 | v3 (best) |
|---|---|---|---|
| Tokens per run | 140K | 985K-1,123K | **75K** |
| Token efficiency vs v2 | — | baseline | **92% reduction** |
| Duration | ~90s | 141-155s | **92s** |
| Correct diagnosis | No | No | No |
| Checked UE2 | Yes | No | Sometimes |
| Checked P-CSCF config | No | No | No |
| Found `udp_mtu_try_proto` | No | No | No |

v3 solved the engineering problem (cost, speed, observability) while revealing that the reasoning problem is deeper than architecture. The Diameter `I_Open` state acts as an "attractor" — a plausible-looking anomaly that captures every agent's attention regardless of how it's structured, prompted, or orchestrated.

---

## What Would Actually Fix the Diagnosis

1. **Fix the red herring in the stack.** If the Diameter `I_Open` state were resolved (by restarting the I-CSCF or fixing the underlying handshake), the agents would be forced to look elsewhere. The most dangerous red herring is a real anomaly that's unrelated to the actual failure.

2. **Enforce disconfirmation in code.** After any agent proposes a root cause, programmatically check: "Does this explanation account for all observations?" If Diameter is blamed but registration succeeded, auto-reject the hypothesis and force deeper investigation.

3. **Make the critical two-tool-call sequence deterministic.** The actual root cause is found by exactly two tool calls: `read_running_config(pcscf, grep="udp_mtu")` and `check_process_listeners(e2e_ue2)`. These could be run as a mandatory pre-check whenever the trace shows a delivery failure — no LLM judgment needed.

4. **Train on episodes.** The chaos monkey platform was built to generate labeled failure episodes. Running the agent against dozens of different fault types — where the Diameter `I_Open` state may or may not be present — would teach us which failure patterns the agent handles well and which need architectural guardrails.

---

## The Deeper Lesson

Multi-agent AI systems fail differently than single-agent systems, but they fail for the same fundamental reason: **LLMs follow the most compelling signal, not the most correct one.** Architecture can control token costs, enforce tool isolation, and guarantee that certain agents run. But it cannot force an LLM to prefer a subtle transport mismatch over a loud Diameter error.

The path forward isn't better prompts or more agents. It's a hybrid architecture where:
- **Code handles rules** — mandatory investigation steps, hypothesis disconfirmation, known failure pattern matching
- **LLMs handle judgment** — interpreting evidence, connecting dots across domains, explaining findings to humans
- **Episodes provide feedback** — running the agent against diverse, labeled failures to discover blind spots before they matter in production

v3's context isolation is the right foundation. The token problem is solved. The reasoning problem is next.
