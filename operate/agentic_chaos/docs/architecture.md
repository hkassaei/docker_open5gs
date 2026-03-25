# Agentic Chaos Monkey — Architecture

**Date:** 2026-03-18
**Version:** 1.0 (Phase 1 complete)

---

## What It Is

The Agentic Chaos Monkey is a multi-agent fault injection platform for the 5G SA + IMS Docker stack (Open5GS, Kamailio, PyHSS, UERANSIM, RTPEngine). It injects controlled failures — from killing a single container to partitioning the entire IMS signaling plane — observes the symptoms, records everything as structured training data, and optionally challenges an AI troubleshooting agent to diagnose the fault.

It's built on Google's Agent Development Kit (ADK) and runs entirely on a laptop or on Google Cloud.

---

## What It Does

### Core Use Case: Generate Failure Training Data

You can't train an autonomous network operations agent without failure data. A healthy network produces none. The chaos monkey solves this by systematically breaking the stack in controlled ways and recording what happens.

Each chaos "episode" produces a JSON file containing:
- What the network looked like before the fault (baseline metrics + container status)
- What fault was injected and how (mechanism, parameters, verification)
- What symptoms appeared (metric deltas, error logs, timing)
- How the fault was healed and how long recovery took
- The ground-truth RCA label (what actually broke and why)

These episodes are the **primary output product** — training data for telecom-specific RCA models.

### Use Case: Evaluate RCA Agents (Challenge Mode)

When Challenge Mode is enabled, the platform breaks the stack, then invokes the existing `agentic_ops` troubleshooting agent (Pydantic AI + Claude) to diagnose the failure. The RCA agent sees the symptoms but does NOT know what fault was injected. Its diagnosis is scored against ground truth across five dimensions: root cause correctness, component overlap, severity assessment, fault-type identification, and confidence calibration.

This creates a closed-loop eval framework: inject fault → observe symptoms → challenge agent → score diagnosis → record everything.

### Use Case: Discover Protocol Failure Thresholds (Adaptive Escalation)

The platform progressively increases fault severity until symptoms appear — the "Boiling Frog" pattern. For example, it injects 100ms of latency on the P-CSCF, then 250ms, then 500ms, until SIP transactions start timing out. This discovers the exact threshold at which a protocol breaks (in this case, Kamailio's T1 timer at 500ms).

The escalation data is especially valuable for training — it captures not just "fault X causes symptom Y" but "fault X at severity Z is the threshold."

### Use Case: Quick Fault Testing via CLI

```bash
# List available scenarios
python -m agentic_chaos.cli list-scenarios

# Run a scenario
python -m agentic_chaos.cli run "P-CSCF Latency"

# Emergency: heal all active faults
python -m agentic_chaos.cli heal-all
```

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                         CLI / API                                │
│                                                                  │
│   cli.py                          server.py                      │
│   run / list-scenarios            GET /api/chaos/faults          │
│   list-episodes / heal-all        (data-ready for GUI Phase 2)   │
└───────────────────────┬──────────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR LAYER                            │
│                                                                  │
│   orchestrator.py                                                │
│   run_scenario(Scenario) → Episode                               │
│                                                                  │
│   Creates an ADK SequentialAgent pipeline:                       │
│                                                                  │
│   ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────┐ ┌────┐ ┌────┐   │
│   │ Baseline │→│  Fault   │→│ Symptom  │→│Chall│→│Heal│→│Rec │   │
│   │ Collector│ │ Injector │ │ Observer │ │enge │ │  er│ │ord │   │
│   └──────────┘ └──────────┘ └──────────┘ └─────┘ └────┘ └────┘   │
│                                                                  │
│   Shared state via ADK session.state:                            │
│     baseline → faults_injected → observations → resolution       │
└───────────────────────┬──────────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────────────┐
│                      AGENT LAYER                                 │
│                                                                  │
│   agents/baseline.py          BaseAgent — no LLM                 │
│     Captures metrics + container status + stack phase            │
│                                                                  │
│   agents/fault_injector.py    BaseAgent — no LLM                 │
│     Target → Inject → Verify cycle for each FaultSpec            │
│     Dispatches to docker_tools or network_tools                  │
│     Registers every fault in SQLite BEFORE injection             │
│                                                                  │
│   agents/symptom_observer.py  LoopAgent (ADK)                    │
│     SymptomPoller: polls metrics/logs each iteration             │
│     EscalationChecker: escalates severity if no symptoms         │
│     Exits when symptoms detected or max iterations               │
│                                                                  │
│   agents/challenger.py        BaseAgent — uses external LLM      │
│     Invokes agentic_ops RCA agent (Claude) on broken stack       │
│     Scores diagnosis against ground truth                        │
│     Skipped gracefully if API key unavailable                    │
│                                                                  │
│   agents/healer.py            BaseAgent — no LLM                 │
│     Calls registry.heal_all(), captures post-heal metrics        │
│                                                                  │
│   recorder.py                 BaseAgent — no LLM                 │
│     Assembles Episode JSON, writes to episodes/ directory        │
└───────────────────────┬──────────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────────────┐
│                      TOOLS LAYER                                 │
│   Framework-agnostic async functions — no ADK dependency         │
│                                                                  │
│   tools/_common.py        shell(), validate_container(),         │
│                           validate_ip(), ALL_CONTAINERS          │
│                                                                  │
│   tools/docker_tools.py   kill, stop, pause, restart             │
│                           inspect_status, get_pid                │
│                                                                  │
│   tools/network_tools.py  inject_latency, inject_packet_loss,    │
│                           inject_corruption, inject_bandwidth,   │
│                           inject_partition (iptables)            │
│                           All via nsenter into container netns   │
│                                                                  │
│   tools/verification_tools.py                                    │
│                           verify_container_status,               │
│                           verify_latency (ping RTT),             │
│                           verify_reachable/unreachable,          │
│                           verify_tc_active/with_pid              │
│                                                                  │
│   tools/observation_tools.py                                     │
│                           snapshot_metrics (reuses               │
│                             MetricsCollector from gui/),         │
│                           snapshot_container_status,             │
│                           snapshot_logs, compute_metrics_delta,  │
│                           compute_blast_radius (reuses           │
│                             topology.impact_of from gui/)        │
│                                                                  │
│   tools/application_tools.py                                     │
│                           MongoDB subscriber ops,                │
│                           PyHSS subscriber ops,                  │
│                           config corruption (via python3)        │
└───────────────────────┬──────────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────────────┐
│                   SAFETY LAYER                                   │
│                                                                  │
│   fault_registry.py    SQLite-backed Triple Lock                 │
│                                                                  │
│   Lock 1: Intent Registry                                        │
│     Every fault registered BEFORE injection with heal_command    │
│     If injection fails → remove record, run heal                 │
│                                                                  │
│   Lock 2: TTL Reaper (background asyncio task)                   │
│     Polls every 5s for expired faults (expires_at < now)         │
│     Auto-heals and marks status='expired'                        │
│                                                                  │
│   Lock 3: Signal Handlers + atexit                               │
│     SIGINT/SIGTERM → synchronous heal-all (no asyncio needed)    │
│     atexit → synchronous heal-all                                │
│     CLI heal-all → manual escape hatch                           │
│                                                                  │
│   SQLite Schema:                                                 │
│   ┌────────────────────────────────────────────────────────────┐ │
│   │ active_faults                                              │ │
│   │   fault_id (PK), episode_id, fault_type, target,           │ │
│   │   params (JSON), mechanism, heal_command,                  │ │
│   │   injected_at, ttl_seconds, expires_at,                    │ │
│   │   status (active|healed|expired|failed),                   │ │
│   │   verified (0|1), verification_result                      │ │
│   └────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

---

## Data Flow: A Complete Episode

Here's what happens when you run `python -m agentic_chaos.cli run "DNS Failure"`:

```
1. INITIALIZE
   ├── Create FaultRegistry (SQLite)
   ├── Start TTL reaper background task
   ├── Create ADK InMemorySessionService
   ├── Seed session.state with scenario + episode_id
   └── Create ChaosDirector (SequentialAgent pipeline)

2. BASELINE COLLECTION (BaselineCollector)
   ├── snapshot_metrics()
   │     ├── Prometheus HTTP → AMF, SMF, UPF, PCF metrics
   │     ├── docker exec kamcmd → P-CSCF, I-CSCF, S-CSCF stats
   │     ├── docker exec rtpengine-ctl → RTPEngine stats
   │     ├── HTTP GET PyHSS API → IMS subscriber count
   │     └── docker exec mongosh → MongoDB subscriber count
   ├── snapshot_container_status() → 20 containers checked
   ├── determine_phase() → "ready"
   └── state["baseline"] = {timestamp, phase, status, metrics}

3. FAULT INJECTION (FaultInjector)
   ├── For each fault in scenario:
   │     ├── _dispatch_inject("container_kill", "dns")
   │     │     └── docker kill dns → success
   │     ├── Register in SQLite: fault_id, heal_cmd="docker start dns"
   │     ├── _dispatch_verify("container_kill", "dns")
   │     │     └── docker inspect dns → "exited" ✓
   │     └── mark_verified()
   └── state["faults_injected"] = [{fault_id, target, verified, ...}]

4. SYMPTOM OBSERVATION (SymptomObserver LoopAgent)
   ├── Iteration 1:
   │     ├── SymptomPoller:
   │     │     ├── snapshot_metrics() → compare to baseline
   │     │     ├── snapshot_logs() → filter for errors/timeouts
   │     │     ├── compute_metrics_delta()
   │     │     ├── _filter_notable_logs()
   │     │     └── symptoms_detected = True (error logs from pcscf, icscf, ...)
   │     └── EscalationChecker: symptoms detected → escalate → EXIT LOOP
   └── state["observations"] = [{iteration, delta, logs, symptoms}]

5. CHALLENGE MODE (ChallengeAgent) — skipped if not enabled or no API key
   ├── _build_question(observations) → "Stack is experiencing DNS failures..."
   ├── agentic_ops.create_agent().run(question)
   ├── score_diagnosis(diagnosis, injected_faults)
   └── state["challenge_result"] = {score, diagnosis, ...}

6. HEALING (Healer)
   ├── registry.heal_all() → docker start dns
   ├── snapshot_metrics() → post-heal state
   ├── recovery_time = now - injection_time
   └── state["resolution"] = {healed_at, method, post_heal_metrics, recovery_time}

7. RECORDING (EpisodeRecorder)
   ├── Assemble Episode from session.state
   ├── Build RcaLabel: {root_cause, affected_components, severity, failure_domain}
   └── Write episodes/ep_20260318_202745_dns_failure.json
```

---

## The Fault Taxonomy

```
┌───────────────────────────────────────────────────────────────────┐
│                        FAULT TYPES                                │
├──────────────┬───────────────────┬────────────────────────────────┤
│ Category     │ Type              │ Mechanism                      │
├──────────────┼───────────────────┼────────────────────────────────┤
│ CONTAINER    │ container_kill    │ docker kill (SIGKILL)          │
│              │ container_stop    │ docker stop -t N (graceful)    │
│              │ container_pause   │ docker pause (SIGSTOP/freeze)  │
│              │ container_restart │ docker restart (upgrade sim)   │
├──────────────┼───────────────────┼────────────────────────────────┤
│ NETWORK      │ network_latency   │ nsenter + tc netem delay       │
│              │ network_loss      │ nsenter + tc netem loss        │
│              │ network_corruption│ nsenter + tc netem corrupt     │
│              │ network_bandwidth │ nsenter + tc tbf rate          │
│              │ network_partition │ nsenter + iptables DROP        │
├──────────────┼───────────────────┼────────────────────────────────┤
│ APPLICATION  │ config_corruption │ docker exec python3 -c ...     │
│              │ subscriber_delete │ mongosh / PyHSS REST API       │
│              │ collection_drop   │ mongosh db.collection.drop()   │
└──────────────┴───────────────────┴────────────────────────────────┘

BLAST RADIUS:
  single_nf  → One container affected (e.g., kill pcscf)
  multi_nf   → Multiple containers affected (e.g., partition pcscf from icscf+scscf)
  global     → Entire subsystem affected (e.g., kill mongo → all 5G core queries fail)
```

All network faults use `nsenter` to enter the container's network namespace from the host. This is a "zero-touch" approach — no modifications to docker-compose files, no extra containers, no `NET_ADMIN` capability needed on the target containers. The chaos agent reaches in from the outside.

---

## The Safety Model

Orphaned faults (latency rules, iptables entries, paused containers that never get unpaused) are the #1 risk of chaos engineering in a lab environment. The platform prevents this with three independent safety mechanisms:

```
┌─────────────────────────────────────────────────────────────────┐
│                    TRIPLE LOCK SAFETY                             │
│                                                                  │
│  Lock 1: INTENT REGISTRY (SQLite)                                │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  ① Register fault (with heal_command) BEFORE injection      │ │
│  │  ② Execute inject command                                    │ │
│  │  ③ Verify injection took effect                             │ │
│  │  ④ If verify fails → heal immediately + remove record       │ │
│  │                                                              │ │
│  │  INVARIANT: A fault cannot exist in the network without     │ │
│  │  a corresponding row in active_faults with a valid          │ │
│  │  heal_command.                                              │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  Lock 2: TTL REAPER (background asyncio task)                    │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  Runs every 5 seconds:                                      │ │
│  │    SELECT * FROM active_faults                              │ │
│  │    WHERE status='active' AND expires_at < now               │ │
│  │  For each expired fault → execute heal_command              │ │
│  │                                                              │ │
│  │  GUARANTEE: No fault survives past its TTL, even if the     │ │
│  │  orchestrator hangs or the observation loop stalls.          │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  Lock 3: SIGNAL HANDLERS + ATEXIT                                │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  On SIGINT (Ctrl+C), SIGTERM, or normal process exit:       │ │
│  │    → Synchronous heal of ALL active faults (no asyncio)     │ │
│  │    → Uses raw sqlite3 + subprocess.run (not async)          │ │
│  │                                                              │ │
│  │  GUARANTEE: Even if the asyncio event loop is dead, faults  │ │
│  │  are healed. Even if the laptop loses power mid-episode,    │ │
│  │  the TTL reaper will clean up on next startup.              │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  Manual escape hatch: python -m agentic_chaos.cli heal-all       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Adaptive Escalation — The Boiling Frog

When a scenario has `escalation=True`, the SymptomObserver doesn't just poll — it progressively increases fault severity:

```
┌──────────────────────────────────────────────────────────────┐
│              ESCALATION FLOW (LoopAgent)                       │
│                                                               │
│  Iteration 1:                                                 │
│    SymptomPoller → latency 100ms → no symptoms                │
│    EscalationChecker → heal 100ms, inject 250ms               │
│                                                               │
│  Iteration 2:                                                 │
│    SymptomPoller → latency 250ms → no symptoms                │
│    EscalationChecker → heal 250ms, inject 500ms               │
│                                                               │
│  Iteration 3:                                                 │
│    SymptomPoller → latency 500ms → SIP T1 timer hit!          │
│    EscalationChecker → SYMPTOMS DETECTED → exit loop          │
│                                                               │
│  Result: "P-CSCF SIP breaks at 500ms latency because         │
│           Kamailio T1 timer defaults to 500ms"                │
└──────────────────────────────────────────────────────────────┘

ESCALATION SCHEDULES:
  network_latency:   100ms → 250ms → 500ms → 2000ms
  network_loss:      5% → 15% → 30% → 50%
  network_bandwidth: 1000kbit → 500kbit → 100kbit → 10kbit
  network_jitter:    20ms → 50ms → 100ms → 500ms
```

This generates high-value training data: not just "this fault causes that symptom" but "this is the exact severity threshold."

---

## Challenge Mode — Closed-Loop RCA Evaluation

```
┌──────────────────────────────────────────────────────────────────┐
│                  CHALLENGE MODE FLOW                             │
│                                                                  │
│  1. Chaos orchestrator injects fault                             │
│     (RCA agent does NOT see this)                                │
│                                                                  │
│  2. Symptoms appear in metrics + logs                            │
│                                                                  │
│  3. ChallengeAgent builds a diagnostic question:                 │
│     "The stack is experiencing issues. Recent error logs:        │
│      [pcscf] ERROR: tm timeout                                   │
│      [e2e_ue1] Registration failed: 408 Request Timeout          │
│      Metrics: pcscf active_transactions 0→3"                     │
│                                                                  │
│  4. agentic_ops RCA agent investigates:                          │
│     → read_container_logs, get_network_status, query_subscriber  │
│     → Produces Diagnosis: "P-CSCF network latency..."            │
│                                                                  │
│  5. Scorer compares diagnosis to ground truth:                   │
│     ┌──────────────────────────┬──────────┬────────┐             │
│     │ Dimension                │ Weight   │ Score  │             │
│     ├──────────────────────────┼──────────┼────────┤             │
│     │ Root cause correct?      │ 40%      │ 1.0    │             │
│     │ Component overlap        │ 25%      │ 0.67   │             │
│     │ Severity correct?        │ 15%      │ 1.0    │             │
│     │ Fault type identified?   │ 10%      │ 1.0    │             │
│     │ Confidence calibrated?   │ 10%      │ 1.0    │             │
│     ├──────────────────────────┼──────────┼────────┤             │
│     │ TOTAL                    │          │ 87%    │             │
│     └──────────────────────────┴──────────┴────────┘             │
│                                                                  │
│  6. Score + diagnosis recorded in episode JSON                   │
└──────────────────────────────────────────────────────────────────┘
```

Requires `ANTHROPIC_API_KEY` for the Claude-based RCA agent. Skipped gracefully if unavailable.

---

## Integration Points

The chaos platform doesn't operate in isolation — it reuses and integrates with the existing `operate/` infrastructure:

```
┌──────────────────────────────────────────────────────────────────┐
│                     EXISTING INFRASTRUCTURE                      │
│                                                                  │
│  operate/gui/metrics.py                                          │
│    MetricsCollector — Prometheus + kamcmd + PyHSS + MongoDB      │
│    ← Reused by observation_tools.snapshot_metrics()              │
│                                                                  │
│  operate/gui/topology.py                                         │
│    NetworkTopology.impact_of() — compute blast radius            │
│    ← Reused by observation_tools.compute_blast_radius()          │
│                                                                  │
│  operate/gui/server.py                                           │
│    GET /api/chaos/faults — active faults endpoint                │
│    ← Data-ready for Phase 2 GUI "Break This" button              │
│                                                                  │
│  operate/agentic_ops/                                            │
│    Pydantic AI troubleshooting agent (Claude)                    │
│    ← Invoked by ChallengeAgent for blind RCA diagnosis           │
│                                                                  │
│  .env + operate/e2e.env                                          │
│    Container IPs, subscriber credentials, network config         │
│    ← Loaded by observation_tools._load_env()                     │
└──────────────────────────────────────────────────────────────────┘
```

---

## The 10 Pre-Built Scenarios

| # | Name | Category | Blast | Target(s) | What Breaks |
|---|---|---|---|---|---|
| 1 | gNB Radio Link Failure | container | single | nr_gnb | UEs lose radio, PDU sessions drop |
| 2 | P-CSCF Latency | network | single | pcscf | SIP T1 timeouts, IMS registration fails |
| 3 | S-CSCF Crash | container | single | scscf | IMS auth stops, no new registrations |
| 4 | HSS Unresponsive | container | single | pyhss | Diameter timeouts, subscriber resolution fails |
| 5 | Data Plane Degradation | network | single | upf | RTP packet loss, voice quality drops |
| 6 | MongoDB Gone | container | global | mongo | 5G core loses subscriber store |
| 7 | DNS Failure | container | global | dns | IMS domain unresolvable |
| 8 | IMS Network Partition | network | multi | pcscf↔icscf,scscf | SIP signaling severed |
| 9 | AMF Restart | container | multi | amf | UEs deregistered, must re-attach |
| 10 | Cascading IMS Failure | compound | multi | pyhss + scscf | Total IMS outage |

Scenarios 2 (P-CSCF Latency) has `escalation=True` — it uses adaptive escalation.
Scenario 10 (Cascading IMS Failure) has `challenge_mode=True` — it invokes the RCA agent.

---

## Episode Schema

The episode JSON is the primary output product. It follows schema version 1.0:

```
Episode
├── schema_version: "1.0"
├── episode_id: "ep_20260318_143022_pcscf_latency"
├── timestamp: ISO 8601
├── duration_seconds: float
│
├── scenario
│   ├── name, description, category, blast_radius
│   ├── faults: [FaultSpec...]
│   ├── expected_symptoms: [str...]
│   ├── escalation: bool
│   └── challenge_mode: bool
│
├── baseline
│   ├── timestamp
│   ├── stack_phase: "ready" | "partial" | "down"
│   ├── container_status: {container → status}
│   └── metrics: {node → {metric → value}}
│
├── faults: [Fault...]
│   ├── fault_id, fault_type, target, params
│   ├── mechanism (exact command)
│   ├── heal_command
│   ├── injected_at, ttl_seconds, expires_at
│   ├── verified: bool
│   └── verification_result
│
├── observations: [Observation...]
│   ├── iteration, timestamp, elapsed_seconds
│   ├── metrics_delta: {node → {metric → {baseline, current, delta}}}
│   ├── log_samples: {container → [lines]}
│   ├── symptoms_detected: bool
│   └── escalation_level: int
│
├── resolution
│   ├── healed_at, heal_method
│   ├── post_heal_metrics
│   └── recovery_time_seconds
│
├── rca_label (ground truth)
│   ├── root_cause
│   ├── affected_components
│   ├── severity: "healthy" | "degraded" | "down"
│   ├── failure_domain: "ims_signaling" | "data_plane" | "core_control_plane" | ...
│   └── protocol_impact: "SIP" | "Diameter" | "GTP-U" | ...
│
└── challenge_result (optional, if challenge_mode=True)
    ├── rca_agent_model
    ├── diagnosis_summary, diagnosis_root_cause
    ├── score
    │   ├── root_cause_correct: bool
    │   ├── component_overlap: float (Jaccard)
    │   ├── severity_correct: bool
    │   ├── confidence_calibrated: bool
    │   └── total_score: float (0.0-1.0)
    └── time_to_diagnosis_seconds
```

---

## File Map

```
operate/agentic_chaos/
├── __init__.py              # Package version
├── __main__.py              # python -m entry point
├── cli.py                   # CLI: run, list-scenarios, list-episodes, show, heal-all
├── models.py                # 12 Pydantic models + escalation schedules
├── fault_registry.py        # SQLite Triple Lock (registry + TTL reaper + signal handlers)
├── orchestrator.py          # ChaosDirector SequentialAgent + run_scenario()
├── recorder.py              # EpisodeRecorder BaseAgent → writes episode JSON
├── scorer.py                # Challenge Mode scoring (5 dimensions, weighted)
├── requirements.txt         # google-adk, aiosqlite, pydantic
│
├── agents/
│   ├── baseline.py          # BaselineCollector — metrics + status snapshot
│   ├── fault_injector.py    # FaultInjector — Target → Inject → Verify
│   ├── symptom_observer.py  # SymptomPoller + LoopAgent factory
│   ├── escalation.py        # EscalationChecker — Boiling Frog
│   ├── challenger.py        # ChallengeAgent — invoke RCA agent + score
│   └── healer.py            # Healer — reverse all faults
│
├── tools/
│   ├── _common.py           # shell(), validate_container(), validate_ip(), constants
│   ├── docker_tools.py      # kill, stop, pause, restart, inspect, get_pid
│   ├── network_tools.py     # latency, loss, corruption, bandwidth, partition (nsenter)
│   ├── verification_tools.py# ping probes, tc checks, container status
│   ├── observation_tools.py # metrics snapshot, log capture, delta, blast radius
│   └── application_tools.py # MongoDB/PyHSS subscriber ops, config corruption
│
├── scenarios/
│   └── library.py           # 10 pre-built scenarios
│
├── episodes/                # Output: recorded episode JSON files
│
├── tests/                   # 171 tests across 12 test files
│   ├── test_models.py       # Pydantic models, enums, serialization
│   ├── test_fault_registry.py # SQLite CRUD, TTL, emergency heal
│   ├── test_functional.py   # Live stack: docker, network, verification, observation
│   ├── test_agents_functional.py # Full e2e via ADK orchestrator
│   ├── test_scenarios.py    # Scenario library validation
│   ├── test_cli.py          # CLI parser and commands
│   ├── test_scorer.py       # Scoring logic + severity inference
│   ├── test_escalation.py   # Escalation schedules + decision logic
│   ├── test_symptom_filter.py # Log keyword filtering
│   ├── test_observation_tools.py # Metrics delta, phase detection
│   ├── test_verification_tools.py # Ping RTT parser
│   └── test_application_tools.py # IMSI validation, config corruption
│
└── docs/
    ├── architecture.md      # This document
    ├── plan-final.md        # Implementation plan
    ├── plan-review.md       # Initial plan review
    └── plan-review-feedback.md # Feedback on plan
```

---

## Design Decisions

| Decision | Choice | Why |
|---|---|---|
| ADK for orchestration | SequentialAgent + LoopAgent | Clean pipeline model, shared state via session, built-in loop/escalate primitives |
| No LLM in core pipeline | BaseAgent for 5 of 6 agents | Deterministic execution, no API latency, works without Gemini key for most scenarios |
| nsenter for network faults | Enter container netns from host | Zero-touch: no compose changes, no NET_ADMIN on containers, surgical |
| SQLite for fault registry | WAL mode, single-file DB | No external dependencies, survives process restart, concurrent read-safe |
| Tools are framework-agnostic | Plain async functions, no ADK imports | Reusable from ADK, Pydantic AI, CLI, or scripts |
| Episode as primary output | JSON per episode, one file | Self-contained training datum, easy to browse/filter/load |
| Pydantic AI for RCA agent | Separate from ADK chaos agents | Two independent subsystems, different LLM providers, shared tool patterns |
| Shared shell() helper | Single implementation in _common.py | DRY, timeout in one place, validation in one place |
| Input validation at tool boundary | validate_container(), validate_ip(), param ranges | Defense-in-depth: safe even if called with LLM-generated inputs |

---

## What's Next

### Phase 2: GUI Integration
- "Break This" button on topology nodes → calls chaos CLI
- Fault timeline overlay on topology view
- Blast radius preview before injection (using `topology.impact_of()`)
- Active faults display (using `GET /api/chaos/faults`)

### Phase 3: Autonomous Platform
- Scheduled chaos campaigns (sequence of escalating scenarios)
- Auto-remediation agent (heal + fix root cause)
- Fine-tuned telecom RCA model trained on episode data
- Continuous eval: chaos → diagnose → score → retrain loop

