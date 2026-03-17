# RCA Reflection: IMS Registration 408 — Why It Took 30+ Minutes

**Date:** 2026-03-17
**Related RCA:** [ims_registration_failed_408.md](ims_registration_failed_408.md)

---

## Where I Got Stuck & Why It Took So Long

### 1. I Started at the Wrong Layer

I dove straight into **SIP signaling analysis** — tracing CSeq numbers through Kamailio logs, analyzing Diameter SAR/SAA async callback timing, examining Via headers, scrutinizing transaction suspension mechanics. I spent many rounds on the hypothesis that the I-CSCF's 5-second `t_set_fr()` timeout was expiring before the S-CSCF's async SAR completed. I eventually disproved it (S-CSCF processing took ~110ms, well within 5 seconds) — but that was 15+ minutes wasted.

**The actual problem was that UDP packets weren't reaching the P-CSCF at all.** A single `tcpdump` would have revealed this in 30 seconds.

### 2. I Was Anchored by the Previous Session's Hypothesis

The context from the prior conversation had me deep in the S-CSCF → I-CSCF response path analysis. I resumed that thread faithfully instead of re-assessing from first principles. The prior session had established that "the request path works but the response path is broken" — so I kept digging into the response path. I never questioned whether the request path was *still* working on March 17.

### 3. I Followed a Top-Down Approach (Application → Network) Instead of Bottom-Up

The standard telecom troubleshooting methodology is **OSI bottom-up**: physical → data link → network → transport → application. I went the opposite direction — starting at Layer 7 (SIP), then Layer 5 (Diameter), and only eventually reaching Layer 3 (IP routing, GTP tunnels). An experienced network engineer would have checked data plane connectivity first.

### 4. Log Grep Rabbit Holes

My investigation pattern was: grep logs → find a clue → grep more logs → find another clue → repeat. Each round produced genuinely interesting SIP-level findings (the SAR timing, the CSeq interleaving, the transaction suspension values), but none of them led to the root cause. I was doing **thorough but misdirected** work.

The sequence of greps I ran before finally checking basic connectivity:

1. S-CSCF logs for SAR/callback timing
2. S-CSCF logs for CSeq 19752 full trace
3. S-CSCF logs for reply/send operations
4. I-CSCF logs for Call-ID correlation
5. P-CSCF logs for reply processing
6. S-CSCF config file analysis
7. I-CSCF register route analysis

That's ~12 tool calls before I ran the first tcpdump.

### 5. I Didn't Use Stats/Health Commands Early

Kamailio's `kamcmd tm.stats` immediately showed only **20 transactions total** — a screaming red flag that the P-CSCF hadn't received SIP traffic in days. If I'd run that first, I would have pivoted to "why isn't traffic arriving?" instead of "why aren't responses coming back?"

### 6. I Didn't Send Synthetic Test Probes Early

When I finally sent a test SIP OPTIONS from inside the P-CSCF container, it was processed immediately — proving the P-CSCF was alive. When I sent one from the UE's `192.168.101.10` address, it never arrived — proving the GTP tunnel was broken. These two tests, done in the first 5 minutes, would have isolated the problem to the GTP data plane.

---

## What an Agentic Troubleshooting System Should Do Differently

### 1. Always Start with a Layered Health Check (Bottom-Up)

Before analyzing any application logs, the agent should run a **systematic connectivity sweep**:

```
Phase 0: Infrastructure Health (30 seconds)
  - Are all containers running? (docker ps)
  - Are all processes alive? (ps aux / kamcmd uptime per node)
  - Basic stats per node (kamcmd tm.stats, memory, active sessions)

Phase 1: Data Plane Verification (60 seconds)
  - Can UE reach P-CSCF? (synthetic UDP probe from source IP)
  - Can P-CSCF reach I-CSCF? (synthetic probe)
  - Can I-CSCF reach S-CSCF? (synthetic probe)
  - Is GTP tunnel functional? (tcpdump at UPF for GTP-U traffic)
  - Check interface stats (TX/RX counters on tunnel interfaces)

Phase 2: Application-Level Triage (only if Phase 0-1 pass)
  - Recent SIP transaction stats
  - Error counts per node
  - THEN dive into log analysis
```

If Phase 1 fails, skip Phase 2 entirely. Don't analyze SIP logs when packets aren't even arriving.

### 2. Hypothesis-Driven Investigation with Kill Conditions

Each hypothesis should have a **maximum cost budget** and a **kill condition**:

```
Hypothesis: "I-CSCF timeout expires before S-CSCF responds"
  Kill condition: If S-CSCF processing time < 5 seconds → DISPROVE and move on
  Max cost: 3 tool calls
```

I spent ~8 tool calls on the timing hypothesis before disproving it. An agent should cap this.

### 3. "Re-verify Assumptions" Step When Resuming Investigations

When continuing from a previous session, the agent should **re-verify the previous session's assumptions** before continuing the investigation thread. The prior session established "request path works" — but that was 4 days ago. A single check would have shown it no longer held.

This is a general principle: **stale context is dangerous.** An agentic system that resumes from a prior session should treat prior conclusions as hypotheses to re-verify, not facts to build on.

### 4. Parallel Multi-Layer Probing

Instead of sequential investigation, the agent should probe **multiple layers simultaneously**:

```
Parallel batch 1 (run all at once):
  - docker exec pcscf kamcmd tm.stats              (app-level health)
  - docker exec pcscf tcpdump -c 1 udp port 5060   (is traffic arriving?)
  - docker exec e2e_ue1 ip -s link show uesimtun1  (tunnel counters)
  - docker logs --tail 5 nr_gnb                     (gNB status)
```

All four commands are independent. Running them in parallel would have immediately surfaced: zero transactions, zero traffic, asymmetric TX/RX, and "signal lost." Total time: ~5 seconds instead of 30 minutes.

### 5. Anomaly Detection Over Log Grepping

Instead of grepping for specific CSeq/Call-ID patterns, the agent should first ask **"what's abnormal?"**:

| Observation | Expected | Actual | Verdict |
|-------------|----------|--------|---------|
| P-CSCF total transactions (4 days) | Thousands | 20 | **ABNORMAL** |
| I-CSCF reply route entries | Many | 0 | **ABNORMAL** |
| UE uesimtun1 TX/RX ratio | ~1:1 | 4088:20 | **ABNORMAL** (99.5% loss) |
| gNB status messages | Connected | "signal lost" | **ABNORMAL** |
| P-CSCF last SIP log entry | Recent | 4 days ago | **ABNORMAL** |

Pattern detection beats targeted log analysis for initial triage. An agentic system should run broad anomaly checks before narrow deep-dives.

### 6. Maintain an Investigation Stack with Backtracking

My investigation was essentially a depth-first search that went too deep into one branch. The agent should maintain an explicit investigation stack:

```
What actually happened (depth-first, no backtracking):

[Layer 7: SIP response path]
  └─ grep S-CSCF SAR timing
  └─ grep I-CSCF reply routes
  └─ grep P-CSCF reply processing
  └─ analyze I-CSCF config
  └─ analyze S-CSCF async transaction model
  └─ ... 15+ minutes in this branch ...
  └─ eventually checked connectivity → found real problem

What should have happened (bottom-up with early kills):

[Phase 0: Health check] → P-CSCF tm.stats = 20 total → RED FLAG → 30 seconds
  ↓
[Phase 1: Data plane] → tcpdump = 0 packets at P-CSCF → FOUND IT → 60 seconds
  ↓
[Phase 1b: Where is it breaking?] → probe from uesimtun1 IP → 0 at UPF → 60 seconds
  ↓
[Phase 1c: Why?] → gNB "signal lost" + tunnel TX/RX asymmetry → ROOT CAUSE → 60 seconds
  ↓
Total: ~4 minutes
```

---

## The Core Lesson

**The most expensive mistake in troubleshooting is being thorough at the wrong layer.**

Every minute spent analyzing SIP transaction timing at the S-CSCF was wasted because the problem was in the GTP data plane two layers below. An agentic system needs to be disciplined about verifying lower layers before investing in upper-layer analysis — even when the upper-layer analysis feels productive and produces interesting findings.

The SIP-level analysis wasn't *wrong* — it uncovered a real secondary issue with the S-CSCF response path. But it wasn't the *current* problem. The agent confused "interesting finding" with "root cause" and kept pulling the thread.

### 7. I Never Checked Prometheus/Grafana

This is the most damning oversight. The stack has **Prometheus (port 9090) and Grafana (port 3000) running**, scraping metrics from the AMF, SMF, UPF, and PCF every 5 seconds. These metrics include:

- `fivegs_ep_n3_gtp_indatapktn3upf` — GTP data plane incoming packets at UPF
- `fivegs_ep_n3_gtp_outdatapktn3upf` — GTP data plane outgoing packets at UPF
- `fivegs_upffunction_upf_sessionnbr` — UPF session count
- `ran_ue` — RAN-connected UEs
- `amf_session` — AMF sessions
- `fivegs_amffunction_rm_reginitreq/succ` — 5G NAS registration stats

A single Prometheus query would have revealed the root cause in **under 3 seconds**:

```
$ curl -s "http://localhost:9090/api/v1/query?query=fivegs_ep_n3_gtp_indatapktn3upf"
→ value: 0    # ZERO GTP data plane traffic. Dead.

$ curl -s "http://localhost:9090/api/v1/query?query=fivegs_ep_n3_gtp_outdatapktn3upf"
→ value: 0    # Zero in both directions.
```

The full one-shot metrics triage takes 3 seconds and tells the whole story:

| Metric | Value | Interpretation |
|--------|-------|---------------|
| `gtp_indatapktn3upf` | **0** | **Data plane dead** |
| `gtp_outdatapktn3upf` | **0** | **Dead in both directions** |
| `upf_sessionnbr` | 4 | Control plane OK (sessions exist) |
| `ran_ue` | 2 | AMF thinks UEs are connected |
| `gnb` | 1 | gNB registered |
| `rm_reginitreq/succ` | 9/9 | 5G NAS registration succeeded |
| `amf_authfail` | **6** | Auth failures (secondary signal) |

**Diagnosis writes itself**: Control plane healthy (sessions exist, UEs registered, gNB connected), but data plane completely dead (zero GTP packets). Sessions established but no user traffic flowing. Points directly to GTP-U forwarding layer — the gNB RLS issue.

**Why I didn't check**: I don't have Prometheus/Grafana in my mental model as a *troubleshooting* tool. My instinct is `docker logs` + `grep`. That's a developer's instinct, not an operator's. For operational systems, **the metrics store IS the troubleshooting entry point** — the open5gs developers already thought about what needs to be observable and exported it as metrics. The information was pre-computed and waiting. I ignored it and went mining raw logs instead.

This is the single biggest improvement an agentic troubleshooting system can make: **query the metrics store first, before touching a single log file.**

---

### Anti-Patterns to Avoid in Agentic Troubleshooting

1. **Confirmation anchoring**: Continuing a previous session's investigation thread without re-verifying its premises.
2. **Top-down investigation**: Starting at the application layer when the problem might be at a lower layer.
3. **Log grep spirals**: Using log entries as breadcrumbs that lead deeper into the same layer instead of stepping back to check a different layer.
4. **Thoroughness bias**: Preferring a complete analysis of the wrong hypothesis over a quick check of the right one.
5. **Sequential when parallel is possible**: Running one diagnostic at a time when multiple independent checks could run simultaneously.

### Design Principles for an Agentic Troubleshooting System

1. **Metrics store first. Always.** Before touching a single log file, query Prometheus/Grafana for the pre-computed system health view. Metrics are structured, time-series, and purpose-built for anomaly detection. Logs are unstructured, verbose, and require parsing. A 3-second Prometheus query replaces 30 minutes of log grep spirals.
2. **Bottom-up by default.** After metrics, verify connectivity at each layer before analyzing application logic. OSI model exists for a reason.
3. **Budget your hypotheses.** Each hypothesis gets N tool calls max. If not confirmed, backtrack.
4. **Re-verify stale context.** Assumptions from prior sessions are hypotheses, not facts.
5. **Parallel probing.** Run independent diagnostics concurrently to maximize information per unit time.
6. **Anomaly-first, detail-second.** Broad stats checks before narrow log greps.
7. **Synthetic probes over log analysis.** Sending a test packet is faster and more definitive than reading 10,000 log lines.
8. **Explicit investigation state.** Track what layer you're on, what hypothesis you're testing, how many tool calls you've spent, and what the kill condition is.

### Revised Investigation Flow (Incorporating Metrics)

```
Phase 0: METRICS TRIAGE (3 seconds)
  Query Prometheus for key indicators:
  - Data plane: GTP packet counters (in/out)
  - Control plane: session counts, UE counts, gNB count
  - Registration: success/failure counters
  - Auth: failure/reject counters
  → If data plane counters = 0 → skip to Phase 1
  → If control plane counters abnormal → investigate control plane
  → If all healthy → proceed to Phase 2

Phase 0b: GRAFANA VISUAL CHECK (10 seconds)
  Open time-series dashboard:
  - When did the anomaly start?
  - Is it a gradual degradation or a cliff?
  - Does it correlate with any other metric change?

Phase 1: DATA PLANE VERIFICATION (60 seconds)
  Only if Phase 0 flags a data plane issue:
  - tcpdump at each hop
  - Interface TX/RX counters
  - Synthetic probes from actual source IPs

Phase 2: APPLICATION ANALYSIS (only if Phases 0-1 pass)
  - Process health stats (kamcmd, etc.)
  - Then and ONLY then: log analysis
```

The key insight: **Prometheus is the radiograph. Logs are the biopsy.** You don't skip the radiograph and go straight to cutting tissue.
