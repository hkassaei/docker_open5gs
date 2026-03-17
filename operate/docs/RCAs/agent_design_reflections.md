# Agentic RCA System Design: Architecture Reflections

**Date:** 2026-03-17
**Context:** Design thinking for an AI agent that automates IMS/5G network root cause analysis, based on lessons learned from the [IMS Registration 408 RCA](ims_registration_failed_408.md) and [investigation reflections](rca_reflections.md).

---

## The Core Question

> If you were to design an agentic system to perform such RCA in the future, would you break it down into multiple (sequential or parallel) agents and sub-agents, or would you design the whole thing in one agent?

**Answer: Neither pure single-agent nor pure parallel. A gated multi-phase architecture with an orchestrator.**

---

## Why a Single Agent Won't Work

A single agent will always have the same failure modes observed in the manual investigation:

1. **Context window fills with log output.** Each `docker logs | grep` dumps hundreds of lines. After 10 greps, the agent is swimming in data and can't see the forest for the trees.

2. **No enforced investigation discipline.** A single agent follows the most "interesting" thread, not the most diagnostic one. SIP CSeq timing analysis is fascinating. GTP packet counters are boring. The manual investigation spent 30 minutes on the fascinating one. The boring one had the answer.

3. **Can't parallelize.** Per-hop data plane probes are perfectly independent. A single agent runs them sequentially.

4. **Can't prune.** A single agent doesn't have a natural checkpoint where it stops and asks "should I even be doing this?" The orchestrator/sub-agent boundary creates that checkpoint.

## Why Fully Parallel Won't Work Either

If you spawn 10 agents in parallel (metrics + 4 hop probes + 4 log analyzers + config), you waste compute on log analyzers that shouldn't have run at all. Worse, they might return "SIP response path is broken" — which is technically true but not the *current* root cause. You'd have conflicting findings with no way to prioritize.

The **sequential gating** between phases prevents this. Phase 0 results determine whether Phase 1 runs. Phase 1 results determine whether Phase 2 runs. Within each phase, agents run in parallel.

---

## The Architecture

```
                    ┌─────────────────────────┐
                    │     ORCHESTRATOR         │
                    │                          │
                    │  - Investigation state   │
                    │  - Decision tree         │
                    │  - Hypothesis budget     │
                    │  - Pruning logic         │
                    │  - Final RCA synthesis   │
                    └────────┬────────────────┘
                             │
              ┌──────────────┼──────────────────┐
              │              │                   │
         Phase 0        Phase 1             Phase 2
         (ALWAYS)       (CONDITIONAL)       (CONDITIONAL)
              │              │                   │
    ┌─────────┴───┐    ┌─────┴──────┐    ┌──────┴───────┐
    │  METRICS    │    │ DATA PLANE │    │ APPLICATION  │
    │  AGENT      │    │ AGENTS     │    │ AGENTS       │
    │             │    │ (parallel) │    │ (parallel)   │
    │ - Prometheus│    │            │    │              │
    │ - Grafana   │    │ ┌────────┐ │    │ ┌──────────┐ │
    │ - Anomaly   │    │ │UE→gNB  │ │    │ │P-CSCF    │ │
    │   detection │    │ │probe   │ │    │ │log agent │ │
    │             │    │ ├────────┤ │    │ ├──────────┤ │
    │ Returns:    │    │ │gNB→UPF │ │    │ │I-CSCF    │ │
    │ structured  │    │ │probe   │ │    │ │log agent │ │
    │ health      │    │ ├────────┤ │    │ ├──────────┤ │
    │ report      │    │ │UPF→PCSCF│ │   │ │S-CSCF    │ │
    │             │    │ │probe   │ │    │ │log agent │ │
    │             │    │ ├────────┤ │    │ ├──────────┤ │
    │             │    │ │PCSCF→  │ │    │ │HSS/Diam  │ │
    │             │    │ │ICSCF   │ │    │ │log agent │ │
    │             │    │ └────────┘ │    │ └──────────┘ │
    └─────────────┘    └────────────┘    └──────────────┘
```

### Why This Shape

**The Orchestrator is the key component.** It's not just a dispatcher — it's the investigation strategist. It:

1. **Always runs the Metrics Agent first** (Phase 0). Non-negotiable. 3 seconds.
2. **Reads the metrics report and decides what to investigate.** This is the pruning step that saves 90% of the time.
3. **Dispatches Phase 1 or Phase 2 agents conditionally.** If metrics show data plane is dead, skip application agents entirely.
4. **Manages hypothesis budgets.** Each sub-agent gets N tool calls. If it can't confirm a hypothesis within budget, it returns "inconclusive" and the orchestrator re-routes.
5. **Synthesizes the final RCA** from all sub-agent findings.

**The Metrics Agent is a single, fast agent.** It doesn't need to be parallelized — it's just Prometheus queries. But it MUST run first, and its output MUST gate everything else. This is the "radiograph before biopsy" principle.

**The Data Plane Agents run in parallel, one per hop.** Each one probes a single link in the chain (UE→gNB, gNB→UPF, UPF→P-CSCF, etc.) using synthetic packets, tcpdump, and interface stats. They're independent and can run simultaneously. The orchestrator checks which hop fails and focuses investigation there.

**The Application Agents run in parallel per component, but only if needed.** Each one is a specialist for one node (P-CSCF Kamailio expert, S-CSCF Kamailio expert, HSS Diameter expert). They know what to grep for, what stats commands to run, and what the normal behavior looks like for their component. But they should NEVER be dispatched until Phase 0 and Phase 1 pass.

---

## The Critical Decision Points

The orchestrator's decision tree for the IMS 408 failure we investigated:

```
Metrics Agent returns:
  gtp_indatapktn3upf = 0
  gtp_outdatapktn3upf = 0
  upf_sessionnbr = 4
  ran_ue = 2

Orchestrator logic:
  IF gtp_in = 0 AND gtp_out = 0:
    → Data plane is dead
    → Sessions exist (4) but no traffic flowing
    → SKIP Phase 2 (application analysis)
    → RUN Phase 1 (data plane probes) to find WHERE it breaks

  Phase 1 returns:
    UE→gNB: packets enter uesimtun1 (TX=4088) but RX=20
    gNB→UPF: zero GTP-U packets at UPF
    gNB logs: "signal lost" for UEs

  Orchestrator concludes:
    → Break is at gNB (RLS layer)
    → Root cause: gNB lost simulated radio link
    → Fix: restart UERANSIM
    → Total time: ~30 seconds
```

Compare this to what actually happened: skip metrics entirely, go straight to Phase 2 SIP log analysis, spend 30+ minutes on the wrong layer.

---

## What Each Agent Looks Like

### Metrics Agent

Stateless, deterministic, always returns structured data.

```
Input:  "Run IMS health triage"

Output: {
  "data_plane": {
    "gtp_in": 0,
    "gtp_out": 0,
    "status": "DEAD"
  },
  "control_plane": {
    "sessions": 4,
    "ues": 2,
    "gnbs": 1,
    "status": "OK"
  },
  "registration": {
    "requests": 9,
    "successes": 9,
    "auth_failures": 6
  },
  "anomalies": [
    "GTP data plane zero traffic",
    "6 auth failures"
  ],
  "recommendation": "Investigate data plane first"
}
```

**Available metrics in the stack (Prometheus, port 9090):**

| Metric | What It Tells You |
|--------|-------------------|
| `fivegs_ep_n3_gtp_indatapktn3upf` | GTP data plane incoming packets at UPF |
| `fivegs_ep_n3_gtp_outdatapktn3upf` | GTP data plane outgoing packets at UPF |
| `fivegs_upffunction_upf_sessionnbr` | UPF active session count |
| `ran_ue` | RAN-connected UEs at AMF |
| `gnb` | Connected gNBs at AMF |
| `amf_session` | AMF session count |
| `ues_active` | Active UEs at SMF |
| `fivegs_amffunction_rm_reginitreq` | 5G NAS initial registration requests |
| `fivegs_amffunction_rm_reginitsucc` | 5G NAS initial registration successes |
| `fivegs_amffunction_amf_authreq` | Authentication requests |
| `fivegs_amffunction_amf_authfail` | Authentication failures |
| `fivegs_amffunction_amf_authreject` | Authentication rejections |
| `fivegs_smffunction_sm_pdusessioncreationreq` | PDU session creation requests |
| `fivegs_smffunction_sm_pdusessioncreationsucc` | PDU session creation successes |
| `fivegs_smffunction_sm_sessionnbr` | SMF active session count |

**Prometheus targets configured (scrape every 5s):**
- AMF (172.22.0.10:9091) — UP
- SMF — UP
- PCF — UP
- UPF (172.22.0.8:9091) — UP
- HSS (172.22.0.3:9091) — DOWN (4G component, no route)
- MME (172.22.0.9:9091) — DOWN (4G component, no route)
- PCRF (172.22.0.4:9091) — DOWN (4G component, no route)

Note: Kamailio IMS nodes (P-CSCF, I-CSCF, S-CSCF) are NOT currently scraped by Prometheus. They expose stats via `kamcmd` but not via HTTP /metrics. This is a gap — adding Kamailio Prometheus exporters would make the metrics agent far more powerful for IMS-specific triage.

### Data Plane Probe Agent

Per-hop, runs synthetic tests.

```
Input:  "Test UE→gNB GTP-U path for UE at 192.168.101.10"

Tools:  tcpdump, ip link stats, synthetic UDP probes, interface counters

Output: {
  "hop": "UE→gNB",
  "status": "BROKEN",
  "evidence": "TX=4088, RX=20 on uesimtun1; gNB reports signal lost",
  "confidence": "HIGH"
}
```

**Per-hop probe details:**

| Hop | How to Probe |
|-----|-------------|
| UE → gNB | `ip -s link show uesimtun1` (TX/RX counters), `docker logs nr_gnb \| grep "signal lost"` |
| gNB → UPF | `tcpdump -i any "udp port 2152"` on UPF (GTP-U), check for encapsulated traffic |
| UPF → P-CSCF | `tcpdump -i any "udp port 5060"` on P-CSCF, send synthetic SIP from `192.168.101.10` |
| P-CSCF → I-CSCF | `tcpdump -i any "udp port 4060"` on I-CSCF, or `kamcmd tm.stats` on P-CSCF |
| I-CSCF → S-CSCF | `tcpdump -i any "udp port 6060"` on S-CSCF, or `kamcmd tm.stats` on I-CSCF |
| S-CSCF → HSS | Check Diameter CDP peer state, `docker logs scscf \| grep "cdp"` |

**Key routing knowledge the probe agent needs:**
- UE traffic from `192.168.101.10` is policy-routed through `uesimtun1` (GTP tunnel), NOT directly via `eth0`
- IP rule: `from 192.168.101.10 lookup rt_uesimtun1` → `default dev uesimtun1`
- Probes MUST bind to the correct source IP to test the actual path pjsua uses

### Application Log Agent

Per-component specialist.

```
Input:  "Analyze S-CSCF REGISTER processing for recent failures"

Tools:  docker logs grep, kamcmd stats, config file reads

Output: {
  "component": "S-CSCF",
  "status": "PROCESSING_OK",
  "detail": "Auth succeeds, SAR/SAA completes in 110ms, 200 OK generated",
  "issues": [
    "Transaction suspension logs index[0] label[0] — suspicious"
  ]
}
```

**Per-component specialist knowledge:**

| Component | Stats Command | Key Log Patterns | What Normal Looks Like |
|-----------|--------------|------------------|----------------------|
| P-CSCF | `kamcmd tm.stats` | `REGISTER`, `REGISTER_reply`, `REGISTER_failure` | Transactions incrementing, rpl_received matching requests |
| I-CSCF | `kamcmd tm.stats` | `register`, `REG_UAR_REPLY`, `register_reply`, `register_failure` | UAR processing, reply route entries |
| S-CSCF | `kamcmd tm.stats` | `REGISTER`, `REG_MAR_REPLY`, `PRE_REG_SAR_REPLY` | MAR/SAR callbacks completing, 401/200 sent |
| PyHSS | HTTP API / logs | Diameter UAR/UAA, MAR/MAA, SAR/SAA | Responses with success result codes |

---

## Investigation Flow: Sequential Gates with Parallel Phases

```
Phase 0: METRICS TRIAGE (3 seconds, ALWAYS runs)
  ┌─────────────────────────────────────────────────┐
  │ Query Prometheus for:                           │
  │   - GTP packet counters (data plane alive?)     │
  │   - Session counts (control plane intact?)      │
  │   - Registration stats (auth working?)          │
  │   - Grafana time-series (when did it break?)    │
  │                                                 │
  │ Return: structured health report + anomalies    │
  └───────────────────────┬─────────────────────────┘
                          │
                    ┌─────┴─────┐
                    │ DECISION  │
                    └─────┬─────┘
                          │
            ┌─────────────┼──────────────┐
            │             │              │
     Data plane       Control plane   All healthy
     anomaly          anomaly         (rare)
            │             │              │
            ▼             ▼              ▼

Phase 1: DATA PLANE      Phase 1b:      Phase 2:
PROBES (parallel)        CONTROL PLANE  APPLICATION
                         CHECK          ANALYSIS
  ┌──────────────┐                      (parallel)
  │ UE→gNB probe │       ┌──────────┐
  │ gNB→UPF probe│       │ AMF logs │   ┌──────────┐
  │ UPF→PCSCF    │       │ SMF logs │   │ P-CSCF   │
  │ PCSCF→ICSCF  │       │ UPF logs │   │ I-CSCF   │
  │ ICSCF→SCSCF  │       └──────────┘   │ S-CSCF   │
  └──────┬───────┘                       │ HSS      │
         │                               └──────────┘
         ▼
  Identify broken hop
         │
         ▼
  Focused investigation
  of broken hop ONLY
```

### The Pruning Logic (What Saves 90% of Time)

```python
# Pseudocode for orchestrator decision logic

metrics = metrics_agent.run()

if metrics.data_plane.status == "DEAD":
    # GTP counters at zero — don't waste time on SIP logs
    probes = run_parallel([
        DataPlaneProbe("UE→gNB"),
        DataPlaneProbe("gNB→UPF"),
        DataPlaneProbe("UPF→PCSCF"),
    ])
    broken_hop = find_first_broken(probes)
    # Only investigate the broken hop, skip everything downstream
    return investigate_hop(broken_hop)

elif metrics.data_plane.status == "DEGRADED":
    # Some traffic flowing but errors — check both layers
    probes = run_parallel(data_plane_probes)
    app_agents = run_parallel(application_agents)
    return correlate(probes, app_agents)

elif metrics.control_plane.status != "OK":
    # Session setup failures — investigate control plane
    return run_parallel(control_plane_agents)

else:
    # Everything looks healthy in metrics — must be application-level
    # This is the ONLY case where SIP log analysis is warranted
    return run_parallel(application_agents)
```

---

## The One Hardcoded Rule

**The Metrics Agent always runs first. This is not configurable, not skippable, not optional.**

It's a 3-second query that determines the entire investigation path. Every other design decision is negotiable. This one isn't.

In the IMS 408 investigation:
- With metrics first: **30 seconds** to root cause (GTP = 0 → probe hops → gNB signal lost)
- Without metrics: **30+ minutes** of SIP log analysis on the wrong layer

That's a 60x speedup from a single architectural decision.

---

## Gaps to Address

### Missing Observability

The current stack has Prometheus scraping the 5G core (AMF, SMF, UPF, PCF) but NOT the IMS nodes:

| Component | Prometheus Metrics? | Stats Available Via |
|-----------|-------------------|-------------------|
| AMF | Yes (port 9091) | Prometheus |
| SMF | Yes (port 9091) | Prometheus |
| UPF | Yes (port 9091) | Prometheus |
| PCF | Yes (port 9091) | Prometheus |
| P-CSCF | **No** | `kamcmd` only |
| I-CSCF | **No** | `kamcmd` only |
| S-CSCF | **No** | `kamcmd` only |
| PyHSS | **No** | HTTP API / logs |
| gNB (UERANSIM) | **No** | Logs only |
| UE (UERANSIM) | **No** | Logs only |

**To make the Metrics Agent comprehensive, we'd need:**
1. Kamailio Prometheus exporter (`kamailio-exporter` or native `xhttp_prom`) for P-CSCF, I-CSCF, S-CSCF — exposing `tm.stats`, `sl.stats`, shared memory, dialog counts
2. UERANSIM metrics exporter — exposing RLS link status, GTP tunnel state, registration state
3. PyHSS metrics endpoint — exposing Diameter message counts, response codes

### Missing Metrics for IMS-Specific Triage

Metrics the Metrics Agent would ideally have:

| Desired Metric | Source | What It Tells You |
|---------------|--------|-------------------|
| `kamailio_tm_transactions_total` | P-CSCF, I-CSCF, S-CSCF | SIP transaction throughput |
| `kamailio_tm_replies_received` | P-CSCF, I-CSCF | Are SIP responses arriving? |
| `kamailio_tm_active_transactions` | All Kamailio nodes | Transaction buildup / leak |
| `kamailio_shm_used_bytes` | All Kamailio nodes | Memory pressure |
| `kamailio_dialog_active` | P-CSCF, S-CSCF | Active call count |
| `ueransim_rls_link_status` | gNB | Is radio link up/down? |
| `ueransim_gtp_tunnel_status` | gNB, UE | Is GTP-U tunnel active? |
| `pyhss_diameter_request_total` | PyHSS | HSS request throughput |
| `pyhss_diameter_error_total` | PyHSS | HSS errors |

With these metrics, the Metrics Agent could diagnose nearly every failure class without touching a single log file.

---

## Summary: Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Single vs multi-agent | **Multi-agent with orchestrator** | Enforces investigation discipline, enables pruning, bounded context per agent |
| Sequential vs parallel | **Sequential gates, parallel within phases** | Pruning between phases saves 90% of time; parallelism within phases saves wall-clock time |
| Where to start | **Metrics store, always** | 3-second triage determines entire investigation path |
| When to analyze logs | **Only after metrics + data plane pass** | Logs are expensive, unstructured, and seductive. They're the last resort, not the first. |
| Agent specialization | **Per-layer and per-component** | Each agent carries domain knowledge for its scope without polluting other agents' context |
| Hypothesis management | **Budgeted with kill conditions** | Each hypothesis gets N tool calls max; prevents depth-first rabbit holes |
| Context management | **Orchestrator holds summary; sub-agents hold detail** | Orchestrator sees structured findings, not raw log output; prevents context window exhaustion |
