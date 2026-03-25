# Agentic Chaos Monkey — Developer & User Guide

A hands-on guide to running chaos experiments on the 5G SA + IMS Docker stack.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Quick Start](#2-quick-start)
3. [CLI Reference](#3-cli-reference)
4. [Running Scenarios](#4-running-scenarios)
5. [Understanding Episodes](#5-understanding-episodes)
6. [The 10 Pre-Built Scenarios](#6-the-10-pre-built-scenarios)
7. [Safety: What Happens If Things Go Wrong](#7-safety-what-happens-if-things-go-wrong)
8. [Writing Custom Scenarios](#8-writing-custom-scenarios)
9. [Using Episodes as Training Data](#9-using-episodes-as-training-data)
10. [Challenge Mode (RCA Evaluation)](#10-challenge-mode-rca-evaluation)
11. [Adaptive Escalation](#11-adaptive-escalation)
12. [Programmatic API](#12-programmatic-api)
13. [Troubleshooting](#13-troubleshooting)
14. [FAQ](#14-faq)

---

## 1. Prerequisites

Before using the chaos platform, verify you have:

### System tools

```bash
# These should all return without error:
docker --version          # Docker 28+
nsenter --version         # util-linux
tc -V                     # iproute2
iptables --version        # iptables/nftables
sqlite3 --version         # SQLite CLI
```

### Passwordless sudo for fault injection

Network faults use `nsenter` which requires root. Verify this works without a password prompt:

```bash
sudo -n nsenter --version    # Should NOT ask for password
sudo -n tc -V                # Should NOT ask for password
```

If these prompt for a password, set up the sudoers rule:

```bash
sudo visudo -f /etc/sudoers.d/chaos-monkey
# Add this line (replace 'yourusername' with your actual username):
# yourusername ALL=(root) NOPASSWD: /usr/bin/nsenter, /usr/sbin/tc, /usr/sbin/iptables
```

### Python packages

```bash
# Activate the venv
source operate/.venv/bin/activate

# Verify key packages
python -c "from google.adk.agents import SequentialAgent; print('ADK OK')"
python -c "import aiosqlite; print('aiosqlite OK')"
```

### Gemini API access (Vertex AI)

```bash
# These env vars must be set:
export GOOGLE_CLOUD_PROJECT="your-gcp-project"
export GOOGLE_CLOUD_LOCATION="northamerica-northeast1"  # or your region
export GOOGLE_GENAI_USE_VERTEXAI="TRUE"

# Verify:
gcloud auth application-default print-access-token >/dev/null && echo "Auth OK"
```

### The 5G + IMS stack must be running

```bash
# Verify core containers are up:
docker ps --format '{{.Names}}' | wc -l
# Should show ~20 containers (amf, smf, upf, pcscf, etc.)
```

---

## 2. Quick Start

The fastest way to run your first chaos experiment:

```bash
# From the docker_open5gs root directory:

# 1. List what scenarios are available
PYTHONPATH=operate operate/.venv/bin/python -m agentic_chaos.cli list-scenarios

# 2. Run a safe scenario against the v1.5 agent
PYTHONPATH=operate operate/.venv/bin/python -m agentic_chaos.cli run "DNS Failure" --agent v1.5

# 3. Check the recorded episode
PYTHONPATH=operate operate/.venv/bin/python -m agentic_chaos.cli list-episodes
```

You should see output like:

```
Running scenario: DNS Failure
  Agent: v1.5
  Category: container
  Blast radius: global
  Faults: 1
  Description: Kill the DNS server. IMS domain resolution breaks...

============================================================
EPISODE COMPLETE
============================================================
  ID:            ep_20260324_202745_dns_failure
  Duration:      35.2s
  Faults:        1
  Observations:  6
  Symptoms:      True
  Resolution:    scheduled
  RCA label:     data_layer
  Episode file:  .../agentic_ops/docs/agent_logs/run_20260324_202745_dns_failure.json

  Agent Evaluation:
    Score:        85%
    Root cause:   correct
    Components:   100% overlap
    Severity:     correct
    Diagnosis:    DNS container is down, causing IMS domain resolution failure...

  Markdown report: .../agentic_ops/docs/agent_logs/run_20260324_202745_dns_failure.md
```

The platform injected the fault, observed symptoms, invoked the troubleshooting agent, scored its diagnosis, healed the stack, and recorded everything as both a JSON episode file and a markdown summary.

---

## 3. CLI Reference

All commands are run from the `docker_open5gs` root directory:

```bash
# Shorthand used in this guide:
alias chaos='PYTHONPATH=operate operate/.venv/bin/python -m agentic_chaos.cli'
```

### `chaos list-scenarios`

Lists all 10 pre-built scenarios with their category and blast radius.

```
Name                                Category     Blast        Faults
----------------------------------------------------------------------
gNB Radio Link Failure              container    single_nf    1
P-CSCF Latency                      network      single_nf    1
S-CSCF Crash                        container    single_nf    1
HSS Unresponsive                    container    single_nf    1
Data Plane Degradation              network      single_nf    1
MongoDB Gone                        container    global       1
DNS Failure                         container    global       1
IMS Network Partition               network      multi_nf     2
AMF Restart (Upgrade Simulation)    container    multi_nf     1
Cascading IMS Failure               compound     multi_nf     2
```

### `chaos run "<scenario name>" --agent <v1.5|v3>`

Runs a complete chaos episode against the specified troubleshooting agent. The `--agent` flag is required — it selects which agent version is invoked during the challenge step.

The platform will:
1. Capture a baseline (metrics + container status)
2. Inject the specified faults
3. Verify each fault took effect
4. Observe symptoms (poll metrics/logs)
5. Invoke the troubleshooting agent and score its diagnosis
6. Heal all faults
7. Write the episode JSON + markdown summary to the agent's log directory

```bash
chaos run "P-CSCF Latency" --agent v1.5
chaos run "gNB Radio Link Failure" --agent v3
chaos run "Cascading IMS Failure" --agent v3
```

Output files are written to the respective agent's directory:
- **v1.5:** `operate/agentic_ops/docs/agent_logs/run_<ts>_<scenario>.{json,md}`
- **v3:** `operate/agentic_ops_v3/docs/agent_logs/run_<ts>_<scenario>.{json,md}`

Add `-v` for verbose/debug output:

```bash
chaos -v run "DNS Failure" --agent v1.5
```

### `chaos list-episodes`

Lists all recorded episodes with duration, fault count, and whether symptoms were detected.

```
Episode ID                                         Duration   Faults   Symptoms
-------------------------------------------------------------------------------------
ep_20260318_202745_dns_failure                         1.8s  1        True
ep_20260318_202708_test_observations                   0.9s  1        True
ep_20260318_202659_test_dns_pause                      0.8s  1        True
```

### `chaos show-episode <episode_id>`

Prints the full episode JSON. Supports partial ID matching:

```bash
# Full ID:
chaos show-episode ep_20260318_202745_dns_failure

# Partial match (if unambiguous):
chaos show-episode dns_failure
```

Pipe to `jq` for pretty filtering:

```bash
chaos show-episode dns_failure | jq '.faults[0]'
chaos show-episode dns_failure | jq '.observations[0].log_samples'
chaos show-episode dns_failure | jq '.rca_label'
```

### `chaos heal-all`

Emergency command — heals ALL active faults immediately. Use this if:
- A scenario was interrupted (Ctrl+C before healing phase)
- You suspect orphaned faults (latency rules, paused containers)
- The stack is behaving oddly after a chaos run

```bash
chaos heal-all
# Output: "No active faults." or "Healed N faults."
```

This is your safety net. When in doubt, run `heal-all`.

---

## 4. Running Scenarios

### Choosing a scenario

Start with low-risk single-NF scenarios before moving to multi-NF or global:

**Beginner (start here):**
- `DNS Failure` — kills DNS, easy to understand, heals fast
- `HSS Unresponsive` — pauses PyHSS, causes Diameter timeouts

**Intermediate:**
- `P-CSCF Latency` — network latency, has escalation mode
- `Data Plane Degradation` — packet loss on UPF, affects voice quality

**Advanced:**
- `IMS Network Partition` — iptables partition, severs SIP signaling
- `Cascading IMS Failure` — compound fault, multiple simultaneous failures

All scenarios automatically invoke Challenge Mode (the troubleshooting agent is always evaluated). You choose which agent to test with the `--agent` flag.

### What to expect

When a scenario runs, you'll see log output showing each phase:

```
chaos-agent.baseline: Capturing baseline snapshot...
chaos-orchestrator: [BaselineCollector] Baseline captured: phase=ready, 20 containers running

chaos-agent.injector: Injecting fault 1/1: container_kill on dns
chaos-registry: Registered fault f_bd5aec3c on dns (TTL=120s)
chaos-agent.injector:   → VERIFIED: Expected 'exited', got 'exited'
chaos-orchestrator: [FaultInjector] Injected 1 of 1 faults

chaos-agent.observer: Symptom poll iteration 1 (elapsed: 1.1s)
chaos-agent.observer:   → Iteration 1: SYMPTOMS DETECTED.

chaos-registry: Healed fault f_bd5aec3c (method=scheduled)
chaos-orchestrator: [Healer] Healed 1 faults. Recovery time: 1.8s

chaos-agent.recorder: Episode recorded: .../episodes/ep_20260318_..._dns_failure.json
```

Each episode typically takes 2-30 seconds depending on the observation window.

### Stack phase requirements

The platform checks the stack phase before injecting:
- **"ready"** — All 20 containers running. Ideal state for chaos.
- **"partial"** — Core is up but UEs/gNB are missing. Scenarios will still run but some symptoms may differ.
- **"down"** — Core containers are missing. Most scenarios will fail because there's nothing to break.

---

## 5. Understanding Episodes

Each chaos run produces **two files** in the agent's log directory:
- **JSON episode log** (`run_<ts>_<scenario>.json`) — machine-readable record of everything
- **Markdown summary** (`run_<ts>_<scenario>.md`) — plain-English analysis for human review

Files are written to:
- v1.5: `operate/agentic_ops/docs/agent_logs/`
- v3: `operate/agentic_ops_v3/docs/agent_logs/`

A copy of the JSON is also kept in `operate/agentic_chaos/episodes/` for the platform's own episode tracking.

Here's what's inside the JSON:

### Episode structure

```
episode.json
├── schema_version    "1.0"
├── episode_id        "ep_20260318_202745_dns_failure"
├── timestamp         When the episode started
├── duration_seconds  Total wall-clock time
│
├── scenario          What was planned
│   ├── name, description
│   ├── category      "container" / "network" / "compound"
│   ├── blast_radius  "single_nf" / "multi_nf" / "global"
│   └── faults        List of FaultSpecs (what to inject)
│
├── baseline          Pre-fault snapshot
│   ├── stack_phase   "ready" / "partial" / "down"
│   ├── container_status  {amf: "running", pcscf: "running", ...}
│   └── metrics       {amf: {ran_ue: 2, ...}, pcscf: {...}, ...}
│
├── faults            What was actually injected (with verification)
│   └── [{fault_id, fault_type, target, mechanism, heal_command,
│          verified: true, verification_result: "..."}]
│
├── observations      Symptom polls during the fault
│   └── [{iteration, timestamp, elapsed_seconds,
│          metrics_delta: {node: {metric: {baseline, current, delta}}},
│          log_samples: {container: [error lines]},
│          symptoms_detected: true/false}]
│
├── resolution        How the fault was healed
│   ├── healed_at, heal_method
│   ├── post_heal_metrics
│   └── recovery_time_seconds
│
├── rca_label         Ground truth (for training)
│   ├── root_cause
│   ├── affected_components
│   ├── severity      "healthy" / "degraded" / "down"
│   ├── failure_domain "ims_signaling" / "data_plane" / ...
│   └── protocol_impact "SIP" / "Diameter" / "GTP-U" / ...
│
└── challenge_result  (only if Challenge Mode was enabled)
    ├── diagnosis from RCA agent
    └── score {root_cause_correct, component_overlap, total_score}
```

### Useful jq queries

```bash
# What faults were injected?
chaos show-episode <id> | jq '.faults[] | {target, fault_type, verified}'

# What symptoms were detected?
chaos show-episode <id> | jq '.observations[] | {iteration, symptoms_detected, metrics_delta | keys}'

# What error logs appeared?
chaos show-episode <id> | jq '.observations[0].log_samples'

# What's the ground-truth RCA label?
chaos show-episode <id> | jq '.rca_label'

# How long did recovery take?
chaos show-episode <id> | jq '.resolution.recovery_time_seconds'
```

---

## 6. The 10 Pre-Built Scenarios

### Single-NF Scenarios (break one thing)

#### gNB Radio Link Failure
**What it does:** Kills the UERANSIM gNB container.
**What breaks:** UEs lose their 5G radio connection. PDU sessions drop. SIP REGISTER timers expire without renewal.
**Why it matters:** Tests the most common radio failure — the gNB going offline.

#### P-CSCF Latency
**What it does:** Injects 500ms latency on the P-CSCF (SIP edge proxy).
**What breaks:** SIP REGISTER transactions timeout (Kamailio T1 timer is 500ms). IMS registration fails.
**Special:** Has `escalation=True` — the platform will ramp up latency from 100ms→250ms→500ms→2000ms until symptoms appear.

#### S-CSCF Crash
**What it does:** Kills the S-CSCF (Serving-CSCF / SIP registrar).
**What breaks:** IMS authentication stops (no MAR/MAA Diameter exchange). New registrations impossible. Active calls eventually drop.

#### HSS Unresponsive
**What it does:** Pauses (freezes) PyHSS. Docker still shows it as "running" but all processes are frozen.
**What breaks:** Diameter UAR/UAA and MAR/MAA requests hang. SIP REGISTER stalls waiting for Diameter. This is subtler than a crash — the HSS looks alive but can't respond.

#### Data Plane Degradation
**What it does:** Injects 30% packet loss on the UPF.
**What breaks:** RTP media streams degrade. Voice calls become choppy or drop. GTP-U packet counters show anomalies.

### Global Scenarios (break everything downstream)

#### MongoDB Gone
**What it does:** Kills MongoDB — the 5G core's subscriber data store.
**What breaks:** UDR can't query subscriber data. New PDU session creation fails. Existing sessions may survive briefly from cached state.

#### DNS Failure
**What it does:** Kills the DNS server.
**What breaks:** IMS domain (ims.mnc001.mcc001.3gppnetwork.org) becomes unresolvable. All SIP routing that depends on DNS NAPTR/SRV records fails.

### Multi-NF Scenarios (break relationships between things)

#### IMS Network Partition
**What it does:** Creates iptables DROP rules that block all traffic between the P-CSCF and both the I-CSCF and S-CSCF.
**What breaks:** SIP signaling between the edge proxy and the IMS core is completely severed. New registrations and calls fail. Active calls may survive briefly (RTP goes through UPF, not CSCFs).

#### AMF Restart (Upgrade Simulation)
**What it does:** Stops the AMF with a 10-second grace period, then the healer starts it back up.
**What breaks:** UEs temporarily lose their NAS connection. NGAP association at the gNB drops. UEs must re-register after the AMF recovers.
**Why it matters:** Simulates a rolling NF upgrade, which is the most common planned disruption in production 5G networks.

#### Cascading IMS Failure
**What it does:** Kills PyHSS AND adds 2-second latency to the S-CSCF simultaneously.
**What breaks:** Total IMS outage — no Diameter auth (HSS is dead) AND SIP is extremely slow (2s latency). No voice calls possible.
**Special:** Compound fault with two simultaneous failures — tests whether the agent can trace cascading symptoms back to multiple root causes.

---

## 7. Safety: What Happens If Things Go Wrong

### The Triple Lock protects you

Every injected fault has three independent safety mechanisms:

1. **SQLite Registry** — The heal command is recorded BEFORE injection. If the process dies mid-inject, the heal command is still in the database.

2. **TTL Reaper** — Every fault has a maximum lifetime (default 120 seconds). A background task checks every 5 seconds and auto-heals expired faults, even if the orchestrator hangs.

3. **Signal Handlers** — If you press Ctrl+C or the process is killed, all active faults are healed synchronously before exit.

### Manual recovery

If you suspect the stack is in a bad state:

```bash
# 1. First, try heal-all
chaos heal-all

# 2. If that shows "No active faults" but something is still broken,
#    check for orphaned tc rules on a specific container:
PID=$(docker inspect -f '{{.State.Pid}}' pcscf)
sudo nsenter -t $PID -n tc qdisc show dev eth0

# 3. If you see netem/tbf rules, clear them:
sudo nsenter -t $PID -n tc qdisc del dev eth0 root

# 4. If a container is paused:
docker unpause <container_name>

# 5. If a container was killed:
docker start <container_name>

# 6. Nuclear option — restart the entire stack:
docker compose -f sa-vonr-deploy.yaml restart
```

### What if my laptop loses power mid-episode?

The TTL reaper won't be running, but the faults have a maximum lifetime. When you restart:
1. Container faults (kill/pause): Docker will start containers normally. Paused containers become unpaused on Docker restart.
2. Network faults (tc/iptables): These live in the container's network namespace. If the container restarts, the rules are gone. If the container didn't restart, run `chaos heal-all` to clean up.

---

## 8. Writing Custom Scenarios

You can define custom scenarios in Python:

```python
import asyncio
import sys
sys.path.insert(0, 'operate')

from agentic_chaos.models import Scenario, FaultSpec, FaultCategory, BlastRadius
from agentic_chaos.orchestrator import run_scenario

# Define a custom scenario
my_scenario = Scenario(
    name="Custom: Slow S-CSCF",
    description="Add 300ms latency to S-CSCF to test SIP auth performance",
    category=FaultCategory.NETWORK,
    blast_radius=BlastRadius.SINGLE_NF,
    faults=[
        FaultSpec(
            fault_type="network_latency",
            target="scscf",
            params={"delay_ms": 300, "jitter_ms": 30},
            ttl_seconds=90,
        ),
    ],
    expected_symptoms=["SIP auth latency increase", "Diameter MAR/MAA delay"],
    observation_window_seconds=20,
    ttl_seconds=90,
)

# Run it against v3
episode = asyncio.run(run_scenario(my_scenario, agent_version="v3"))
print(f"Episode: {episode['episode_id']}")
```

### Available fault types and their parameters

```python
# Container faults (no params needed):
FaultSpec(fault_type="container_kill", target="pcscf")
FaultSpec(fault_type="container_stop", target="amf", params={"timeout": 10})
FaultSpec(fault_type="container_pause", target="pyhss")
FaultSpec(fault_type="container_restart", target="smf")

# Network faults:
FaultSpec(fault_type="network_latency", target="pcscf",
          params={"delay_ms": 500, "jitter_ms": 50})

FaultSpec(fault_type="network_loss", target="upf",
          params={"loss_pct": 30})

FaultSpec(fault_type="network_corruption", target="upf",
          params={"corrupt_pct": 5})

FaultSpec(fault_type="network_bandwidth", target="pcscf",
          params={"rate_kbit": 100})

FaultSpec(fault_type="network_partition", target="pcscf",
          params={"target_ip": "172.22.0.19"})  # I-CSCF IP
```

### Valid targets

Any container in the stack:

```
mongo, nrf, scp, ausf, udr, udm, amf, smf, upf, pcf,
dns, mysql, pyhss, icscf, scscf, pcscf, rtpengine,
nr_gnb, e2e_ue1, e2e_ue2
```

### Compound scenarios (multiple faults)

```python
cascading = Scenario(
    name="Custom: IMS Meltdown",
    description="Kill HSS + partition P-CSCF + add latency on S-CSCF",
    category=FaultCategory.COMPOUND,
    blast_radius=BlastRadius.MULTI_NF,
    faults=[
        FaultSpec(fault_type="container_kill", target="pyhss"),
        FaultSpec(fault_type="network_partition", target="pcscf",
                  params={"target_ip": "172.22.0.19"}),
        FaultSpec(fault_type="network_latency", target="scscf",
                  params={"delay_ms": 1000}),
    ],
    expected_symptoms=["Total IMS outage"],
    ttl_seconds=60,
)
```

---

## 9. Using Episodes as Training Data

Episodes are designed as training data for telecom RCA models. Each episode is a self-contained `(scenario, baseline, symptoms, root_cause)` tuple.

### Loading episodes in Python

```python
import json
from pathlib import Path

episodes_dir = Path("operate/agentic_chaos/episodes")

# Load all episodes
episodes = []
for f in episodes_dir.glob("ep_*.json"):
    with open(f) as fp:
        episodes.append(json.load(fp))

print(f"Loaded {len(episodes)} episodes")

# Filter by fault type
network_faults = [
    ep for ep in episodes
    if any(f["fault_type"].startswith("network_") for f in ep["faults"])
]

# Extract training pairs: (symptoms, root_cause)
training_data = []
for ep in episodes:
    symptoms = {
        "metrics_delta": ep["observations"][0].get("metrics_delta", {}) if ep["observations"] else {},
        "log_samples": ep["observations"][0].get("log_samples", {}) if ep["observations"] else {},
    }
    label = ep["rca_label"]
    training_data.append({"symptoms": symptoms, "label": label})
```

### Episode fields useful for training

| Field | Use |
|---|---|
| `observations[].metrics_delta` | Quantitative signal: which metrics changed and by how much |
| `observations[].log_samples` | Qualitative signal: error messages, SIP codes, timeouts |
| `rca_label.root_cause` | Ground truth: what actually happened |
| `rca_label.affected_components` | Ground truth: which NFs were involved |
| `rca_label.failure_domain` | Classification: ims_signaling, data_plane, core_control_plane |
| `rca_label.protocol_impact` | Classification: SIP, Diameter, GTP-U, NGAP, PFCP |
| `scenario.blast_radius` | Severity classification: single_nf, multi_nf, global |

### Building an eval dataset

Run all 10 scenarios against both agents to build a comparison dataset:

```bash
# Evaluate v1.5 across all scenarios
for scenario in \
    "gNB Radio Link Failure" \
    "P-CSCF Latency" \
    "S-CSCF Crash" \
    "HSS Unresponsive" \
    "Data Plane Degradation" \
    "MongoDB Gone" \
    "DNS Failure" \
    "IMS Network Partition" \
    "AMF Restart (Upgrade Simulation)" \
    "Cascading IMS Failure"; do
  echo "=== Running: $scenario (v1.5) ==="
  chaos run "$scenario" --agent v1.5
  sleep 5  # Let the stack recover between scenarios
done

# Then evaluate v3 across the same scenarios
for scenario in \
    "gNB Radio Link Failure" \
    "P-CSCF Latency" \
    "S-CSCF Crash" \
    "HSS Unresponsive" \
    "Data Plane Degradation" \
    "MongoDB Gone" \
    "DNS Failure" \
    "IMS Network Partition" \
    "AMF Restart (Upgrade Simulation)" \
    "Cascading IMS Failure"; do
  echo "=== Running: $scenario (v3) ==="
  chaos run "$scenario" --agent v3
  sleep 5
done

chaos list-episodes
```

Results land in their respective directories — compare the markdown summaries side by side:

```bash
# v1.5 results
ls operate/agentic_ops/docs/agent_logs/run_*.md

# v3 results
ls operate/agentic_ops_v3/docs/agent_logs/run_*.md
```

---

## 10. Challenge Mode (RCA Evaluation)

Challenge Mode tests whether an AI agent can correctly diagnose an injected fault without knowing what was injected. It is **always enabled** — every scenario run evaluates the specified agent.

### How it works

1. The chaos platform injects a fault and observes symptoms
2. The `ChallengeAgent` invokes the troubleshooting agent selected by `--agent`
   - **v1.5:** Pydantic AI single-agent (`agentic_ops`) — defaults to Gemini 2.5 Pro via Vertex AI
   - **v3:** ADK multi-phase pipeline (`agentic_ops_v3`) — uses Gemini via Vertex AI
3. The agent sees only the symptoms (logs, metrics) — NOT the injected fault
4. The agent produces a diagnosis (root_cause, affected_components, confidence)
5. The `scorer` compares the diagnosis to ground truth and produces a score
6. Both JSON and markdown reports are written to the agent's log directory

### Requirements

Both agents default to Gemini 2.5 Pro via Vertex AI, so they share the same credentials:

```bash
export GOOGLE_CLOUD_PROJECT="your-gcp-project"
export GOOGLE_CLOUD_LOCATION="northamerica-northeast1"
export GOOGLE_GENAI_USE_VERTEXAI="TRUE"
```

v1.5 can alternatively use Anthropic Claude by setting `AGENT_MODEL` and `ANTHROPIC_API_KEY`:

```bash
export AGENT_MODEL="anthropic:claude-sonnet-4-20250514"
export ANTHROPIC_API_KEY="your-key-here"
```

If the required credentials are not set, Challenge Mode is skipped gracefully — the rest of the episode (baseline, inject, observe, heal, record) runs normally, but no agent diagnosis or score is produced.

### Understanding the score

The score has five dimensions:

| Dimension | Weight | What it measures |
|---|---|---|
| Root cause correct | 40% | Did the agent identify the right container(s)? |
| Component overlap | 25% | Jaccard similarity of affected component lists |
| Severity correct | 15% | Did it say "down" when the NF was killed, "degraded" when there was latency? |
| Fault type identified | 10% | Did it mention relevant keywords (e.g., "latency", "timeout", "killed")? |
| Confidence calibrated | 10% | High confidence + correct = good. High confidence + wrong = bad. |

The total score is 0.0 to 1.0 (0% to 100%). A score above 0.7 is good. Above 0.85 is excellent.

---

## 11. Adaptive Escalation

When a scenario has `escalation=True`, the platform doesn't just inject a fixed fault — it progressively increases severity until symptoms appear.

### How it works

```
Iteration 1: inject 100ms latency → poll metrics → no symptoms detected
             → heal 100ms → inject 250ms
Iteration 2: inject 250ms latency → poll metrics → no symptoms detected
             → heal 250ms → inject 500ms
Iteration 3: inject 500ms latency → poll metrics → SIP T1 timer hit!
             → SYMPTOMS DETECTED → exit observation loop → heal → record
```

### Escalation schedules

| Fault type | Level 0 | Level 1 | Level 2 | Level 3 |
|---|---|---|---|---|
| network_latency | 100ms | 250ms | 500ms | 2000ms |
| network_loss | 5% | 15% | 30% | 50% |
| network_bandwidth | 1000kbit | 500kbit | 100kbit | 10kbit |
| network_jitter | 20ms | 50ms | 100ms | 500ms |

### Enabling escalation

The pre-built "P-CSCF Latency" scenario has escalation. For custom scenarios:

```python
my_scenario = Scenario(
    ...,
    escalation=True,  # Enable adaptive escalation
    faults=[
        FaultSpec(fault_type="network_latency", target="pcscf",
                  params={"delay_ms": 100}),  # Starting params (will be overridden by schedule)
    ],
)
```

### Why escalation matters

The escalation data is the most valuable training signal the platform produces. Instead of just recording "500ms latency breaks SIP", it records:
- "100ms latency: no impact"
- "250ms latency: no impact"
- "500ms latency: SIP T1 timer exceeded, REGISTER transactions fail"

This teaches an RCA model the **threshold** at which protocols break — knowledge that's extremely hard to get from production data alone.

---

## 12. Programmatic API

The chaos platform can be used as a Python library, not just via CLI.

### Running a scenario

```python
import asyncio
from agentic_chaos.orchestrator import run_scenario
from agentic_chaos.scenarios.library import get_scenario

async def main():
    scenario = get_scenario("DNS Failure")
    episode = await run_scenario(scenario, agent_version="v1.5")
    print(f"Duration: {episode['duration_seconds']:.1f}s")
    print(f"Symptoms: {any(o['symptoms_detected'] for o in episode['observations'])}")
    print(f"Score: {episode.get('challenge_result', {}).get('score', {}).get('total_score', 'N/A')}")

asyncio.run(main())
```

### Using tools directly (without the orchestrator)

```python
import asyncio
from agentic_chaos.tools.docker_tools import docker_pause, docker_unpause
from agentic_chaos.tools.network_tools import inject_latency, clear_tc_rules
from agentic_chaos.tools.verification_tools import verify_tc_active
from agentic_chaos.tools.observation_tools import snapshot_metrics, compute_blast_radius

async def manual_experiment():
    # Check blast radius before injecting
    impact = await compute_blast_radius("pcscf")
    print(f"Breaking pcscf affects: {impact['affected_nodes']}")

    # Inject latency
    result = await inject_latency("pcscf", delay_ms=300)
    print(f"Injected: {result['success']}")

    # Verify
    tc = await verify_tc_active("pcscf")
    print(f"TC active: {tc['active']}")

    # Capture metrics while fault is active
    metrics = await snapshot_metrics()
    print(f"P-CSCF transactions: {metrics.get('pcscf', {}).get('metrics', {})}")

    # Heal
    await clear_tc_rules("pcscf")
    print("Healed")

asyncio.run(manual_experiment())
```

### Using the fault registry directly

```python
import asyncio
from agentic_chaos.fault_registry import FaultRegistry

async def check_registry():
    registry = FaultRegistry()
    await registry.initialize()

    # Check for any active faults
    active = await registry.get_active_faults()
    for f in active:
        print(f"{f.fault_id}: {f.fault_type} on {f.target} (expires {f.expires_at})")

    # Heal everything
    count = await registry.heal_all(method="manual")
    print(f"Healed {count} faults")

asyncio.run(check_registry())
```

---

## 13. Troubleshooting

### "Unknown container" error

```
ValueError: Unknown container 'foo'. Known containers: mongo, nrf, ...
```

The container name must match exactly. Check valid names with:
```python
from agentic_chaos.tools._common import ALL_CONTAINERS
print(ALL_CONTAINERS)
```

### "Cannot get PID for container" error

```
RuntimeError: Cannot get PID for container 'dns' — not running?
```

The container must be running for network faults (which need `nsenter`). Check:
```bash
docker inspect -f '{{.State.Status}}' dns
```

### "Permission denied" on nsenter

```
nsenter: cannot open /proc/.../ns/net: Permission denied
```

Your sudo rule isn't set up. See [Prerequisites](#1-prerequisites).

### Faults seem to persist after a run

```bash
# First, check the registry:
chaos heal-all

# If that says "No active faults" but the stack is still broken:
# The fault was healed but the container hasn't recovered yet.
# Give it a few seconds, or restart the affected container:
docker restart pcscf
```

### Episode JSON is empty or missing fields

This usually means the baseline snapshot failed (Prometheus unreachable, or containers not running). Check:
```bash
# Is Prometheus up?
curl -s http://172.22.0.36:9090/api/v1/query?query=up | python3 -m json.tool | head

# Are containers running?
docker ps --format '{{.Names}}\t{{.State}}'
```

### Gemini API errors

```
google.genai.errors.ClientError: 404 NOT_FOUND
```

Check your Vertex AI setup:
```bash
echo $GOOGLE_CLOUD_PROJECT    # Must be set
echo $GOOGLE_CLOUD_LOCATION   # Must match a region with Gemini
echo $GOOGLE_GENAI_USE_VERTEXAI  # Must be "TRUE"
gcloud auth application-default print-access-token >/dev/null  # Must succeed
```

---

## 14. FAQ

**Q: Will the chaos monkey break my production network?**
A: No. It only operates on Docker containers on your local machine via `docker kill`, `docker pause`, `nsenter + tc`, etc. It has no access to anything outside the Docker network.

**Q: Can I run chaos while the GUI is active?**
A: Yes. The GUI will show the effects in real time — containers going down, metrics changing. The API endpoint `GET /api/chaos/faults` exposes active faults for future GUI integration.

**Q: How long does an episode take?**
A: Most episodes take 2-30 seconds. The observation window (default 30s) determines how long the platform waits for symptoms. Symptoms are usually detected in the first poll (5s), so episodes complete quickly.

**Q: What if I want to inject a fault and leave it active for manual testing?**
A: Use the tools directly instead of `run_scenario()`:
```python
from agentic_chaos.tools.network_tools import inject_latency
result = asyncio.run(inject_latency("pcscf", delay_ms=500))
print(f"Heal with: {result['heal_cmd']}")
# Now test manually... when done:
from agentic_chaos.tools.network_tools import clear_tc_rules
asyncio.run(clear_tc_rules("pcscf"))
```

**Q: Can I add new fault types?**
A: Yes. Add a new async function in the appropriate tool module (e.g., `tools/network_tools.py`), add the fault type string to `_NETWORK_FAULTS` in `fault_injector.py`, and add dispatch entries in `_dispatch_inject()` and `_dispatch_verify()`.

**Q: What's the difference between "container_kill" and "container_stop"?**
A: `container_kill` sends SIGKILL (immediate, no cleanup). `container_stop` sends SIGTERM first, waits for the grace period, then SIGKILL. Use `stop` with a timeout to simulate a graceful shutdown/upgrade.

**Q: What's the difference between "container_pause" and "container_kill"?**
A: `pause` freezes all processes (SIGSTOP) — the container appears "running" but can't respond. This simulates an unresponsive NF (e.g., memory exhaustion, deadlock). `kill` terminates the container entirely. Paused containers are trickier because health checks may not detect them as failed.

**Q: How do I add a custom scenario to the library permanently?**
A: Edit `operate/agentic_chaos/scenarios/library.py`. Add your Scenario object and include it in the `SCENARIOS` dict. Then add a test in `tests/test_scenarios.py` to validate it.
