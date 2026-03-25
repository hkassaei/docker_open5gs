# Agentic Chaos Monkey — CEO Plan Review

**Date:** 2026-03-18
**Status:** Awaiting mode selection (EXPANSION / HOLD / REDUCTION)
**Author:** Claude (plan review), Hossein (concept & requirements)

---

## PRE-REVIEW SYSTEM AUDIT

### Current System State

**Repository**: `docker_open5gs` — a containerized 5G SA + IMS stack (Open5GS, Kamailio, PyHSS, UERANSIM, RTPEngine) with an `operate/` overlay that adds:

- **GUI** (`operate/gui/`): aiohttp server + single-page topology viewer with live metrics, WebSocket log streaming, AI explain buttons on every NF detail panel
- **Troubleshooting agent** (`operate/agentic_ops/`): Pydantic AI agent with 6 tools (read logs, read config, network status, query subscriber, read env, search logs) — uses Anthropic Claude via `anthropic:claude-sonnet-4-20250514`
- **E2E test scripts** (`operate/scripts/`): deploy/teardown/provision automation
- **Docs** (`operate/docs/`): RCAs, reflections, architecture docs
- **Empty directory** (`operate/agentic_chaos/`): created but contains no files — the user has already started thinking about this

**Uncommitted work**: topology.py, metrics.py (subscriber counts), index.html (AI Explain button on detail panels), server.py (container-aware explain endpoint), plus new untracked files (metrics.py, topology.py, topology_plan.md, docs/features/).

**No stashes. No TODO/FIXME files found.**

### What's In Flight

The user has been on a multi-day arc:

1. Built the GUI topology + metrics system
2. Built the Pydantic AI troubleshooting agent
3. Ran a real IMS 408 failure investigation, documented the RCA
4. Wrote deep architectural reflections (`agent_design_reflections.md`, `rca_reflections.md`) that articulate a gated multi-phase orchestrator architecture
5. Created the empty `agentic_chaos/` directory — signaling intent to start this work

### Existing Known Pain Points

From `agent_design_reflections.md` and `rca_reflections.md`:

- IMS nodes (Kamailio) have **no Prometheus metrics** — only `kamcmd` stats
- UERANSIM/PyHSS have **no metrics endpoints**
- The existing troubleshooting agent is a **single flat agent** (no orchestrator, no phasing, no pruning)
- Context window exhaustion from log output is a known problem
- The existing agent uses **Pydantic AI + Anthropic Claude**, NOT ADK + Gemini

### Taste Calibration (for EXPANSION mode)

**Well-designed patterns to emulate:**

1. `operate/agentic_ops/tools.py` — clean separation of tool implementations from agent definition, good error handling, `_truncate()` for context management, shell quoting
2. `operate/gui/metrics.py` — elegant collector pattern with cache TTL, parallel async gather, consistent `{metrics, badge, source}` return shape

**Anti-patterns to avoid:**

1. The hardcoded `PYHSS_IP=172.22.0.34` default that was wrong — shows the danger of hardcoded defaults that diverge from `.env`
2. The existing `_collect_pyhss()` hitting `/auc/` (wrong endpoint) — shows the danger of code written without verification

### Retrospective Check

The `agent_design_reflections.md` is essentially the user's own architectural review of what a multi-agent system should look like. The chaos monkey plan directly builds on these reflections. The user has already done significant design thinking — this isn't a blank-slate request.

---

## STEP 0: Nuclear Scope Challenge + Mode Selection

### 0A. Premise Challenge

**Is this the right problem to solve?**

Yes, emphatically. The user has articulated the motivation clearly: you can't train an autonomous operations agent without operational failure data, and you can't get operational failure data from a healthy network. Chaos engineering is the established discipline for this. The 5G/IMS stack is uniquely suited — it has 20 containers with complex interdependencies across multiple protocol layers (SIP, Diameter, GTP-U, NGAP, PFCP), meaning failures cascade in non-obvious ways that create rich training data.

**What's the actual outcome?** Two things:

1. **Near-term**: A system that can create controlled, repeatable failures across the stack at various blast radii
2. **Long-term**: A training data pipeline that captures `(failure scenario, symptoms, metrics, logs, root cause)` tuples to train an autonomous RCA agent

**What happens if we do nothing?** The user is stuck manually breaking things and manually collecting data. Given the 20-container stack with ~40 edges, the failure space is enormous — manual exploration is infeasible.

### 0B. Existing Code Leverage

| Sub-problem | Existing code | Reuse? |
|---|---|---|
| Docker container manipulation (stop/kill/pause) | `_run()` in server.py, `_shell()` in tools.py | Yes — same `asyncio.create_subprocess_exec` pattern |
| Network fault injection (tc/netem) | None | New — needs `docker exec` + `tc qdisc` |
| Metrics collection before/during/after | `MetricsCollector` in metrics.py | Yes — the collector already aggregates Prometheus + kamcmd + PyHSS |
| Log collection | `read_container_logs`, `search_logs` in tools.py | Yes — tools already exist for this |
| Container status | `get_network_status` in tools.py | Yes |
| Subscriber queries | `query_subscriber` in tools.py | Yes |
| Network topology awareness | `topology.py` — full graph model with `path_between()`, `impact_of()`, `neighbors()` | **Critical reuse** — `impact_of(node_id)` already computes blast radius |

The existing codebase is well-positioned. The topology graph, metrics collector, and troubleshooting tools are all reusable. The new work is: (a) the fault injection primitives, (b) the ADK agent orchestration layer, (c) the data collection/recording pipeline.

### 0C. Dream State Mapping

```
CURRENT STATE                   THIS PLAN                    12-MONTH IDEAL
─────────────────────          ──────────────────────        ──────────────────────
Manual operations              ADK chaos orchestrator         Fully autonomous
  → Human breaks things          → Agents inject faults       → Chaos runs on schedule
  → Human reads logs             → Agents collect data        → RCA agent diagnoses
  → Human does RCA               → Structured recordings      → Remediation agent fixes
                                                              → Runs in GCP with
Pydantic AI single agent       ADK multi-agent                  scale-out workers
  → Claude, no phasing           → Gemini (or any LLM)
  → Context exhaustion           → Orchestrator + specialists  Training data pipeline
                                 → Shared state               → (scenario, symptoms,
Empty agentic_chaos/           Fault injection primitives       root_cause) dataset
                                 → Container lifecycle         → Fine-tuning / eval
                                 → Network degradation           for RCA agent
                                 → Software faults
                                 → Blast radius control
```

This plan is the **critical middle column**. It's the bridge from "human-in-the-loop learning tool" to "autonomous operations platform." Without it, the 12-month vision is unreachable.

### 0D. Mode-Specific Analysis

#### 10x Check: What's 10x more ambitious for 2x the effort?

The 10x version isn't just "inject faults" — it's a **full chaos engineering platform** that:

1. **Generates failure scenarios** autonomously (an LLM agent that designs novel failure combinations based on the topology graph)
2. **Records structured episodes** (pre-fault baseline, fault injection, symptom evolution over time, metrics snapshots at intervals, full log capture, manual or automated RCA label)
3. **Replays episodes** for training (given the same starting state, replay the same fault and verify the RCA agent can diagnose it)
4. **Runs campaigns** (a sequence of escalating failures: warm up with single-NF kills, progress to multi-NF cascades, culminate in full-stack chaos)
5. **Scores the RCA agent** against recorded episodes (eval framework)

The 2x effort upgrade: add the recording/episode format and the campaign runner. These are the pieces that make the data useful for training, not just for one-off testing.

#### Platonic Ideal

The best version of this system would feel like a **flight simulator for telecom operators**. You'd sit at the GUI, click "Run Campaign: IMS Registration Resilience", and watch as the chaos system:

- Injects a P-CSCF network partition
- The topology view shows the edge going red in real-time
- The RCA agent detects the failure, diagnoses it, and recommends remediation
- The chaos system heals the fault
- The next scenario starts automatically
- At the end, you get a scorecard: "RCA agent correctly diagnosed 7/10 failure scenarios"

A new engineer joining in 6 months would look at this and say: "This is how you learn telecom — you break it and watch the AI explain what happened."

#### Delight Opportunities (30 minutes each)

1. **"Break This" button on topology nodes** — right-click any node in the GUI, get a menu of fault types (kill, pause, add 500ms latency, drop 30% packets). Instant gratification.
2. **Pre-built scenario library** — 10 curated failure scenarios with descriptions ("Simulate a gNB radio link failure", "Simulate a Diameter peer timeout between S-CSCF and HSS"). One-click run.
3. **Fault timeline overlay** — on the topology view, show a timeline bar at the bottom marking when faults were injected and healed, like a video editor timeline.
4. **Blast radius preview** — before injecting a fault, show which edges and downstream nodes will be affected (reuse `topology.impact_of()`).
5. **Episode export** — export a completed chaos episode as a self-contained JSON file that can be loaded by the RCA agent eval framework.

#### Temporal Interrogation

```
HOUR 1 (foundations):
  - ADK project structure decision: separate package or inside operate/?
  - Python version compatibility (ADK requires 3.10+, existing .venv is 3.12 ✓)
  - Model choice: Gemini for orchestrator (ADK-native) vs Claude via LiteLLM?
  - How do fault injection tools get Docker access? (same host, docker exec)

HOUR 2-3 (core logic):
  - tc/netem requires NET_ADMIN capability — do the containers have it?
    (They likely DON'T. Need --cap-add=NET_ADMIN or run tc from host netns)
  - How to inject latency on a specific container's network?
    (docker exec + tc, or nsenter into container's network namespace)
  - State management: how does the chaos orchestrator track what faults are active?
  - Healing/rollback: how to guarantee faults are cleaned up even if the agent crashes?

HOUR 4-5 (integration):
  - How does the chaos system integrate with the existing GUI?
  - WebSocket endpoint for chaos status? New API endpoints?
  - How does it integrate with the existing MetricsCollector for before/after snapshots?

HOUR 6+ (polish/tests):
  - Testing chaos tools without actually breaking the stack during development
  - How to test on a laptop vs GCP — what changes?
  - Episode recording format — what schema?
```

### 0E. ADK Technical Assessment

#### What ADK Gives Us

ADK (Google Agent Development Kit) is an open-source Python framework (`pip install google-adk`) with:

- **`LlmAgent`**: An agent backed by an LLM (Gemini natively, Claude/others via LiteLLM)
- **`SequentialAgent`**: Executes sub-agents in order, passing shared state
- **`ParallelAgent`**: Executes sub-agents concurrently, merging results via shared state
- **`LoopAgent`**: Iterates sub-agents until a termination condition (escalate) or max iterations
- **Shared `session.state`**: All agents in an invocation share a state dict. Agent A writes `state['data']`, Agent B reads `{data}` in its instruction
- **`output_key`**: An agent's output is automatically saved to `state[output_key]`
- **`AgentTool`**: Wrap any agent as a callable tool for another agent
- **`transfer_to_agent`**: LLM-driven dynamic delegation to sub-agents
- **Deployment**: Local Docker, Cloud Run, GKE, Vertex AI Agent Engine

#### ADK + Claude (Model Agnostic)

ADK supports non-Gemini models via:
- **LiteLLM integration**: `pip install google-adk[litellm]` — provides access to Claude, GPT-4, etc.
- **Direct Anthropic wrapper**: ADK has a native Claude wrapper class

This means the chaos orchestrator can use **Gemini for orchestration** (fast, cheap, ADK-native) while specialist agents could use **Claude for deep analysis** if needed.

#### How ADK Maps to the Chaos Monkey Architecture

```
                        ┌──────────────────────────────┐
                        │   CHAOS ORCHESTRATOR          │
                        │   (ADK LlmAgent or            │
                        │    SequentialAgent)            │
                        │                               │
                        │   Responsibilities:            │
                        │   - Select failure scenario    │
                        │   - Capture baseline metrics   │
                        │   - Dispatch fault agents      │
                        │   - Monitor symptoms           │
                        │   - Record episode             │
                        │   - Heal faults                │
                        └──────────┬───────────────────┘
                                   │
              ┌────────────────────┼───────────────────────┐
              │                    │                        │
    SequentialAgent         ParallelAgent            SequentialAgent
    "Pre-Flight"           "Fault Injection"          "Post-Flight"
              │                    │                        │
    ┌─────────┴────┐     ┌────────┼────────┐     ┌────────┴────────┐
    │ Baseline     │     │        │        │     │ Symptom         │
    │ Collector    │     │ Fault  │ Fault  │     │ Collector       │
    │ (metrics +   │     │ Agent  │ Agent  │     │ (metrics +      │
    │  health)     │     │  #1    │  #2    │     │  logs + health) │
    └──────────────┘     └────────┴────────┘     └─────────────────┘
```

The key ADK primitives map directly:
- **`SequentialAgent`** for the overall episode flow: baseline → inject → observe → heal → record
- **`ParallelAgent`** for concurrent fault injection (multi-NF failures) and concurrent metric collection
- **`LoopAgent`** for symptom monitoring (poll until timeout or detection)
- **`LlmAgent`** for the orchestrator's scenario selection and the specialist fault agents' decisions
- **`session.state`** for passing baseline metrics to the symptom collector, active faults to the healer, etc.

### 0F. Mode Selection — Three Options

#### Option A: SCOPE EXPANSION (Recommended)

Dream big. Design the full chaos engineering platform:

- Multi-agent fault injection with ADK (orchestrator + specialist agents)
- Episode recording with structured schema (baseline, faults, symptoms, resolution)
- Campaign runner (sequences of escalating failures)
- GUI integration (fault controls on topology nodes, timeline overlay)
- Training data pipeline (episodes as eval dataset for RCA agent)
- Laptop + GCP deployment

**Effort**: ~3-4 weeks of focused work
**Risk**: Larger surface area, more integration points
**Payoff**: A complete platform that produces training data and looks beautiful

#### Option B: HOLD SCOPE

Lock scope to exactly what was described in the requirements:

- Multi-agent fault injection with ADK
- Individual agents for each failure type
- Controlled blast radius (single NF → multi-NF → full stack)
- Laptop + GCP deployment
- No episode recording, no campaigns, no GUI integration

**Effort**: ~1-2 weeks
**Risk**: Low — focused scope
**Payoff**: Working fault injection, but no structured data output for training

#### Option C: SCOPE REDUCTION

Minimum viable chaos:

- A single orchestrator agent (not multi-agent) that can: kill/pause containers, add network latency via tc/netem, and restore
- CLI-only, no GUI integration
- No ADK — just extend the existing Pydantic AI pattern
- No recording, no campaigns

**Effort**: ~3-5 days
**Risk**: Lowest
**Payoff**: Quick wins, but doesn't build toward the 12-month vision, and doesn't use ADK as requested

---

## KEY DESIGN DECISIONS TO RESOLVE

These decisions need to be made regardless of scope mode:

### 1. Network Fault Injection Mechanism

**The problem**: `tc qdisc` (netem) requires `NET_ADMIN` capability inside the container. Most Docker Compose stacks don't grant this by default.

**Options**:
- **A) `nsenter` from the host** into the container's network namespace. No container modification needed. The chaos agent runs `nsenter -t $(docker inspect -f '{{.State.Pid}}' amf) -n tc qdisc add dev eth0 root netem delay 500ms`. Works on laptop. Requires host-level access (which we have since we're running docker commands).
- **B) Add `cap_add: NET_ADMIN`** to the docker-compose files. Cleaner from inside the container but requires modifying the compose files.
- **C) Use Pumba** (a dedicated chaos tool for Docker). Handles tc/netem via its own sidecar. Adds a dependency but battle-tested.

**Recommendation**: Option A (`nsenter`). No compose changes, works with the existing stack as-is, and the chaos agent already has host-level Docker access.

### 2. Fault Rollback / Healing Guarantee

**The problem**: If the chaos agent crashes mid-experiment, faults remain injected. A container with 500ms latency stays that way forever.

**Options**:
- **A) Fault registry with atexit/signal handlers** — maintain a list of active faults, register cleanup on SIGINT/SIGTERM/atexit
- **B) TTL-based faults** — every fault has a max duration; a background timer heals it automatically
- **C) Both A + B** — belt and suspenders

**Recommendation**: C (both). The registry handles graceful shutdown; TTL handles crashes.

### 3. ADK vs Pydantic AI Coexistence

**The problem**: The existing `agentic_ops` uses Pydantic AI + Claude. The new `agentic_chaos` uses ADK + Gemini. Two agent frameworks in one project.

**Options**:
- **A) Keep both** — they serve different purposes (troubleshooting vs chaos). They share tool implementations but have separate agent definitions.
- **B) Migrate agentic_ops to ADK** — unify on one framework. Significant rework.
- **C) Use ADK for chaos, but have the chaos orchestrator invoke the Pydantic AI troubleshooting agent as a subprocess** for RCA scoring.

**Recommendation**: A (keep both). They're independent subsystems. The chaos tools can reuse the same shell helpers and Docker patterns from `agentic_ops/tools.py` without coupling the frameworks. Later, if ADK proves better, migration is straightforward because the tool implementations are framework-agnostic.

### 4. Failure Taxonomy

What types of failures should the system support? Here's a proposed taxonomy:

```
FAILURE TAXONOMY
─────────────────────────────────────────────────────────────────────
Layer           │ Failure Type          │ Mechanism           │ Blast
─────────────────────────────────────────────────────────────────────
Container       │ Kill (SIGKILL)        │ docker kill         │ Single NF
                │ Stop (graceful)       │ docker stop         │ Single NF
                │ Pause (freeze)        │ docker pause        │ Single NF
                │ Restart               │ docker restart      │ Single NF
─────────────────────────────────────────────────────────────────────
Network         │ Latency               │ tc netem delay      │ Single NF
                │ Jitter                │ tc netem delay +    │ Single NF
                │                       │   jitter            │
                │ Packet loss           │ tc netem loss       │ Single NF
                │ Packet corruption     │ tc netem corrupt    │ Single NF
                │ Bandwidth limit       │ tc tbf              │ Single NF
                │ Network partition     │ iptables DROP       │ Edge
                │ DNS failure           │ kill dns container  │ Global
─────────────────────────────────────────────────────────────────────
Application     │ Config corruption     │ sed + restart       │ Single NF
                │ Database wipe         │ mongosh dropDB      │ Global
                │ Subscriber deletion   │ mongosh/PyHSS API   │ Single UE
                │ Certificate expiry    │ replace cert files  │ Single NF
─────────────────────────────────────────────────────────────────────
Compound        │ Rolling restart       │ Sequential kills    │ Multi-NF
                │ Cascading failure     │ Kill + latency      │ Multi-NF
                │ Split brain           │ Partition subsets   │ Multi-NF
                │ Upgrade simulation    │ Stop + config +     │ Multi-NF
                │                       │   restart           │
─────────────────────────────────────────────────────────────────────
```

### 5. Proposed Directory Structure

```
operate/agentic_chaos/
├── __init__.py
├── orchestrator.py          # ADK SequentialAgent: baseline → inject → observe → heal
├── agents/
│   ├── __init__.py
│   ├── container_agent.py   # Kill/stop/pause/restart specialist
│   ├── network_agent.py     # tc/netem/iptables specialist
│   ├── application_agent.py # Config corruption, DB faults specialist
│   └── compound_agent.py    # Multi-step failure sequences
├── tools/
│   ├── __init__.py
│   ├── docker_tools.py      # Container lifecycle: kill, stop, pause, restart
│   ├── network_tools.py     # tc qdisc, iptables, nsenter wrappers
│   ├── application_tools.py # Config edits, DB operations
│   └── observation_tools.py # Metrics snapshots, log capture, health checks
├── models.py                # Pydantic models: FaultSpec, Episode, Baseline, etc.
├── fault_registry.py        # Track active faults, TTL, cleanup on exit
├── recorder.py              # Episode recording: baseline + faults + symptoms → JSON
├── scenarios/
│   ├── __init__.py
│   └── library.py           # Pre-built failure scenarios
├── prompts/
│   └── orchestrator.md      # System prompt for the chaos orchestrator LlmAgent
└── README.md
```

### 6. Proposed Episode Schema

```json
{
  "episode_id": "ep_20260318_143022_pcscf_latency",
  "timestamp": "2026-03-18T14:30:22Z",
  "scenario": {
    "name": "P-CSCF Network Latency",
    "description": "Inject 500ms latency on P-CSCF to simulate WAN degradation",
    "blast_radius": "single_nf",
    "target_nodes": ["pcscf"],
    "affected_edges": ["pcscf→icscf", "pcscf→scscf", "e2e_ue1→pcscf", "e2e_ue2→pcscf"]
  },
  "baseline": {
    "timestamp": "2026-03-18T14:30:22Z",
    "phase": "ready",
    "metrics": { "amf": {...}, "smf": {...}, "pcscf": {...} },
    "container_status": { "amf": "running", "pcscf": "running", ... }
  },
  "faults_injected": [
    {
      "type": "network_latency",
      "target": "pcscf",
      "params": { "delay_ms": 500, "jitter_ms": 50 },
      "mechanism": "nsenter tc netem",
      "injected_at": "2026-03-18T14:30:25Z"
    }
  ],
  "observations": [
    {
      "timestamp": "2026-03-18T14:30:30Z",
      "metrics": {...},
      "symptoms": ["SIP REGISTER timeout at P-CSCF", "IMS registration latency >2s"]
    }
  ],
  "resolution": {
    "healed_at": "2026-03-18T14:31:25Z",
    "method": "tc qdisc del",
    "post_heal_metrics": {...}
  },
  "rca_label": {
    "root_cause": "P-CSCF network latency causing SIP transaction timeouts",
    "affected_components": ["pcscf", "icscf", "scscf"],
    "severity": "degraded"
  }
}
```

---

## WHAT ALREADY EXISTS (reusable)

| Component | Location | How it helps chaos engineering |
|---|---|---|
| Topology graph with `impact_of()` | `operate/gui/topology.py` | Compute blast radius before injecting a fault |
| MetricsCollector (Prometheus + kamcmd + PyHSS + MongoDB) | `operate/gui/metrics.py` | Capture baseline and post-fault metrics snapshots |
| Container log reader | `operate/agentic_ops/tools.py:read_container_logs()` | Capture logs during fault episodes |
| Cross-container log search | `operate/agentic_ops/tools.py:search_logs()` | Find symptoms across the stack |
| Network status checker | `operate/agentic_ops/tools.py:get_network_status()` | Verify pre/post fault container states |
| Subscriber query | `operate/agentic_ops/tools.py:query_subscriber()` | Verify subscriber state after DB faults |
| Env config reader | `operate/agentic_ops/tools.py:read_env_config()` | Discover IPs, topology for fault targeting |
| Docker shell helper | `operate/agentic_ops/tools.py:_shell()` | Run arbitrary docker/nsenter commands |
| .env IP mappings | `.env`, `operate/e2e.env` | Map container names to IPs for network faults |

---

## NOT IN SCOPE (for any mode)

| Item | Rationale |
|---|---|
| Migrating `agentic_ops` from Pydantic AI to ADK | Different subsystem, works fine as-is, can migrate later |
| Adding Prometheus exporters to Kamailio/UERANSIM | Valuable but orthogonal infrastructure work |
| Physical/hardware failure simulation | Not applicable to Docker containers |
| Multi-host distributed chaos (Kubernetes ChaosMonkey) | GCP version uses Cloud Run, not K8s mesh |
| Auto-remediation agent | The 12-month vision, not this phase |
| Real traffic generation (SIPp, iperf) | Useful but separate from fault injection |

---

## OPEN QUESTIONS FOR HOSSEIN

1. **Review mode**: EXPANSION (full platform with recording + campaigns + GUI) vs HOLD (fault injection + ADK multi-agent only) vs REDUCTION (single agent, CLI only)?

2. **Model choice for ADK orchestrator**: Gemini (ADK-native, fast, cheap) vs Claude via LiteLLM (consistent with existing agent, better reasoning)?

3. **NET_ADMIN approach**: `nsenter` from host (no compose changes) vs `cap_add` in compose files vs Pumba sidecar?

4. **Fault rollback**: Registry + TTL (belt and suspenders) vs simpler approach?

5. **GUI integration priority**: Should the chaos system integrate with the existing topology GUI from day one, or start CLI-only and add GUI later?

6. **Episode recording priority**: Is the training data pipeline (episode recording) a must-have for v1, or can it be deferred?

---

## SOURCES

- [ADK Documentation — Index](https://google.github.io/adk-docs/)
- [ADK Multi-Agent Systems](https://google.github.io/adk-docs/agents/multi-agents/)
- [ADK Workflow Agents](https://google.github.io/adk-docs/agents/workflow-agents/)
- [ADK Technical Overview](https://google.github.io/adk-docs/get-started/about/)
- [ADK Python Quickstart](https://google.github.io/adk-docs/get-started/python/)
- [ADK Claude Integration](https://google.github.io/adk-docs/agents/models/anthropic/)
- [ADK LiteLLM Integration](https://google.github.io/adk-docs/agents/models/litellm/)
- [ADK Deployment Options](https://google.github.io/adk-docs/deploy/)
- [ADK on PyPI](https://pypi.org/project/google-adk/)
- [ADK GitHub (Python)](https://github.com/google/adk-python)
- [Build Multi-Agent Systems with ADK (Google Blog)](https://cloud.google.com/blog/products/ai-machine-learning/build-multi-agentic-systems-using-google-adk)
- [Developer's Guide to Multi-Agent Patterns in ADK](https://developers.googleblog.com/developers-guide-to-multi-agent-patterns-in-adk/)
- [Pumba — Chaos Testing for Docker](https://github.com/alexei-led/pumba)
