# Evaluation: P-CSCF Latency — Both Agents Trapped by I_Open

**Date:** 2026-03-25
**Scenario:** P-CSCF Latency
**Result:** Both v1.5 and v3 failed
**Root issue:** Agents cannot distinguish latency-induced timeouts from broken connections

---

## The Scenario

We injected 500ms network latency (with 50ms jitter) on the P-CSCF container using `tc netem`. The P-CSCF is the SIP edge proxy — every IMS signaling message passes through it. Kamailio's SIP T1 timer is 500ms, so at this latency, REGISTER transactions start timing out. The UEs report `408 Request Timeout`.

This is a network-layer fault. All containers are running. All processes are healthy. The only problem is that packets are slow.

**Ground truth:** `pcscf` — network latency — severity: degraded

---

## v3 Agent Performance

**Log:** [`agentic_ops_v3/docs/agent_logs/run_20260325_150437_p_cscf_latency.md`](../../agentic_ops_v3/docs/agent_logs/run_20260325_150437_p_cscf_latency.md)
**Score:** 25%
**Tokens:** 98,023
**Time to diagnosis:** 108.7s

**What it concluded:** "UE registration is failing due to a broken Diameter connection between the I-CSCF and HSS. The Diameter peer connection from the I-CSCF to the HSS is stuck in the `I_Open` state."

The v3 agent saw the `I_Open` state on Diameter peers (which is a permanent cosmetic artifact in our stack — see the I_Open resolution in the evaluation plan) and concluded the Diameter connection was broken. It never investigated why SIP transactions were timing out or checked the transport layer for latency.

The per-phase token breakdown shows where the investigation went:

| Phase | Tokens | What it did |
|-------|--------|-------------|
| TriageAgent | 12,746 | Detected symptoms correctly (408 timeouts) |
| EndToEndTracer | 28,523 | Traced the call flow, found I_Open |
| TransportSpecialist | 29,185 | Spent the most tokens but still missed `tc` rules |
| IMSSpecialist | 15,899 | Reinforced the I_Open theory |
| SynthesisAgent | 7,211 | Synthesized the wrong conclusion |

The TransportSpecialist consumed 29K tokens and 4 tool calls but never ran `tc qdisc show` on the P-CSCF or measured RTT. It doesn't have those tools, and its prompt doesn't instruct it to check for traffic control rules.

---

## v1.5 Agent Performance

**Log:** [`agentic_ops/docs/agent_logs/run_20260324_211749_p_cscf_latency.md`](../../agentic_ops/docs/agent_logs/run_20260324_211749_p_cscf_latency.md)
**Score:** 15%
**Tokens:** 514,089
**Time to diagnosis:** 94.5s

**What it concluded:** "VoNR call failure due to loss of Diameter connectivity between IMS CSCFs and the HSS. Both the I-CSCF and S-CSCF are unable to establish a functional Diameter connection with the HSS (PyHSS), as evidenced by their peer connections being stuck in the 'I_Open' state."

Same failure mode as v3 — fixated on I_Open, concluded Diameter was broken, never checked for latency. Scored even worse than v3 (15% vs 25%) because it didn't even mention `pcscf` as an affected component, and burned 5x more tokens doing it.

---

## Why Both Agents Failed

### 1. I_Open is the loudest signal, and it's wrong

Both agents check `kamcmd cdp.list_peers` early in their investigation. It returns `I_Open` — which looks alarming but is a permanent cosmetic artifact of the PyHSS/Kamailio interop in our stack. The agents treat it as a smoking gun and build their entire diagnosis around it, ignoring the actual fault.

Despite the agent prompts being updated to note that `I_Open` is a known benign condition, the agents still fixated on it. The I_Open signal is too similar to the observed symptoms (SIP timeouts → must be a broken upstream connection) for the LLM to dismiss it based on a prompt disclaimer alone.

### 2. No tools or instincts for transport-layer inspection

Neither agent can:
- Run `tc qdisc show` to check for netem/tbf rules on a container
- Measure RTT between containers (ping)
- Inspect network namespace configuration

The fault is invisible at the application layer. Container status: running. Process status: healthy. Logs: timeouts (which look identical to a broken connection). The only way to find this fault is to look at the network layer, and the agents have no tools for that.

### 3. "Slow" looks identical to "broken" without timing data

A `408 Request Timeout` from a 500ms latency looks exactly like a `408 Request Timeout` from an unreachable peer. Both agents interpreted the timeout as evidence of a dead connection. They don't reason about timing — they don't ask "is this timeout because the peer is slow or because it's gone?"

### 4. v1.5 is dramatically less token-efficient

| Metric | v1.5 | v3 | Ratio |
|--------|------|-----|-------|
| Total tokens | 514,089 | 98,023 | 5.2x |
| Score | 15% | 25% | worse |
| Tool calls | 13 | 11 | similar |

v1.5's single large-context architecture accumulates all tool results into one growing conversation. By the end, most of those 514K tokens are the LLM re-reading prior tool outputs. v3's context-isolated phases avoid this — each specialist starts with a fresh context seeded only with structured state from prior phases.

---

## Proposal: How to Fix This

### Short-term: Add transport-layer tools

Add two new tools available to the agents:

1. **`check_tc_rules(container)`** — Runs `tc qdisc show dev eth0` inside the container's network namespace. Returns any active netem (latency/loss/corruption) or tbf (bandwidth) rules. If rules exist, this is almost certainly the root cause.

2. **`measure_rtt(source_container, target_ip)`** — Runs `ping -c 3` from one container to another and returns the RTT. Elevated RTT (>100ms in a Docker network where normal RTT is <1ms) immediately points to a latency fault.

### Short-term: Add a transport-layer check to the investigation pipeline

Before the agents reason about application-layer issues, they should run a transport health check on any container showing timeouts. This should be a **code-enforced step**, not a prompt suggestion — the LLM will skip it if given the choice.

For v3, this means adding a pre-check in the TransportSpecialist that always runs `check_tc_rules` on containers mentioned in triage findings before doing anything else.

For v1.5, this means adding `check_tc_rules` as a tool and adding explicit instructions: "If you see timeouts, check for tc rules on the affected container BEFORE investigating application-layer causes."

### Medium-term: Strengthen I_Open handling

The prompt disclaimer about I_Open isn't enough. Options:

1. **Filter it out of tool output:** When `kamcmd cdp.list_peers` returns `I_Open`, the tool wrapper could annotate it with `[KNOWN BENIGN — see I_Open documentation]` to make it harder for the LLM to treat as a finding.

2. **Add a validation step:** Before the agent concludes "Diameter is broken because I_Open", require it to verify by checking whether Diameter messages are actually flowing (e.g., check PyHSS logs for recent UAR/MAR processing). If messages are flowing, I_Open is cosmetic.

### What success looks like

After these changes, re-running this scenario should produce a diagnosis like: "P-CSCF has 500ms network latency (tc netem delay rule active on eth0). This exceeds Kamailio's SIP T1 timer, causing REGISTER transactions to timeout with 408. Recommendation: remove the tc rule or increase T1 timer."
