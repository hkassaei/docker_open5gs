# Agentic Chaos Monkey — Final Implementation Plan

**Date:** 2026-03-18
**Mode:** EXPANSION
**Decisions by:** Hossein + Gemini (Senior Engineer review) + Claude (Plan review)

---

## Table of Contents

1. [Vision & Outcome](#1-vision--outcome)
2. [Decided Design Parameters](#2-decided-design-parameters)
3. [System Architecture](#3-system-architecture)
4. [ADK Agent Hierarchy](#4-adk-agent-hierarchy)
5. [Fault Injection Primitives](#5-fault-injection-primitives)
6. [The Triple Lock — Fault Safety System](#6-the-triple-lock--fault-safety-system)
7. [Episode Recording System](#7-episode-recording-system)
8. [Challenge Mode — Closed-Loop Eval](#8-challenge-mode--closed-loop-eval)
9. [Adaptive Escalation — The Boiling Frog](#9-adaptive-escalation--the-boiling-frog)
10. [Directory Structure & File Manifest](#10-directory-structure--file-manifest)
11. [Tool Specifications](#11-tool-specifications)
12. [Scenario Library](#12-scenario-library)
13. [Implementation Phases](#13-implementation-phases)
14. [Reuse Map](#14-reuse-map)
15. [GCP Deployment Path](#15-gcp-deployment-path)
16. [Not In Scope](#16-not-in-scope)
17. [Risk Register](#17-risk-register)
18. [Sources](#18-sources)

---

## 1. Vision & Outcome

**Near-term deliverable:** A multi-agent chaos engineering platform that injects controlled failures into the 5G SA + IMS stack and records structured episodes.

**Primary output product:** Episode JSON files — each one a complete `(scenario, baseline, faults, symptoms, resolution, rca_label)` tuple usable as training/eval data for an autonomous RCA agent.

**12-month trajectory:**

```
Phase 1 (this plan)        Phase 2 (next)              Phase 3 (12-month)
─────────────────────      ─────────────────────       ─────────────────────
ADK chaos orchestrator     GUI "Break This" button     Autonomous chaos campaigns
Episode recording (JSON)   Fault timeline overlay      Scheduled chaos runs
CLI-driven scenarios       Blast radius preview        Auto-remediation agent
Challenge Mode (eval)      Campaign runner             Fine-tuned telecom RCA model
Laptop + GCP ready         Episode browser in GUI      Continuous eval pipeline
```

---

## 2. Decided Design Parameters

| Decision | Choice | Rationale |
|---|---|---|
| **Review mode** | EXPANSION | The value is dataset generation, not just fault injection |
| **Orchestrator model** | `gemini-3.1-flash-lite-preview` | Sub-100ms latency for high-frequency state polling |
| **Specialist model** | `gemini-3.1-pro-preview` | System-2 reasoning for protocol-aware fault design |
| **Network faults** | `nsenter` from host | Zero-touch, no compose changes, surgical |
| **Fault safety** | Registry + TTL + Signal Handlers (Triple Lock) | Orphaned faults are unacceptable |
| **Fault registry** | SQLite (`state.db`) | Persistent, queryable, shared across processes |
| **GUI integration** | Phase 2 (CLI first, data-ready from day 1) | Design `faults` overlay in topology API now, build UI later |
| **Episode recording** | Must-have for v1 | The primary deliverable — without it, this is a fancy shell script |
| **Agent framework** | ADK for chaos, Pydantic AI stays for troubleshooting | Independent subsystems, shared tool implementations |
| **Semantic verification** | Target → Inject → Verify on every fault | Injection without verification is a silent failure |
| **Adaptive escalation** | LoopAgent with escalating parameters | Static faults may not trigger symptoms if timers are high |

---

## 3. System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        CHAOS PLATFORM                                   │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    ADK ORCHESTRATOR                                │  │
│  │              (SequentialAgent: "ChaosDirector")                    │  │
│  │                                                                   │  │
│  │  Phase 1         Phase 2           Phase 3          Phase 4       │  │
│  │  ┌──────────┐   ┌──────────────┐  ┌──────────────┐ ┌──────────┐  │  │
│  │  │ Baseline │──>│ Fault        │─>│ Symptom      │─>│ Healer + │  │  │
│  │  │ Collector│   │ Injector     │  │ Observer     │  │ Recorder │  │  │
│  │  │          │   │              │  │              │  │          │  │  │
│  │  │ Metrics  │   │ Target       │  │ Poll metrics │  │ Heal all │  │  │
│  │  │ snapshot │   │ Inject       │  │ Collect logs │  │ faults   │  │  │
│  │  │ Health   │   │ Verify  <────│──│ Escalate if  │  │ Record   │  │  │
│  │  │ check    │   │ (per fault)  │  │ no symptoms  │  │ episode  │  │  │
│  │  └──────────┘   └──────────────┘  └──────────────┘  └──────────┘  │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────┐  │
│  │  FAULT REGISTRY   │  │  EPISODE STORE    │  │  SCENARIO LIBRARY    │  │
│  │  (SQLite)         │  │  (JSON files)     │  │  (Python defs)       │  │
│  │                   │  │                   │  │                      │  │
│  │  Active faults    │  │  episodes/        │  │  Pre-built scenarios │  │
│  │  TTL tracking     │  │    ep_20260318_   │  │  Custom scenarios    │  │
│  │  Heal-on-exit     │  │    ...json        │  │  from LLM            │  │
│  └──────────────────┘  └──────────────────┘  └──────────────────────┘  │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                    SPECIALIST AGENTS                              │   │
│  │                                                                  │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │   │
│  │  │ Container    │  │ Network      │  │ Application          │   │   │
│  │  │ Agent        │  │ Agent        │  │ Agent                │   │   │
│  │  │              │  │              │  │                      │   │   │
│  │  │ kill/stop/   │  │ latency/     │  │ config corruption/   │   │   │
│  │  │ pause/       │  │ loss/jitter/ │  │ DB faults/           │   │   │
│  │  │ restart      │  │ partition/   │  │ subscriber deletion  │   │   │
│  │  │              │  │ bandwidth    │  │                      │   │   │
│  │  │ Verify:      │  │ Verify:      │  │ Verify:              │   │   │
│  │  │ docker ps    │  │ ping/curl    │  │ config read/DB query │   │   │
│  │  └──────────────┘  └──────────────┘  └──────────────────────┘   │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │              SHARED INFRASTRUCTURE (reused from existing code)    │   │
│  │                                                                  │   │
│  │  topology.py          metrics.py           agentic_ops/tools.py  │   │
│  │  impact_of()          MetricsCollector      read_container_logs   │   │
│  │  path_between()       collect()             search_logs           │   │
│  │  neighbors()          (Prom+kamcmd+API)     get_network_status    │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

### Data Flow — All Four Paths

```
HAPPY PATH:
  Scenario ──> Baseline snapshot ──> Inject faults ──> Verify injection ──>
  ──> Observe symptoms ──> Heal faults ──> Post-heal check ──> Record episode

NIL PATH (no scenario provided):
  CLI with no args ──> List available scenarios ──> User selects ──> proceed

EMPTY PATH (stack not ready):
  Baseline collector finds containers down ──> Abort with clear error:
  "Cannot run chaos: stack phase is 'down'. Run deploy first."

ERROR PATH (fault injection fails):
  Inject returns non-zero ──> Verify step catches it ──> Fault NOT added to
  registry ──> Orchestrator logs warning ──> Decides: retry, skip, or abort
  ──> Any already-injected faults are healed before exit
```

---

## 4. ADK Agent Hierarchy

### 4.1 Top-Level: ChaosDirector (SequentialAgent)

The outer shell. Runs phases in strict order. No LLM needed — pure orchestration.

```python
from google.adk.agents import SequentialAgent

chaos_director = SequentialAgent(
    name="ChaosDirector",
    description="Runs a complete chaos episode: baseline → inject → observe → heal → record.",
    sub_agents=[
        baseline_collector,    # Phase 1
        fault_injector,        # Phase 2
        symptom_observer,      # Phase 3
        healer_recorder,       # Phase 4
    ],
)
```

### 4.2 Phase 1: BaselineCollector (Custom BaseAgent)

Deterministic — no LLM. Calls MetricsCollector, captures container statuses, saves to `session.state["baseline"]`.

```python
# Pseudocode
class BaselineCollector(BaseAgent):
    async def _run_async_impl(self, ctx):
        metrics = await MetricsCollector(env).collect()
        statuses = await get_network_status(deps)
        ctx.session.state["baseline"] = {
            "timestamp": now_iso(),
            "metrics": metrics,
            "statuses": json.loads(statuses),
            "phase": determine_phase(statuses),
        }
        yield Event(author=self.name, content=f"Baseline captured: {len(metrics)} NFs")
```

### 4.3 Phase 2: FaultInjector (LlmAgent or SequentialAgent)

For pre-built scenarios: a `SequentialAgent` that iterates the fault list deterministically.
For LLM-designed scenarios: an `LlmAgent` that reads the scenario description and decides which specialist to invoke.

Each specialist follows the **Target → Inject → Verify** pattern:

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│  TARGET   │────>│  INJECT  │────>│  VERIFY  │
│           │     │          │     │          │
│ Resolve   │     │ Execute  │     │ Confirm  │
│ container │     │ fault    │     │ effect   │
│ name, IP, │     │ command  │     │ achieved │
│ netns PID │     │ via tool │     │ via probe│
└──────────┘     └──────────┘     └──────────┘
                                       │
                              ┌────────┴────────┐
                              │                 │
                          VERIFIED           FAILED
                              │                 │
                         Register in        Log warning,
                         fault_registry     retry or abort
```

### 4.4 Phase 3: SymptomObserver (LoopAgent — Adaptive Escalation)

Polls metrics and logs at intervals. Implements the **Boiling Frog** pattern:

```python
from google.adk.agents import LoopAgent

symptom_observer = LoopAgent(
    name="SymptomObserver",
    description="Polls for symptoms. Escalates fault severity if no change detected.",
    max_iterations=10,  # Max 10 poll cycles (e.g., 10 × 5s = 50s observation window)
    sub_agents=[
        symptom_collector,   # Capture current metrics + logs
        symptom_evaluator,   # LlmAgent: compare to baseline, detect anomalies
        escalation_checker,  # Escalate or signal done
    ],
)
```

The `escalation_checker` reads `state["symptoms_detected"]`:
- If `True` → `yield Event(actions=EventActions(escalate=True))` → exit loop
- If `False` and iterations remain → write `state["escalation_level"] += 1` → next cycle tightens the fault parameters
- If max iterations reached → record "no symptoms detected at max severity"

### 4.5 Phase 4: HealerRecorder (SequentialAgent)

1. **Healer**: Reads active faults from registry, reverses each one, verifies healing
2. **PostHealCollector**: Captures post-heal metrics snapshot
3. **EpisodeRecorder**: Assembles full episode from `session.state` and writes JSON

```python
healer_recorder = SequentialAgent(
    name="HealerRecorder",
    sub_agents=[healer, post_heal_collector, episode_recorder],
)
```

### 4.6 Specialist Agents (invoked by FaultInjector)

Each is a focused `LlmAgent` with domain-specific tools:

| Agent | Model | Tools | Verification |
|---|---|---|---|
| `ContainerAgent` | `gemini-3.1-flash-lite-preview` | `docker_kill`, `docker_stop`, `docker_pause`, `docker_restart` | `docker inspect` status check |
| `NetworkAgent` | `gemini-3.1-pro-preview` | `inject_latency`, `inject_loss`, `inject_partition`, `inject_bandwidth_limit` | `ping` or `curl` timing probe |
| `ApplicationAgent` | `gemini-3.1-pro-preview` | `corrupt_config`, `delete_subscriber`, `wipe_collection` | Config read-back or DB query |

---

## 5. Fault Injection Primitives

### 5.1 Container Faults

All via standard Docker CLI. No special privileges needed.

```
docker kill <container>                    # SIGKILL — immediate death
docker stop -t 0 <container>              # SIGTERM then SIGKILL
docker pause <container>                   # SIGSTOP — freeze in place
docker unpause <container>                 # SIGCONT — thaw
docker restart <container>                 # Stop + start
```

**Verification**: `docker inspect -f '{{.State.Status}}' <container>` → expect `exited`/`paused`/`running`

### 5.2 Network Faults (via nsenter)

All use `nsenter` into the container's network namespace from the host:

```bash
# Get the container's PID
PID=$(docker inspect -f '{{.State.Pid}}' <container>)

# Inject 500ms latency with 50ms jitter
nsenter -t $PID -n tc qdisc add dev eth0 root netem delay 500ms 50ms

# Inject 30% packet loss
nsenter -t $PID -n tc qdisc add dev eth0 root netem loss 30%

# Inject 1% packet corruption
nsenter -t $PID -n tc qdisc add dev eth0 root netem corrupt 1%

# Bandwidth limit to 100kbit
nsenter -t $PID -n tc qdisc add dev eth0 root tbf rate 100kbit burst 32kbit latency 400ms

# Network partition (drop all traffic to a specific IP)
nsenter -t $PID -n iptables -A OUTPUT -d <target_ip> -j DROP
nsenter -t $PID -n iptables -A INPUT -s <target_ip> -j DROP

# Heal: remove all tc rules
nsenter -t $PID -n tc qdisc del dev eth0 root

# Heal: remove iptables rules
nsenter -t $PID -n iptables -D OUTPUT -d <target_ip> -j DROP
nsenter -t $PID -n iptables -D INPUT -s <target_ip> -j DROP
```

**Verification examples**:
- Latency: `nsenter -t $PID -n ping -c 1 -W 2 <target_ip>` → check RTT > injected delay
- Packet loss: `nsenter -t $PID -n tc -s qdisc show dev eth0` → confirm netem active
- Partition: `nsenter -t $PID -n ping -c 1 -W 2 <target_ip>` → expect 100% loss

### 5.3 Application Faults

```bash
# Config corruption: change a value in a running container's config
docker exec <container> sed -i 's/old_value/corrupted_value/' /path/to/config
docker restart <container>

# Subscriber deletion from MongoDB (5G core)
docker exec mongo mongosh --quiet --eval \
  "db.subscribers.deleteOne({imsi: '<imsi>'})" open5gs

# Subscriber deletion from PyHSS (IMS)
curl -X DELETE http://<pyhss_ip>:8080/ims_subscriber/<subscriber_id>

# Database collection drop (extreme)
docker exec mongo mongosh --quiet --eval "db.subscribers.drop()" open5gs
```

**Verification**: Read back the config or query the DB to confirm the change took effect.

---

## 6. The Triple Lock — Fault Safety System

### Lock 1: Fault Registry (SQLite)

Every injected fault is recorded in `operate/agentic_chaos/state.db`:

```sql
CREATE TABLE active_faults (
    fault_id     TEXT PRIMARY KEY,
    episode_id   TEXT NOT NULL,
    fault_type   TEXT NOT NULL,       -- 'container_kill', 'network_latency', etc.
    target       TEXT NOT NULL,       -- container name
    params       TEXT NOT NULL,       -- JSON: {"delay_ms": 500, "jitter_ms": 50}
    mechanism    TEXT NOT NULL,       -- exact command used to inject
    heal_command TEXT NOT NULL,       -- exact command to reverse
    injected_at  TEXT NOT NULL,       -- ISO timestamp
    ttl_seconds  INTEGER NOT NULL,    -- max lifetime
    expires_at   TEXT NOT NULL,       -- injected_at + ttl_seconds
    status       TEXT DEFAULT 'active' -- 'active', 'healed', 'expired'
);
```

This table is the **shared truth** — the GUI, the troubleshooting agent, and the chaos orchestrator can all query it.

### Lock 2: TTL Expiry

A background `asyncio.Task` polls `active_faults WHERE status = 'active' AND expires_at < now()` every 5 seconds. Any expired fault is healed automatically and marked `status = 'expired'`.

```python
async def _ttl_reaper(db_path: str):
    """Background task: heal any fault that has exceeded its TTL."""
    while True:
        await asyncio.sleep(5)
        expired = query_expired_faults(db_path)
        for fault in expired:
            await _shell(fault.heal_command)
            mark_healed(db_path, fault.fault_id, method="ttl_expired")
```

### Lock 3: Signal Handlers + atexit

On `SIGINT`, `SIGTERM`, or process exit, heal ALL active faults:

```python
import atexit, signal

def _emergency_heal_all():
    """Synchronous cleanup: heal every active fault in the registry."""
    faults = query_all_active_faults(DB_PATH)
    for fault in faults:
        subprocess.run(fault.heal_command, shell=True, timeout=5)
        mark_healed(DB_PATH, fault.fault_id, method="emergency_shutdown")

atexit.register(_emergency_heal_all)
signal.signal(signal.SIGINT, lambda *_: (emergency_heal_all(), sys.exit(1)))
signal.signal(signal.SIGTERM, lambda *_: (emergency_heal_all(), sys.exit(1)))
```

### Safety Invariant

**At no point can a fault exist in the network without a corresponding row in `active_faults` with a valid `heal_command` and `expires_at`.** The inject tool writes the registry row BEFORE executing the inject command. If injection fails, the row is deleted. If injection succeeds but verification fails, the heal command is run immediately and the row is deleted.

---

## 7. Episode Recording System

### 7.1 Episode Schema (v1)

```json
{
  "schema_version": "1.0",
  "episode_id": "ep_20260318_143022_pcscf_latency",
  "timestamp": "2026-03-18T14:30:22Z",
  "duration_seconds": 63,

  "scenario": {
    "name": "P-CSCF Network Latency",
    "description": "Inject 500ms latency on P-CSCF to simulate WAN degradation",
    "category": "network",
    "blast_radius": "single_nf",
    "target_nodes": ["pcscf"],
    "affected_edges": ["e2e_ue1->pcscf", "e2e_ue2->pcscf", "pcscf->icscf", "pcscf->scscf"],
    "expected_symptoms": ["SIP transaction timeouts", "IMS registration delays"]
  },

  "baseline": {
    "timestamp": "2026-03-18T14:30:22Z",
    "stack_phase": "ready",
    "container_status": {
      "amf": "running", "smf": "running", "pcscf": "running"
    },
    "metrics": {
      "amf": {"ran_ue": 2, "amf_session": 2},
      "smf": {"fivegs_smffunction_sm_sessionnbr": 4},
      "pcscf": {"ims_usrloc_pcscf:registered_contacts": 2, "tmx:active_transactions": 0}
    }
  },

  "faults": [
    {
      "fault_id": "f_001",
      "type": "network_latency",
      "target": "pcscf",
      "params": {"delay_ms": 500, "jitter_ms": 50},
      "mechanism": "nsenter -t 12345 -n tc qdisc add dev eth0 root netem delay 500ms 50ms",
      "heal_command": "nsenter -t 12345 -n tc qdisc del dev eth0 root",
      "injected_at": "2026-03-18T14:30:25Z",
      "verified": true,
      "verification_result": "ping RTT 523ms (expected >500ms)"
    }
  ],

  "observations": [
    {
      "iteration": 1,
      "timestamp": "2026-03-18T14:30:30Z",
      "elapsed_seconds": 5,
      "metrics_delta": {
        "pcscf": {"tmx:active_transactions": {"baseline": 0, "current": 3, "delta": 3}}
      },
      "log_samples": {
        "pcscf": ["WARNING: transaction timeout for REGISTER"],
        "e2e_ue1": ["Registration failed: 408 Request Timeout"]
      },
      "symptoms_detected": true,
      "escalation_level": 0
    }
  ],

  "resolution": {
    "healed_at": "2026-03-18T14:31:25Z",
    "heal_method": "scheduled",
    "post_heal_metrics": {
      "pcscf": {"tmx:active_transactions": 0}
    },
    "recovery_time_seconds": 12
  },

  "rca_label": {
    "root_cause": "P-CSCF network latency (500ms) causing SIP REGISTER transaction timeouts (T1 timer = 500ms)",
    "affected_components": ["pcscf", "icscf", "scscf", "e2e_ue1", "e2e_ue2"],
    "severity": "degraded",
    "failure_domain": "ims_registration",
    "protocol_impact": "SIP"
  },

  "challenge_mode": null
}
```

### 7.2 Storage

Episodes are written as individual JSON files to `operate/agentic_chaos/episodes/`:

```
operate/agentic_chaos/episodes/
├── ep_20260318_143022_pcscf_latency.json
├── ep_20260318_150105_amf_kill.json
├── ep_20260318_152330_split_brain_ims.json
└── ...
```

One file per episode. Filename encodes timestamp + scenario name for easy browsing.

---

## 8. Challenge Mode — Closed-Loop Eval

When enabled, the orchestrator adds a Phase 3.5 between symptom observation and healing:

```
Phase 1: Baseline → Phase 2: Inject → Phase 3: Observe
                                                  │
                                          ┌───────┴───────┐
                                          │ Phase 3.5:    │
                                          │ CHALLENGE     │
                                          │               │
                                          │ Invoke the    │
                                          │ agentic_ops   │
                                          │ troubleshoot  │
                                          │ agent as a    │
                                          │ subprocess.   │
                                          │               │
                                          │ Agent sees    │
                                          │ symptoms but  │
                                          │ does NOT know │
                                          │ what fault    │
                                          │ was injected. │
                                          │               │
                                          │ Returns a     │
                                          │ Diagnosis.    │
                                          └───────┬───────┘
                                                  │
                                          Phase 4: Heal + Record
                                                  │
                                          Score the Diagnosis
                                          against known fault
```

### Scoring Rubric

```python
def score_diagnosis(diagnosis: Diagnosis, injected_faults: list[Fault]) -> dict:
    """Score the RCA agent's diagnosis against the known injected faults."""
    score = {
        "root_cause_correct": False,    # Did it identify the right component?
        "component_overlap": 0.0,       # Jaccard similarity of affected components
        "severity_correct": False,      # Did it get the severity right?
        "confidence_calibrated": False,  # High confidence + correct = good
        "time_to_diagnosis_seconds": 0,
    }
    # ... scoring logic ...
    return score
```

The score is appended to the episode JSON under the `challenge_mode` key:

```json
"challenge_mode": {
  "rca_agent_model": "anthropic:claude-sonnet-4-20250514",
  "diagnosis": { ... },
  "score": {
    "root_cause_correct": true,
    "component_overlap": 0.8,
    "severity_correct": true,
    "time_to_diagnosis_seconds": 14
  }
}
```

---

## 9. Adaptive Escalation — The Boiling Frog

When the SymptomObserver loop doesn't detect symptoms, it escalates:

```
Iteration 1: delay 100ms  → metrics unchanged  → no symptoms
Iteration 2: delay 250ms  → metrics unchanged  → no symptoms
Iteration 3: delay 500ms  → SIP T1 timer hit   → SYMPTOMS DETECTED → exit loop
```

Escalation schedule per fault type:

| Fault Type | Level 0 | Level 1 | Level 2 | Level 3 (max) |
|---|---|---|---|---|
| Latency | 100ms | 250ms | 500ms | 2000ms |
| Packet loss | 5% | 15% | 30% | 50% |
| Bandwidth | 1Mbit | 500kbit | 100kbit | 10kbit |
| Jitter | 20ms | 50ms | 100ms | 500ms |

The escalation requires **healing the previous level and injecting the new one** (you can't stack tc rules naively). The FaultInjector's heal + re-inject is atomic from the SymptomObserver's perspective.

This generates high-value data: **the exact threshold at which a protocol breaks**. For example: "SIP REGISTER starts failing at 500ms latency on P-CSCF because Kamailio's T1 timer defaults to 500ms." This is the kind of insight that trains a good RCA model.

---

## 10. Directory Structure & File Manifest

```
operate/agentic_chaos/
├── __init__.py                  # Package init, version
├── orchestrator.py              # ChaosDirector SequentialAgent + sub-agents
├── agents/
│   ├── __init__.py
│   ├── baseline.py              # BaselineCollector (BaseAgent, no LLM)
│   ├── container_agent.py       # ContainerAgent (LlmAgent) — kill/stop/pause/restart
│   ├── network_agent.py         # NetworkAgent (LlmAgent) — tc/netem/iptables
│   ├── application_agent.py     # ApplicationAgent (LlmAgent) — config/DB faults
│   ├── symptom_observer.py      # SymptomObserver (LoopAgent) + evaluator + escalation
│   └── healer.py                # Healer (BaseAgent) — reverses all active faults
├── tools/
│   ├── __init__.py
│   ├── docker_tools.py          # Container lifecycle: kill, stop, pause, restart, inspect
│   ├── network_tools.py         # nsenter + tc qdisc, iptables, ping/curl probes
│   ├── application_tools.py     # Config sed, mongosh, PyHSS API
│   ├── observation_tools.py     # Metrics snapshot (reuse MetricsCollector), log capture
│   └── verification_tools.py    # Probe tools: ping, curl, docker inspect, config readback
├── models.py                    # Pydantic models: FaultSpec, Episode, Baseline, Observation, etc.
├── fault_registry.py            # SQLite CRUD for active_faults + TTL reaper task
├── recorder.py                  # Assemble Episode from session.state, write JSON
├── scorer.py                    # Challenge Mode scoring logic
├── scenarios/
│   ├── __init__.py
│   └── library.py               # Pre-built scenario definitions
├── prompts/
│   ├── orchestrator.md          # System prompt for ChaosDirector (if LlmAgent mode)
│   ├── network_agent.md         # System prompt for NetworkAgent
│   └── application_agent.md     # System prompt for ApplicationAgent
├── episodes/                    # Output directory for recorded episodes (gitignored)
│   └── .gitkeep
├── requirements.txt             # google-adk, aiosqlite
├── cli.py                       # CLI entry point: run scenarios, list episodes, heal-all
├── plan-review.md               # Initial plan review document
├── plan-review-feedback.md      # Hossein + Gemini feedback
├── plan-final.md                # This document
└── README.md                    # Usage, examples, architecture overview
```

---

## 11. Tool Specifications

### 11.1 Docker Tools (`tools/docker_tools.py`)

| Tool Function | Args | Returns | Mechanism |
|---|---|---|---|
| `docker_kill(container)` | container name | `{success, status, heal_cmd}` | `docker kill` |
| `docker_stop(container, timeout=0)` | container, grace period | `{success, status, heal_cmd}` | `docker stop -t N` |
| `docker_pause(container)` | container name | `{success, status, heal_cmd}` | `docker pause` |
| `docker_restart(container)` | container name | `{success, status, heal_cmd}` | `docker restart` |
| `docker_status(container)` | container name | `{status: running/exited/paused}` | `docker inspect` |

Every mutating tool returns a `heal_cmd` string that the registry stores.

### 11.2 Network Tools (`tools/network_tools.py`)

| Tool Function | Args | Returns | Mechanism |
|---|---|---|---|
| `inject_latency(container, delay_ms, jitter_ms)` | container, params | `{success, heal_cmd, pid}` | `nsenter -t PID -n tc qdisc add ...` |
| `inject_packet_loss(container, loss_pct)` | container, percentage | `{success, heal_cmd, pid}` | `nsenter -t PID -n tc qdisc add ... loss N%` |
| `inject_corruption(container, corrupt_pct)` | container, percentage | `{success, heal_cmd, pid}` | `nsenter -t PID -n tc qdisc add ... corrupt N%` |
| `inject_bandwidth_limit(container, rate_kbit)` | container, rate | `{success, heal_cmd, pid}` | `nsenter -t PID -n tc qdisc add ... tbf rate Nkbit` |
| `inject_partition(container, target_ip)` | container, target IP | `{success, heal_cmd, pid}` | `nsenter -t PID -n iptables -A ... -j DROP` |
| `clear_network_faults(container)` | container name | `{success}` | `nsenter -t PID -n tc qdisc del ... root` |

### 11.3 Verification Tools (`tools/verification_tools.py`)

| Tool Function | Args | Returns | Mechanism |
|---|---|---|---|
| `verify_container_status(container, expected)` | container, "exited"/"running" | `{verified: bool, actual}` | `docker inspect` |
| `verify_latency(container, target_ip, min_ms)` | container, IP, threshold | `{verified: bool, measured_ms}` | `nsenter ping -c 1` |
| `verify_reachability(container, target_ip)` | container, IP | `{reachable: bool, rtt_ms}` | `nsenter ping -c 1 -W 2` |
| `verify_unreachability(container, target_ip)` | container, IP | `{unreachable: bool}` | `nsenter ping -c 1 -W 2` (expect fail) |

### 11.4 Observation Tools (`tools/observation_tools.py`)

| Tool Function | Args | Returns | Mechanism |
|---|---|---|---|
| `snapshot_metrics()` | none | Full metrics dict | Reuse `MetricsCollector.collect()` |
| `snapshot_logs(containers, tail)` | container list, line count | `{container: [lines]}` | `docker logs --tail N` |
| `compute_metrics_delta(baseline, current)` | two metrics dicts | `{node: {metric: {baseline, current, delta}}}` | Pure computation |
| `compute_blast_radius(node_id)` | container name | `{broken_edges, affected_nodes}` | Reuse `topology.impact_of()` |

---

## 12. Scenario Library

### Pre-Built Scenarios (v1)

| # | Name | Category | Blast Radius | Faults | Expected Symptoms |
|---|---|---|---|---|---|
| 1 | **gNB Radio Link Failure** | container | single_nf | Kill `nr_gnb` | UEs lose 5G registration, all PDU sessions drop, SIP unregisters |
| 2 | **P-CSCF Latency** | network | single_nf | 500ms latency on `pcscf` | SIP REGISTER 408 timeouts, IMS registration fails |
| 3 | **S-CSCF Crash** | container | single_nf | Kill `scscf` | IMS auth fails, new registrations impossible, active calls drop |
| 4 | **HSS Unresponsive** | container | single_nf | Pause `pyhss` | Diameter timeouts, I-CSCF/S-CSCF can't resolve subscribers |
| 5 | **MongoDB Gone** | container | global | Kill `mongo` | 5G core loses subscriber store, UDR fails, new sessions fail |
| 6 | **DNS Failure** | container | global | Kill `dns` | IMS domain unresolvable, SIP routing breaks |
| 7 | **IMS Network Partition** | network | multi_nf | Partition between `pcscf` and `icscf`+`scscf` | SIP signaling severed, calls fail, registrations fail |
| 8 | **Data Plane Degradation** | network | single_nf | 30% packet loss on `upf` | Voice quality degrades, RTP packet loss, potential call drops |
| 9 | **AMF Restart (Upgrade Sim)** | container | multi_nf | Stop `amf` 10s, restart | UEs temporarily deregistered, re-attach required |
| 10 | **Cascading IMS Failure** | compound | multi_nf | Kill `pyhss` + add 2s latency on `scscf` | Total IMS outage: no auth + degraded signaling |

### Scenario Definition Format

```python
@dataclass
class Scenario:
    name: str
    description: str
    category: str             # "container", "network", "application", "compound"
    blast_radius: str         # "single_nf", "multi_nf", "global"
    faults: list[FaultSpec]   # Ordered list of faults to inject
    expected_symptoms: list[str]
    escalation: bool = False  # Enable adaptive escalation?
    challenge_mode: bool = False  # Run RCA agent after observation?
    observation_window_seconds: int = 30
    ttl_seconds: int = 120    # Max fault lifetime (safety)
```

---

## 13. Implementation Phases

### Phase 1A: Foundation (Week 1)

**Files:** `models.py`, `fault_registry.py`, `tools/docker_tools.py`, `tools/network_tools.py`, `tools/verification_tools.py`

- [ ] Pydantic models: `FaultSpec`, `Fault`, `Baseline`, `Observation`, `Episode`, `Scenario`
- [ ] SQLite fault registry with CRUD operations
- [ ] TTL reaper background task
- [ ] Signal handler + atexit emergency heal
- [ ] Docker tools (kill, stop, pause, restart) with heal commands
- [ ] Network tools (nsenter + tc/netem/iptables) with heal commands
- [ ] Verification tools (ping, docker inspect, tc show)
- [ ] **Test**: Manually inject a fault, verify registry, verify TTL heal, verify signal handler heal

### Phase 1B: ADK Agents (Week 2)

**Files:** `agents/*.py`, `orchestrator.py`, `tools/observation_tools.py`, `prompts/*.md`

- [ ] `pip install google-adk` + configure `GOOGLE_API_KEY`
- [ ] BaselineCollector agent (no LLM — deterministic)
- [ ] ContainerAgent (LlmAgent with docker tools)
- [ ] NetworkAgent (LlmAgent with network tools + verification)
- [ ] Healer agent (BaseAgent — reads registry, heals all)
- [ ] Observation tools (reuse MetricsCollector, docker logs, metrics delta)
- [ ] SymptomObserver LoopAgent with escalation logic
- [ ] ChaosDirector SequentialAgent wiring all phases
- [ ] System prompts for specialist agents
- [ ] **Test**: Run a single pre-built scenario end-to-end via ADK Runner

### Phase 1C: Recording + CLI (Week 3)

**Files:** `recorder.py`, `scenarios/library.py`, `cli.py`, `requirements.txt`, `README.md`

- [ ] Episode recorder: assemble from session.state, write JSON
- [ ] 10 pre-built scenarios in library.py
- [ ] CLI entry point: `python -m operate.agentic_chaos.cli run --scenario "P-CSCF Latency"`
- [ ] CLI: `list-scenarios`, `list-episodes`, `heal-all`, `show-episode <id>`
- [ ] ApplicationAgent + application tools (config corruption, DB faults)
- [ ] **Test**: Run 3+ scenarios, verify episode JSON output is complete and valid

### Phase 1D: Challenge Mode + Polish (Week 4)

**Files:** `scorer.py`, updates to `orchestrator.py`

- [ ] Challenge Mode integration: invoke `agentic_ops` troubleshooting agent as subprocess
- [ ] Scoring logic: compare Diagnosis to known injected faults
- [ ] Adaptive escalation schedules for each fault type
- [ ] Compound scenarios (multi-fault, sequential)
- [ ] Data-ready topology API: add `active_faults` query to fault_registry, expose via existing server.py
- [ ] README.md with usage examples and architecture overview
- [ ] **Test**: Run Challenge Mode, verify scoring output in episode JSON

### What's after Phase 1?

  Phase 2: GUI integration     — "Break This" button, fault timeline overlay, blast radius preview
  Phase 3: Autonomous platform — scheduled campaigns, auto-remediation agent, fine-tuned RCA model

---

## 14. Reuse Map

| Existing Component | Location | Used By | How |
|---|---|---|---|
| `topology.impact_of(node_id)` | `operate/gui/topology.py:102` | `observation_tools.compute_blast_radius()` | Import and call directly |
| `MetricsCollector.collect()` | `operate/gui/metrics.py:41` | `observation_tools.snapshot_metrics()` | Instantiate with same `_env`, call `collect()` |
| `_shell()` helper | `operate/agentic_ops/tools.py:26` | All chaos tools | Copy pattern (async subprocess) |
| `read_container_logs()` | `operate/agentic_ops/tools.py:68` | `observation_tools.snapshot_logs()` | Import or reimplement (simple docker logs) |
| `get_network_status()` | `operate/agentic_ops/tools.py:132` | `BaselineCollector` | Import and call |
| `.env` IP mappings | `.env`, `operate/e2e.env` | Network tools (resolve container → IP) | Reuse `_load_dotenv()` from server.py |
| `_KNOWN_NF_TYPES` | `operate/gui/topology.py:124` | Scenario validation | Import for container name → IP key mapping |

---

## 15. GCP Deployment Path

The chaos platform must work on both laptop and Google Cloud. The architecture supports this because:

**What stays the same:**
- ADK agent definitions (orchestrator, specialists)
- Episode recording format
- Scenario library
- Scoring logic

**What changes on GCP:**

| Component | Laptop | GCP |
|---|---|---|
| Docker host | Local Docker Desktop / Engine | GCE VM running Docker Compose, or GKE |
| `nsenter` | Direct on host | Via SSH to Docker host VM, or DaemonSet on GKE |
| Fault registry | Local SQLite file | Cloud SQL (PostgreSQL) or Firestore |
| Episode storage | Local `episodes/` directory | Cloud Storage bucket |
| ADK Runner | Local `python -m ...` | Cloud Run job or Vertex AI Agent Engine |
| Gemini API | API key via env var | Vertex AI endpoint (same models, different auth) |

**Migration path:** Containerize the chaos platform itself (`Dockerfile`), deploy as a Cloud Run service that connects to the Docker host via SSH or Docker API. The fault tools use `docker` CLI commands which can be redirected to a remote Docker daemon via `DOCKER_HOST` env var.

---

## 16. Not In Scope

| Item | Rationale |
|---|---|
| Migrating `agentic_ops` from Pydantic AI to ADK | Separate subsystem, works fine, migrate later if needed |
| Adding Prometheus exporters to Kamailio/UERANSIM | Orthogonal infrastructure work |
| GUI "Break This" button and fault timeline overlay | Phase 2 — CLI first, data-ready from day 1 |
| Campaign runner (automated sequences of scenarios) | Phase 2 — depends on stable single-scenario execution |
| Auto-remediation agent | Phase 3 (12-month vision) |
| Real traffic generation (SIPp, iperf) | Useful but separate concern |
| Multi-host distributed chaos (Kubernetes ChaosMonkey) | GCP version uses simpler Docker-over-SSH |
| Episode replay / deterministic re-execution | Phase 3 — requires state snapshotting |

---

## 17. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `nsenter` requires root/sudo on host | High | Blocker | The user runs Docker (which requires root). Chaos CLI will need `sudo` or the user must be in a group with nsenter access. Document clearly. |
| `tc`/`iproute2` not installed in host | Medium | Blocker | Pre-flight check in CLI: verify `tc` and `nsenter` are available. Install via `apt install iproute2 util-linux`. |
| Orphaned faults after crash | Medium | High | Triple Lock (registry + TTL + signal handlers). Also: `cli.py heal-all` as manual escape hatch. |
| Container PID changes on restart | Low | Medium | Always resolve PID fresh via `docker inspect` before `nsenter`. Never cache PIDs. |
| ADK + Gemini API latency on laptop | Medium | Low | Orchestrator/workflow agents are deterministic (no LLM). Only specialists call Gemini. For pre-built scenarios, specialists can be bypassed entirely (direct tool calls). |
| Gemini 3.1 models deprecated | Low | Medium | Models are parameterized in config, not hardcoded. Easy to swap. |
| SQLite concurrent access from GUI + chaos agent | Medium | Low | Use WAL mode (`PRAGMA journal_mode=WAL`) for concurrent reads. Only one writer at a time (the chaos agent). |
| Stack doesn't recover after fault healing | Medium | High | Post-heal verification step. If recovery fails, log it in the episode and alert. Include `docker restart` as a last-resort heal. |

---

## 18. Sources

- [ADK Documentation — Index](https://google.github.io/adk-docs/)
- [ADK Multi-Agent Systems](https://google.github.io/adk-docs/agents/multi-agents/)
- [ADK Workflow Agents](https://google.github.io/adk-docs/agents/workflow-agents/)
- [ADK Technical Overview](https://google.github.io/adk-docs/get-started/about/)
- [ADK Python Quickstart](https://google.github.io/adk-docs/get-started/python/)
- [ADK Claude Integration](https://google.github.io/adk-docs/agents/models/anthropic/)
- [ADK LiteLLM Integration](https://google.github.io/adk-docs/agents/models/litellm/)
- [ADK Deployment Options](https://google.github.io/adk-docs/deploy/)
- [ADK on PyPI (v1.27.2)](https://pypi.org/project/google-adk/)
- [ADK GitHub (Python)](https://github.com/google/adk-python)
- [Gemini 3.1 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite-preview)
- [Gemini 3.1 Pro](https://deepmind.google/models/model-cards/gemini-3-1-pro/)
- [Pumba — Chaos Testing for Docker](https://github.com/alexei-led/pumba)
- [Toxiproxy — Network Fault Injection](https://oneuptime.com/blog/post/2026-02-08-how-to-use-docker-for-chaos-engineering-with-toxiproxy/view)
