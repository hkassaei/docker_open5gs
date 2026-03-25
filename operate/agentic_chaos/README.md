# Agentic Chaos Monkey

Controlled fault injection platform for the 5G SA + IMS Docker stack. Injects
faults, observes symptoms, records structured episodes, and optionally challenges
an RCA agent to diagnose the injected failures.

## Architecture

```
ChaosDirector (SequentialAgent)
  │
  ├── 1. BaselineCollector     → Metrics + container status snapshot
  ├── 2. FaultInjector         → Target → Inject → Verify per fault
  ├── 3. SymptomObserver       → Poll metrics/logs in a loop
  │       ├── SymptomPoller        (detect symptoms)
  │       └── EscalationChecker    (Boiling Frog: increase severity)
  ├── 4. ChallengeAgent        → Invoke RCA agent, score diagnosis
  ├── 5. Healer                → Reverse all faults via registry
  └── 6. EpisodeRecorder       → Write episode JSON to disk
```

## Quick Start

```bash
# Set Gemini API access
export GOOGLE_CLOUD_PROJECT="your-project"
export GOOGLE_CLOUD_LOCATION="northamerica-northeast1"
export GOOGLE_GENAI_USE_VERTEXAI="TRUE"

# List available scenarios
PYTHONPATH=operate operate/.venv/bin/python -m agentic_chaos.cli list-scenarios

# Run a scenario
PYTHONPATH=operate operate/.venv/bin/python -m agentic_chaos.cli run "DNS Failure"

# List recorded episodes
PYTHONPATH=operate operate/.venv/bin/python -m agentic_chaos.cli list-episodes

# Show episode details
PYTHONPATH=operate operate/.venv/bin/python -m agentic_chaos.cli show-episode ep_20260318_...

# Emergency: heal all active faults
PYTHONPATH=operate operate/.venv/bin/python -m agentic_chaos.cli heal-all
```

## 10 Pre-Built Scenarios

| # | Scenario | Blast Radius | What It Does |
|---|---|---|---|
| 1 | gNB Radio Link Failure | Single NF | Kill gNB — UEs lose radio |
| 2 | P-CSCF Latency | Single NF | 500ms latency on SIP edge proxy |
| 3 | S-CSCF Crash | Single NF | Kill SIP registrar/call controller |
| 4 | HSS Unresponsive | Single NF | Freeze PyHSS — Diameter timeouts |
| 5 | Data Plane Degradation | Single NF | 30% packet loss on UPF |
| 6 | MongoDB Gone | Global | Kill 5G subscriber store |
| 7 | DNS Failure | Global | Kill DNS — IMS routing breaks |
| 8 | IMS Network Partition | Multi-NF | iptables partition: P-CSCF ↔ I/S-CSCF |
| 9 | AMF Restart | Multi-NF | Stop AMF (upgrade simulation) |
| 10 | Cascading IMS Failure | Multi-NF | Kill HSS + 2s latency on S-CSCF |

## Fault Types

```
CONTAINER                  NETWORK                    APPLICATION
─────────                  ───────                    ───────────
container_kill             network_latency            config corruption
container_stop             network_loss               subscriber deletion
container_pause            network_corruption         collection drop
container_restart          network_bandwidth
                           network_partition
```

## Safety: The Triple Lock

Every fault is protected by three independent safety mechanisms:

1. **SQLite Registry** — Every fault is recorded with its heal command BEFORE
   injection. If injection fails, the record is cleaned up.

2. **TTL Reaper** — Background task auto-heals faults that exceed their
   time-to-live (default 120s).

3. **Signal Handlers** — On SIGINT/SIGTERM/exit, all active faults are
   healed synchronously. `heal-all` CLI is the manual escape hatch.

## Adaptive Escalation (Boiling Frog)

When `escalation=True` on a scenario, the system progressively increases
fault severity until symptoms appear:

```
Iteration 1: latency 100ms  → no symptoms → escalate
Iteration 2: latency 250ms  → no symptoms → escalate
Iteration 3: latency 500ms  → SIP T1 timer hit → SYMPTOMS DETECTED
```

This discovers the exact threshold at which protocols break.

## Challenge Mode

When `challenge_mode=True`, after observing symptoms the platform invokes
the `agentic_ops` troubleshooting agent (Pydantic AI + Claude) to diagnose
the failure. The agent sees symptoms but does NOT know what was injected.
Its diagnosis is scored against ground truth:

- **Root cause correct** — Did it identify the right container?
- **Component overlap** — Jaccard similarity of affected components
- **Severity correct** — Did it assess severity accurately?
- **Confidence calibration** — High confidence + correct = good

Requires `ANTHROPIC_API_KEY` for the RCA agent. Skipped gracefully if unavailable.

## Episode Recording

Each chaos run produces a JSON episode file in `episodes/`:

```json
{
  "schema_version": "1.0",
  "episode_id": "ep_20260318_143022_pcscf_latency",
  "scenario": { ... },
  "baseline": { "metrics": {...}, "container_status": {...} },
  "faults": [{ "verified": true, "mechanism": "nsenter tc ..." }],
  "observations": [{ "symptoms_detected": true, "metrics_delta": {...} }],
  "resolution": { "heal_method": "scheduled" },
  "rca_label": { "root_cause": "...", "failure_domain": "ims_signaling" },
  "challenge_result": { "score": { "total_score": 0.85 } }
}
```

These episodes are the **primary output product** — training data for
autonomous RCA models.

## Testing

```bash
# Run all tests (unit + functional + e2e)
GOOGLE_CLOUD_PROJECT=... GOOGLE_CLOUD_LOCATION=... GOOGLE_GENAI_USE_VERTEXAI=TRUE \
  operate/.venv/bin/python -m pytest operate/agentic_chaos/tests/ -v

# Unit tests only (no Docker needed)
operate/.venv/bin/python -m pytest operate/agentic_chaos/tests/test_models.py \
  operate/agentic_chaos/tests/test_observation_tools.py \
  operate/agentic_chaos/tests/test_verification_tools.py \
  operate/agentic_chaos/tests/test_symptom_filter.py \
  operate/agentic_chaos/tests/test_scorer.py \
  operate/agentic_chaos/tests/test_escalation.py \
  operate/agentic_chaos/tests/test_scenarios.py \
  operate/agentic_chaos/tests/test_cli.py -v
```

## API Endpoint

The GUI server exposes active faults for the topology overlay:

```
GET /api/chaos/faults → [{"fault_id": "...", "target": "pcscf", ...}]
```

## Prerequisites

- Python 3.12+
- `google-adk`, `aiosqlite` (see requirements.txt)
- Docker with the 5G+IMS stack running
- Passwordless sudo for `nsenter`, `tc`, `iptables`
- Gemini API via Vertex AI (GOOGLE_CLOUD_PROJECT, GOOGLE_GENAI_USE_VERTEXAI)
- ANTHROPIC_API_KEY (optional, for Challenge Mode)
