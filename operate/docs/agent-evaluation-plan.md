# Agent Evaluation Plan: Chaos Monkey × Troubleshooting Agents

Using the `agentic_chaos` fault injection platform to systematically evaluate v1.5 and v3 troubleshooting agents across diverse failure types.

---

## Motivation

We spent 11 runs testing against a single fault (TCP/UDP protocol mismatch) and every agent version failed — not because of architecture, but because a Diameter `I_Open` red herring dominated the investigation. We need a broader evaluation across different fault classes to understand which failures the agents handle well and which need architectural guardrails.

---

## Evaluation Framework

### Running a Scenario

Each scenario is run individually, on-demand, via the CLI. This gives full control over when faults are injected, which agent version is tested, and how results are reviewed before moving to the next scenario.

**Step 1 — List available scenarios:**

```bash
python -m agentic_chaos.cli list-scenarios
```

**Step 2 — Run a single scenario against a specific agent:**

```bash
# Run with v1.5 agent
python -m agentic_chaos.cli run "DNS Failure" --agent v1.5

# Run with v3 agent
python -m agentic_chaos.cli run "DNS Failure" --agent v3
```

Each run executes the full orchestrator pipeline:

```
baseline → inject → observe → challenge → heal → record
```

The orchestrator captures a pre-fault baseline, injects the fault(s), observes symptoms during the observation window, invokes the troubleshooting agent under test (the "challenge" step), heals all faults, and records the complete episode. Every step is recorded — nothing is lost.

**Step 3 — Review results:**

```bash
# List all recorded episodes
python -m agentic_chaos.cli list-episodes

# Show full details of a specific episode
python -m agentic_chaos.cli show-episode ep_20260324_143022_dns_failure
```

**Emergency — heal all active faults if something goes wrong:**

```bash
python -m agentic_chaos.cli heal-all
```

### Per-Scenario Procedure

For each scenario, the operator follows this workflow:

```
1. Bring up clean stack (docker compose up)
2. Register both UEs, verify calls work (establishes the healthy baseline)
3. Run the scenario against v1.5:
     python -m agentic_chaos.cli run "<scenario>" --agent v1.5
   → Pipeline runs: baseline → inject → observe → challenge → heal → record
   → Outputs: JSON log + markdown summary in agentic_ops/docs/agent_logs/
4. Verify stack is healthy again (faults were healed in step 3)
5. Run the same scenario against v3:
     python -m agentic_chaos.cli run "<scenario>" --agent v3
   → Outputs: JSON log + markdown summary in agentic_ops_v3/docs/agent_logs/
6. Compare the two markdown summaries side by side
```

Running scenarios one at a time is deliberate: it allows reviewing each result, catching issues early, and adjusting agent prompts between runs if needed.

### Recording Requirements

Every scenario run produces two output files per agent, stored under the respective agent's log directory:

**JSON episode log** — the machine-readable record:
- File: `agentic_ops/docs/agent_logs/run_<timestamp>_<scenario_slug>.json` (v1.5)
  or `agentic_ops_v3/docs/agent_logs/run_<timestamp>_<scenario_slug>.json` (v3)
- Contains: episode ID, scenario definition, baseline snapshot, injected faults, observation iterations with metrics deltas and log samples, the agent's diagnosis (root cause, affected components, severity, confidence), scoring results across all dimensions, resolution details, and timing

**Markdown summary** — the human-readable analysis:
- File: same path as JSON but with `.md` extension
- Contains: plain-English narrative of what happened — what fault was injected, what symptoms appeared, what the agent concluded, whether it was right or wrong, where it went off track (if it did), and what the scoring breakdown looks like
- This is the primary artifact for reviewing agent performance and communicating results

Both files are critical. The JSON is the source of truth for programmatic comparison across runs. The markdown is how we actually understand what happened and make decisions about agent improvements.

### Scoring Dimensions (from `agentic_chaos/scorer.py`)

| Dimension | What It Measures |
|---|---|
| root_cause_correct | Did the agent identify the actual fault? |
| component_overlap | Did it name the right container(s)? |
| severity_correct | Did it assess impact correctly? |
| fault_type_identified | Did it identify the class of failure (network, config, crash)? |
| confidence_calibrated | Is confidence level justified by evidence quality? |

---

## Phase 1: Easy Scenarios (Build Confidence)

Start with faults that produce obvious, unambiguous signals in metrics and container status. These validate that the basic investigation methodology works before we move to subtle failures.

### 1.1 DNS Container Kill

**Fault:** `docker kill dns`
**Expected symptoms:** IMS domain resolution fails. New registrations fail. Existing calls may survive (cached DNS) but new call setup fails.
**Metrics signal:** DNS container shows `exited` in `get_network_status()`. Obvious in triage.
**Why it's easy:** Single container, immediate impact, clear in both metrics and logs. No red herrings.
**What it tests:** Can the agent identify a container outage and connect it to the observed failure?

### 1.2 S-CSCF Crash

**Fault:** `docker kill scscf`
**Expected symptoms:** IMS registration fails. Call routing fails. P-CSCF logs show upstream errors.
**Metrics signal:** S-CSCF disappears from container status. Kamailio stats unavailable.
**Why it's easy:** Critical IMS component, failure is immediate and visible everywhere.
**What it tests:** Can the agent trace the failure to a missing component rather than a misconfiguration?

### 1.3 gNB Radio Link Failure

**Fault:** `docker kill nr_gnb`
**Expected symptoms:** UEs lose 5G connectivity entirely. No signaling, no data plane.
**Metrics signal:** `ran_ue = 0`, `gnb = 0` in Prometheus. All UE operations fail.
**Why it's easy:** Most fundamental failure — everything stops. Hard to misdiagnose.
**What it tests:** Does triage correctly identify the 5G access layer as the problem?

### 1.4 MongoDB Gone

**Fault:** `docker kill mongo`
**Expected symptoms:** New subscriber lookups fail. UDR/UDM can't access subscriber data. Existing sessions may continue but no new registrations.
**Metrics signal:** MongoDB container `exited`. Subscriber count returns error.
**Why it's easy:** Database outage, clear operational impact, obvious in container status.
**What it tests:** Does the agent check subscriber infrastructure, not just IMS signaling?

---

## Phase 2: Medium Scenarios (Network Faults)

Faults that don't show up in container status but are visible in metrics and timing. Tests whether agents can reason about progressive degradation and network-layer issues.

### 2.1 P-CSCF Latency (Escalating)

**Fault:** Inject increasing latency on P-CSCF: 100ms → 250ms → 500ms → 1000ms
**Expected symptoms:** SIP transactions slow down. At ~500ms, T1 timer retransmissions start. At ~1000ms, transactions time out.
**Metrics signal:** Kamailio `tm.stats` shows retransmissions. Diameter response times increase.
**What it tests:** Can the agent detect progressive degradation before a hard failure? Does triage catch elevated response times?

### 2.2 IMS Network Partition

**Fault:** iptables partition between I-CSCF and PyHSS
**Expected symptoms:** I-CSCF can't reach HSS for LIR/UAR. Call routing fails. Registration fails.
**Metrics signal:** Diameter timeouts increase. No container down — everything appears running.
**What it tests:** Can the agent distinguish "container is running but unreachable" from "container is misconfigured"? This is the closest analogue to our TCP mismatch — the symptoms look like a config error but the cause is network.

### 2.3 Data Plane Degradation

**Fault:** Inject 20% packet loss on UPF's GTP interface
**Expected symptoms:** Voice quality degrades. RTP packets lost. Calls connect but audio is choppy/silent.
**Metrics signal:** GTP packet counters still nonzero but lower than expected. RTPEngine may show loss stats.
**What it tests:** Can the agent reason about quality degradation vs. hard failure?

---

## Phase 3: Hard Scenarios (Subtle and Cascading)

Faults where the symptom and root cause are in different domains, or multiple things break at once.

### 3.1 Cascading IMS Failure

**Fault:** Kill PyHSS, then observe cascading effects on I-CSCF, S-CSCF, registration, and calls.
**Expected symptoms:** Multiple IMS nodes report errors. The agent must trace back to the single root cause (HSS down) despite seeing errors at I-CSCF, S-CSCF, and P-CSCF.
**What it tests:** Can the agent separate root cause from cascading symptoms? This is the "500 at I-CSCF is a symptom" pattern we struggled with.

### 3.2 AMF Restart (Transient Failure)

**Fault:** `docker restart amf` — brief outage followed by recovery
**Expected symptoms:** UEs briefly detach, then re-register. Some sessions may be lost. A brief window of errors followed by recovery.
**What it tests:** Can the agent investigate a transient failure that has already resolved by the time it runs? The evidence is only in logs, not in current metrics.

### 3.3 Subscriber Deletion (Application Fault)

**Fault:** Delete UE2's subscriber record from PyHSS while registered
**Expected symptoms:** UE2 is registered (P-CSCF has contact) but HSS has no record. Call routing fails because LIR returns "user not found."
**What it tests:** The subscriber data specialist's ability to detect database/registration state mismatch.

### 3.4 Config Corruption

**Fault:** Corrupt a critical config parameter on a running container (e.g., wrong PFCP address on SMF)
**Expected symptoms:** Specific functionality breaks while everything else appears healthy. Similar to the TCP mismatch — subtle config error with symptoms elsewhere.
**What it tests:** The agent's ability to inspect running configs and find mismatches. This is the failure class we struggled with most.

---

## Pre-Evaluation: Fix the Diameter I_Open Issue

Before running any evaluation, we need to determine whether the Diameter `I_Open` state between I-CSCF and HSS persists across stack restarts. If it does, it will contaminate every evaluation run — the agent will fixate on it regardless of the actual injected fault.

**Action items:**
1. Bring up a fresh stack
2. Check `kamcmd cdp.list_peers` on I-CSCF — is it `R_Open` or `I_Open`?
3. If `I_Open` persists on a clean stack, investigate and fix the Diameter handshake
4. If it only appears after certain operations (e.g., container restarts), document the trigger

---

## Deliverables

After each evaluation phase:
1. **Per-run JSON + markdown pairs** in `agentic_ops/docs/agent_logs/` (v1.5) and `agentic_ops_v3/docs/agent_logs/` (v3) — one pair per scenario per agent
2. **Scoring comparison table** — v1.5 vs v3 across all scenarios
3. **Failure pattern taxonomy** — which fault classes each agent handles well vs. poorly
4. **Architectural recommendations** — which investigation steps need code enforcement vs. LLM judgment for each fault class

---

## Success Criteria

| Phase | Target |
|---|---|
| Phase 1 (easy) | Both agents score >80% on all 4 scenarios |
| Phase 2 (medium) | At least one agent scores >70% on 2 of 3 scenarios |
| Phase 3 (hard) | Identify specific architectural gaps; no score target |
| Overall | Clear understanding of which fault classes need code guardrails vs. LLM reasoning |

---

## Future Capabilities

These are not needed for the first iteration but will be added as the evaluation framework matures.

### Run-All Suite Execution

Add a `run-all` CLI command that executes every scenario (or a filtered subset) in sequence against a specified agent version, without manual intervention between runs:

```bash
# Run all scenarios against v3
python -m agentic_chaos.cli run-all --agent v3

# Run only Phase 1 (easy) scenarios
python -m agentic_chaos.cli run-all --agent v3 --phase 1

# Run only network fault scenarios
python -m agentic_chaos.cli run-all --agent v3 --category network
```

Each scenario in the suite would follow the same pipeline (baseline → inject → observe → challenge → heal → record) with an automatic stack health check between runs. The suite produces a roll-up summary in addition to the per-scenario JSON + markdown pairs.

This becomes important once the individual scenarios are proven reliable — running them manually first ensures we trust the platform before automating the full suite.

### Scenario Authoring

Add support for defining scenarios as standalone YAML files (rather than Python objects in `library.py`) so that new scenarios can be created or existing ones modified without touching code:

```yaml
# scenarios/dns_failure.yaml
name: DNS Failure
description: Kill the DNS server. IMS domain resolution breaks.
category: container
blast_radius: global
faults:
  - fault_type: container_kill
    target: dns
    ttl_seconds: 120
expected_symptoms:
  - IMS domain unresolvable
  - SIP routing failures
  - New registrations fail
observation_window_seconds: 30
ttl_seconds: 120
```

The scenario loader would read both `library.py` (built-in scenarios) and any `.yaml` files in the `scenarios/` directory, making it easy to add experimental scenarios or one-off tests without modifying the core library. This also makes scenario definitions more accessible to operators who aren't familiar with the Python codebase.

---

## Resolved: The Diameter I_Open Issue

**Status:** Investigated and determined to be a cosmetic interop quirk — not a real failure.

### What We Found

After restarting the I-CSCF and S-CSCF, `kamcmd cdp.list_peers` shows `I_Open` on both nodes immediately — before any traffic flows. However:

- **PyHSS logs** show both peers as `connectionStatus: connected` with successful validation
- **PyHSS processes 242+ Diameter messages per hour** across these connections
- **UE registration succeeds** — both UEs go through UAR/UAA (I-CSCF→HSS) and MAR/SAR (S-CSCF→HSS) over the same Diameter connections that show `I_Open`

### Root Cause

Kamailio's C-based CDP module and PyHSS's Python-based Diameter stack disagree on the state machine display. The TCP connection is established, CER/CEA are exchanged, and Diameter messages flow — but Kamailio's CDP doesn't transition its display state from `I_Open` to `R_Open`. This is likely due to stricter CEA validation in Kamailio's CDP than what PyHSS produces.

| Perspective | State Shown | Reality |
|---|---|---|
| Kamailio `cdp.list_peers` | `I_Open` | Misleading |
| PyHSS logs | `connected`, 242 msg/hr | Working |
| UE registration (UAR/UAA) | Succeeds | Proves connection works |

### Impact on Evaluation

The `I_Open` state is a **permanent cosmetic artifact** of this PyHSS/Kamailio combination. It will be visible in every evaluation run regardless of what fault is injected. Every AI agent that checks `cdp.list_peers` will see it.

### Decision: Leave As-Is, Document in Prompts

Rather than fixing the underlying interop issue, we treat `I_Open` as a known benign condition:

1. **Add to agent prompts:** Note that `I_Open` between Kamailio and PyHSS is a known display quirk in this stack. The connection is functional if UE registration succeeds.
2. **Useful as a test:** Can the agent distinguish a pre-existing benign condition from an injected fault? Agents that fixate on `I_Open` when the actual fault is a container kill or network partition are demonstrating poor reasoning.
3. **Fix later if needed:** If the evaluation shows `I_Open` consistently derails investigations across multiple fault types, revisit the Kamailio CDP source or PyHSS CEA implementation.
