# AI Telecom Troubleshooting Agent — Plan Review

A comprehensive analysis of building an AI agent for autonomous network troubleshooting in a 5G SA + IMS stack.

**Scope: HOLD SCOPE** — Build a solid agent with 6 tools that can read logs, read configs, and produce diagnoses. No proactive monitoring, no remediation actions. Make it bulletproof.

**Key design constraints:**
- Model-agnostic: switch between Claude Opus, Sonnet, Gemini, GPT-4, etc. via configuration
- Framework: Pydantic AI (see [Framework Selection](#framework-selection) for rationale)
- Proper API access assumed (no Claude Code CLI dependency)
- Architecture supports future sub-agent decomposition

---

## Table of Contents

- [Pre-Review System Audit](#pre-review-system-audit)
- [The Triggering Event: The BYE Storm](#the-triggering-event-the-bye-storm-debugging-session)
- [Premise Challenge](#step-0-nuclear-scope-challenge)
- [Framework Selection](#framework-selection)
- [Architecture](#architecture)
- [Available Data Sources](#available-data-sources)
- [Tool Definitions](#tool-definitions-v1)
- [System Prompt Design](#system-prompt-design)
- [Sub-Agent Decomposition (Future)](#sub-agent-decomposition-future)
- [Key Design Decisions](#key-design-decisions)
- [Implementation Plan](#implementation-plan)
- [10x Vision (Deferred)](#10x-vision-deferred)
- [Peer Review Notes](#peer-review-notes)

---

## Pre-Review System Audit

### System State

- **Branch**: `master` (3 uncommitted file changes to pcscf/scscf configs)
- **No stashes, no TODOs/FIXMEs** in Python or shell code
- **Existing GUI tool**: `operate/gui/` — aiohttp server with WebSocket log streaming, UE controls, and a simple "AI Explain" button that sends logs to `claude --print`
- **Rich data sources**: 11 Open5GS log files, 20+ container `docker logs`, Prometheus metrics (9091 on 4 NFs), PyHSS REST API (:8080), MongoDB, MySQL, DNS zones, and configuration files for every network function
- **Excellent documentation**: `operate/docs/` contains detailed VoNR call flow traces, authentication flow docs, architecture overview — effectively a telecom knowledge base

### What's Already In Flight

- The VoNR Learning Tool GUI is functional but uncommitted (all under `operate/gui/` and `operate/scripts/`)
- No other branches or PRs

### Existing Pain Points Relevant to This Plan

1. The current "AI Explain" button is **single-container, single-shot** — it sends one UE's logs to Claude and gets a text explanation back. No cross-container correlation.
2. When the BYE storm was debugged, it required **manually** reading logs from `e2e_ue2`, `pcscf`, `scscf`, correlating timestamps, identifying stale transaction state, and applying a fix. That required ~10 tool calls and deep protocol knowledge. The current GUI can't do any of that.
3. There's no structured log format — each component (Open5GS, Kamailio, pjsua, UERANSIM) has its own log style. Correlation requires timestamp parsing and protocol-level understanding.

### Taste Calibration

**Well-designed patterns in this codebase:**

1. `operate/docs/vonr-call-flow.md` — Outstanding documentation. Real log excerpts annotated with protocol explanations. This is the gold standard for what the agent's output should look like.
2. `operate/scripts/provision.sh` — Clean separation of concerns: each database gets its own provisioning section, env vars are configurable, cleanup mode is built in.

**Anti-patterns to avoid:**

1. The current `handle_explain()` — fires `claude --print` as a subprocess with no context, no tools, no ability to investigate. It's a glorified chat completion, not an agent.
2. Hardcoded container names scattered across scripts and server.py — `REQUIRED_CONTAINERS`, `UE_CONTAINERS`, `GNB_CONTAINER` are defined in server.py but also implicitly assumed in every shell script.

---

## The Triggering Event: The BYE Storm Debugging Session

In a previous session, Claude Code was used to troubleshoot why UE2 couldn't register with IMS. The investigation flow was:

1. **Read UE2 logs** — saw 408 Request Timeout on REGISTER attempts
2. **Read P-CSCF logs** — discovered a flood of BYE retransmissions from a stale call session
3. **Correlated** — the BYE storm was consuming P-CSCF's transaction table, causing it to 408 new REGISTERs
4. **Root cause** — previous UE teardown mid-call left stale SIP dialog state in Kamailio's in-memory database
5. **Fix** — restart pcscf and scscf to clear state, then restart UE containers
6. **Result** — both UEs registered successfully within seconds

This required:
- Reading logs from 3+ containers
- Understanding SIP transaction state machines
- Recognizing that BYE retransmissions indicate stale dialog state
- Knowing that Kamailio doesn't automatically clean up dialogs when a UE disappears
- Knowing the fix (restart pcscf/scscf to clear in-memory state)

**This is exactly the kind of task where an LLM with tools excels** — it needs broad knowledge (telecom protocols), multi-source evidence gathering (reading different logs), and reasoning (correlating events across components).

---

## Step 0: Nuclear Scope Challenge

### 0A. Premise Challenge

**Is this the right problem to solve?**

Yes, emphatically. The troubleshooting pattern (multi-container log correlation + protocol knowledge + reasoning) maps perfectly to LLM tool-use agents.

**What would happen if we did nothing?** The user would continue to rely on Claude Code in ad-hoc conversations to troubleshoot issues. This works, but:
- Requires the user to know *which* containers to inspect
- No persistent knowledge of the specific stack's architecture
- Each conversation starts from zero context
- No reusable troubleshooting workflows

**Could a different framing yield a simpler solution?** Possibly — a rule-based monitoring system (e.g., Prometheus alerts + Grafana) could catch known failure modes. But it can't reason about novel issues, correlate SIP call flows across containers, or explain findings in plain English. The LLM approach handles the long tail of telecom failures that no rule system can enumerate in advance.

### 0B. Existing Code Leverage

| Sub-problem | Existing code | Reuse? |
|---|---|---|
| Reading container logs | `handle_logs_ws()`, `docker logs` CLI | Yes — the data access pattern exists |
| Reading config files | Configs mounted at `./amf/`, `./pcscf/`, etc. | Yes — file paths are known |
| Querying subscriber state | `provision.sh` has MongoDB + PyHSS API patterns | Yes — queries are documented |
| Prometheus metrics | `metrics/prometheus.yml` defines scrape targets | Yes — endpoints known |
| Protocol knowledge | `operate/docs/vonr-call-flow.md`, `authentication.md` | **Critical** — this IS the domain knowledge base |
| Container status | `handle_status()` / `_container_status()` | Yes — direct reuse |

**Nothing needs rebuilding.** The agent wraps existing access patterns with an LLM reasoning loop.

### 0C. Dream State Mapping

```
  CURRENT STATE                    THIS PLAN (v1)                   12-MONTH IDEAL
  ┌─────────────────────┐         ┌──────────────────────────┐     ┌──────────────────────────────┐
  │ Manual troubleshoot │         │ AI agent with tools:     │     │ Autonomous NOC operator:     │
  │ via Claude Code     │  --->   │ - reads all logs         │ --> │ - proactive anomaly detection│
  │ conversations       │         │ - correlates events      │     │ - auto-remediation           │
  │                     │         │ - understands protocols  │     │ - learning from past issues  │
  │ Single-shot "AI     │         │ - produces diagnoses     │     │ - multi-stack support (4G+5G)│
  │ Explain" button     │         │ - model-agnostic         │     │ - sub-agent decomposition    │
  └─────────────────────┘         └──────────────────────────┘     └──────────────────────────────┘
```

---

## Framework Selection

### Requirements

1. **Model-agnostic**: Switch between Claude Opus, Sonnet, Gemini, GPT-4, etc. via env var
2. **Tool use**: First-class support for custom Python tool functions
3. **Sub-agent ready**: Architecture must support future multi-agent decomposition
4. **GCP deployable**: Will eventually deploy on Cloud Run or GKE
5. **Python-based**: Existing codebase is Python (aiohttp)
6. **Streaming**: Must stream agent progress to WebSocket-connected browser GUI
7. **Lightweight**: Minimal dependency footprint

### Framework Comparison

| Criteria | LangGraph | CrewAI | Pydantic AI | Google ADK | OpenAI Agents SDK | smolagents |
|---|---|---|---|---|---|---|
| **Model agnostic** | Yes | Yes | Yes (100+ providers) | Gemini-optimized, others via LiteLLM | Yes (100+ LLMs) | Yes via LiteLLM |
| **Tool use quality** | Excellent | Good | Excellent (type-safe, Pydantic validation) | Excellent | Good | Good |
| **Sub-agent support** | Excellent (graph composition) | Excellent (role-based crews) | Good (delegation, handoff) | Good (hierarchical trees) | Good (handoffs) | Good (ManagedAgent) |
| **GCP deployment** | Neutral (containerize yourself) | Neutral | Neutral | **Excellent** (`adk deploy cloud_run`) | Neutral | Neutral |
| **Streaming** | Excellent | Good (no streaming tool calls) | Excellent (`run_stream_events()`) | Good | Good | Basic |
| **Lightweight** | **Heavy** (LangChain ecosystem) | Medium | **Light** (pydantic dep only) | Medium (Google ecosystem) | Light | Very light |
| **Debug/Test** | Good (requires LangSmith) | Medium | Excellent (pytest, Pydantic validation) | Good | Good | Basic |
| **Community** | 24.8k stars, v1.10 | 45.9k stars, v1.1 | 15.4k stars, v1.67 | 17k stars, ~1yr old | 18.4k stars | 25.5k stars |

### Eliminated

- **Anthropic Agent SDK**: Claude-only. Violates the model-agnostic requirement.
- **AutoGen / MS Agent Framework**: In transition (AutoGen → maintenance, MS Agent Framework at RC). Too risky.
- **LangGraph**: Too heavy. The graph abstraction adds conceptual overhead that doesn't match our use case. Good for complex branching workflows, over-engineered for "dispatch tools, gather results, synthesize."
- **smolagents**: Too minimal for multi-agent coordination. Code-generation approach (LLM writes Python) adds security risk.

### Decision: Pydantic AI

**Pydantic AI** is the strongest overall fit. Here's why:

1. **Model agnosticism is genuine and deep.** Swap between Claude Opus, Gemini, GPT-4 via a single config/env var change. Over 100 providers supported natively — no LiteLLM wrapper needed for major providers.

2. **Tool use is best-in-class for this use case.** Tools are typed Python functions with dependency injection. Pydantic validates tool call arguments against schemas before execution — when the LLM calls `read_container_logs(container="pcscf", lines="fifty")` instead of `lines=50`, you get a clean validation error, not a runtime crash deep in Docker.

3. **Sub-agent support is sufficient and growing.** Agent delegation and programmatic handoff patterns work for the IMS-log-reader / 5G-core-inspector / coordinator pattern. Less opinionated than CrewAI's role system, which is actually a benefit — full control over how agents coordinate in a domain as specific as telecom.

4. **Streaming is production-ready.** `run_stream_events()` yields typed `AgentStreamEvent` objects that map cleanly onto WebSocket messages. AG-UI protocol support provides a standardized way to pipe agent state to the browser GUI.

5. **Lightweight.** Core dependency is `pydantic`. No 50-package transitive dependency tree.

6. **Testing is natural.** Tools are regular Python functions — test with pytest. Agents have typed inputs and outputs — assert on them. Logfire integration for production observability.

7. **Credible team.** The Pydantic team has a track record of well-engineered, production-grade Python libraries. Framework at v1.67 with active monthly releases.

**Runner-up: OpenAI Agents SDK** — if Pydantic AI's multi-agent patterns prove insufficient during prototyping, this is the next lightest option with decent handoffs and broad model support.

### Model Configuration

Model selection via environment variable:

```bash
# .env or environment
AGENT_MODEL=anthropic:claude-sonnet-4-20250514    # Default
# AGENT_MODEL=anthropic:claude-opus-4-20250514    # For complex investigations
# AGENT_MODEL=google-gla:gemini-2.5-pro           # Google alternative
# AGENT_MODEL=openai:gpt-4o                       # OpenAI alternative
```

In code:

```python
from pydantic_ai import Agent
import os

agent = Agent(
    model=os.environ.get("AGENT_MODEL", "anthropic:claude-sonnet-4-20250514"),
    system_prompt=SYSTEM_PROMPT,
    tools=[...],
)
```

Switching models requires zero code changes — just update the env var and restart.

---

## Architecture

### v1: Single Agent (HOLD SCOPE)

```
┌───────────────────────────────────────────────────────────────────┐
│  Browser GUI (index.html)                                         │
│  [Investigate] button → WebSocket /ws/investigate                 │
│  ← Streams: tool calls, reasoning, diagnosis                     │
└──────────────┬────────────────────────────────────────────────────┘
               │ WebSocket
┌──────────────▼────────────────────────────────────────────────────┐
│  aiohttp server (server.py)                                       │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │  handle_investigate(request) → WebSocket handler             │ │
│  │    1. Receive user question via WebSocket                    │ │
│  │    2. Create TelecomAgent with model from env                │ │
│  │    3. Run agent with streaming                               │ │
│  │    4. Forward stream events to WebSocket                     │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │  TelecomAgent (operate/agentic-ops/agent.py)                 │ │
│  │                                                              │ │
│  │  pydantic_ai.Agent(                                          │ │
│  │      model = os.environ["AGENT_MODEL"],                      │ │
│  │      system_prompt = <telecom knowledge>,                    │ │
│  │      tools = [                                               │ │
│  │          read_container_logs,                                │ │
│  │          read_config,                                        │ │
│  │          get_network_status,                                 │ │
│  │          query_subscriber,                                   │ │
│  │          read_env_config,                                    │ │
│  │      ],                                                      │ │
│  │      result_type = Diagnosis,                                │ │
│  │  )                                                           │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │  Tools (operate/agentic-ops/tools.py)                        │ │
│  │                                                              │ │
│  │  Each tool is a typed Python function:                       │ │
│  │    async def read_container_logs(                            │ │
│  │        ctx: RunContext[AgentDeps],                            │ │
│  │        container: str,                                       │ │
│  │        tail: int = 200,                                      │ │
│  │        grep: str | None = None,                              │ │
│  │    ) -> str:                                                  │ │
│  │        ...                                                   │ │
│  │                                                              │ │
│  │  Dependencies injected via AgentDeps:                        │ │
│  │    - repo_root: Path                                         │ │
│  │    - env: dict[str, str]                                     │ │
│  │    - ws: WebSocketResponse (for progress streaming)          │ │
│  └──────────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────┘
               │
               │  subprocess / docker exec / HTTP
               ▼
┌──────────────────────────────────────────────────────────────────┐
│  Docker containers (20+)                                         │
│  mongo, nrf, scp, ausf, udr, udm, amf, smf, upf, pcf,          │
│  dns, mysql, pyhss, icscf, scscf, pcscf, rtpengine,             │
│  nr_gnb, e2e_ue1, e2e_ue2                                       │
└──────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
User question ──▶ Agent ──▶ LLM (model from env)
                              │
                              ▼
                      tool_use response
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
            read_container_logs   read_config
            (docker logs pcscf)   (cat pcscf.cfg)
                    │                   │
                    └─────────┬─────────┘
                              ▼
                      tool results back to LLM
                              │
                              ▼
                      LLM reasons, may call more tools
                              │
                              ▼
                      ... (loop until diagnosis)
                              │
                              ▼
                      Diagnosis (structured output)
                              │
                              ▼
                      WebSocket → Browser GUI
```

### Shadow Paths

```
User question
    │
    ▼
VALIDATION ──▶ AGENT LOOP ──▶ TOOL EXEC ──▶ LLM RESPONSE ──▶ OUTPUT
    │               │              │              │              │
    ▼               ▼              ▼              ▼              ▼
  [empty?]      [max turns?]  [container     [refusal?]     [ws closed?]
  [too long?]   [timeout?]     not found?]   [malformed?]   [encoding?]
                [API error?]  [docker         [empty?]
                [rate limit?]  socket gone?]  [token limit?]
                              [permission
                               denied?]
```

---

## Available Data Sources

An AI troubleshooting agent has access to an exceptionally rich set of data sources in this stack.

### Container Logs (via `docker logs`)

All 20+ containers output to stdout/stderr:

| Category | Containers | Log Format | Key Patterns |
|---|---|---|---|
| **5G Core** | amf, smf, upf, nrf, scp, ausf, udm, udr, pcf, bsf, nssf | Open5GS format: `[component] LEVEL: message` | Registration, PDU session, PFCP, N2/N4 |
| **IMS/SIP** | pcscf, scscf, icscf | Kamailio syslog: route names, SIP messages | REGISTER, INVITE, BYE, Diameter Cx |
| **IMS HSS** | pyhss | Python logging + SQL queries | Diameter LIR/MAR/SAR, subscriber lookups |
| **Media** | rtpengine | Custom format: session create/destroy | RTP offer/answer, port allocation |
| **RAN** | nr_gnb | UERANSIM format: `[category] level: message` | NGAP, GTP-U, N2 setup |
| **UEs** | e2e_ue1, e2e_ue2 | pjsua format: `HH:MM:SS.mmm file.c message` | SIP messages, registration, call state |
| **Support** | dns, mysql, mongo | Standard daemon logs | Zone queries, connection events |

### Open5GS Log Files (mounted at `./log/`)

Persistent file-based logs with more detail than `docker logs`:
- `amf.log` (258 KB), `smf.log` (134 KB), `upf.log` (57 KB), `scp.log` (342 KB)
- `nrf.log`, `ausf.log`, `udm.log`, `udr.log`, `pcf.log`, `bsf.log`, `nssf.log`

### Databases

| Database | Access Method | What It Contains |
|---|---|---|
| **MongoDB** (Open5GS) | `docker exec -i mongo mongosh open5gs` | 5G subscribers, slices, APNs, PCC rules |
| **MySQL** (IMS) | `docker exec -i mysql mysql` | IMS subscribers, authentication, S-CSCF assignments |
| **PyHSS REST API** | `curl http://localhost:8080/...` | APN list, subscribers, IMS subscribers, AUC entries |

### Prometheus Metrics

Scraped every 5s from: `amf:9091`, `smf:9091`, `pcf:9091`, `upf:9091`
- UE counts, session counts, connection attempts, errors, latencies

### Configuration Files

Every network function has configuration mounted from the host:

| Component | Config Path | Key Settings |
|---|---|---|
| AMF | `./amf/amf.yaml` | GUAMI, TAI, NGAP, security |
| SMF | `./smf/smf.yaml` | DNN sessions (internet/ims), DNS, PFCP |
| UPF | `./upf/upf.yaml` | PFCP, GTP-U, session subnets |
| P-CSCF | `./pcscf/pcscf.cfg` | SIP routing, IPsec, RTPEngine, N5 QoS |
| S-CSCF | `./scscf/scscf.cfg` | Auth algorithm, ISC filters, HSS queries |
| I-CSCF | `./icscf/icscf.cfg` | S-CSCF pool, Diameter routing |
| PyHSS | `./pyhss/config.yaml` | Diameter transport, PLMN, S-CSCF pool |
| DNS | `./dns/named.conf`, `./dns/ims_zone` | IMS domain SRV/A records |
| UERANSIM | `./ueransim/ueransim-gnb.yaml` | PLMN, TAC, core NF URIs |

### Environment Variables

| File | Contents |
|---|---|
| `.env` | Network IPs (all 40+ components), PLMN (MCC/MNC/TAC), subnets, ports, UPF config |
| `operate/e2e.env` | Test UE credentials (IMSI, Ki, OPc, MSISDN), SIP password |

### Network Topology

All containers on a single Docker bridge: `172.22.0.0/24` with fixed IPs.

```
UE (pjsua on uesimtun1:192.168.101.x)
  |
UERANSIM nr-ue (172.22.0.50/51)
  |
gNB (nr_gnb, 172.22.0.23)
  |
AMF (172.22.0.10) --- N1/NAS
  |
SMF (172.22.0.7) --- N4/PFCP ---> UPF (172.22.0.8)
  |                                   |
  |                            N6 (data plane to IMS via ogstun2)
  |                                   |
  +--- P-CSCF (172.22.0.21:5060) --- SIP traffic
       |
       S-CSCF (172.22.0.20:6060) <---> PyHSS (Diameter Cx)
       |
       I-CSCF (172.22.0.19:4060) <---> PyHSS (Diameter Cx)
       |
       RTPEngine (172.22.0.16) --- media proxy
```

---

## Existing Protocol Knowledge Base

The `operate/docs/` directory contains detailed documentation that forms the agent's domain knowledge:

### `vonr-call-flow.md`
- Complete end-to-end VoNR call trace with real log excerpts
- Phase 1: SIP signaling (INVITE → P-CSCF → S-CSCF → I-CSCF → S-CSCF → P-CSCF → UE2)
- Phase 2: Call answer (200 OK reverse path + RTPEngine media anchoring)
- Phase 3: Media flow (RTP through RTPEngine proxy ports)
- Phase 4: Session refresh (UPDATE keepalives)
- N5 QoS policy authorization (PCF interaction)
- Component-by-component role summary

### `authentication.md`
- Dual authentication domains (5G Core via MongoDB + IMS via PyHSS)
- 5G-AKA flow: UE → gNB → AMF → AUSF → UDM → UDR
- IMS auth flow: pjsua → P-CSCF → I-CSCF → S-CSCF → PyHSS (Diameter UAR/MAR/SAR)
- E2E test modification: MD5 Digest instead of IMS-AKA (pcscf.cfg and scscf.cfg changes)

### `overview.md`
- Full architecture: 5G Core, 4G EPC, IMS, RAN, Support services
- Docker Compose deployment files inventory
- Configuration & networking (`.env`, init scripts, exposed ports)
- Volume mounts & persistence

---

## Tool Definitions (v1)

For HOLD SCOPE, we start with 6 core investigation tools. No remediation tools — the agent diagnoses and recommends, but does not execute fixes.

### Tool 1: `read_container_logs`

```python
@agent.tool
async def read_container_logs(
    ctx: RunContext[AgentDeps],
    container: str,
    tail: int = 200,
    grep: str | None = None,
) -> str:
    """Read recent logs from a Docker container.

    Args:
        container: Container name (e.g. 'pcscf', 'scscf', 'e2e_ue1', 'amf').
        tail: Number of recent lines to return (default 200).
        grep: Optional pattern to filter log lines (case-insensitive).

    Returns:
        The log output as a string. Empty string if container not found.
    """
```

**What it accesses:** `docker logs --tail {tail} {container}`, optionally piped through grep.

**Why it's needed:** This is the primary evidence-gathering tool. Every troubleshooting session starts by reading container logs. The agent can read from any of the 20+ containers.

**Allowed containers:** All containers in the stack. The tool validates that the container name matches a known container before executing.

### Tool 2: `read_config`

```python
@agent.tool
async def read_config(
    ctx: RunContext[AgentDeps],
    component: str,
) -> str:
    """Read the configuration file for a network component.

    Args:
        component: One of 'amf', 'smf', 'upf', 'pcscf', 'scscf', 'icscf',
                   'pyhss', 'dns', 'ueransim-gnb', 'ueransim-ue'.

    Returns:
        The full configuration file content.
    """
```

**What it accesses:** Reads config files from the repo: `./amf/amf.yaml`, `./pcscf/pcscf.cfg`, etc.

**Why it's needed:** Configuration mismatches are a common root cause (e.g., IPsec enabled/disabled, auth algorithm mismatch, wrong IP addresses). The agent needs to compare expected vs. actual configuration.

### Tool 3: `get_network_status`

```python
@agent.tool
async def get_network_status(
    ctx: RunContext[AgentDeps],
) -> dict:
    """Get the status of all network containers.

    Returns:
        Dict with:
        - phase: 'ready' | 'partial' | 'down'
        - containers: {name: 'running' | 'exited' | 'absent'}
    """
```

**What it accesses:** `docker inspect -f '{{.State.Status}}' {container}` for each container.

**Why it's needed:** First thing to check — which containers are up/down? A downed container is immediately diagnostic.

### Tool 4: `query_subscriber`

```python
@agent.tool
async def query_subscriber(
    ctx: RunContext[AgentDeps],
    imsi: str,
    domain: str = "both",
) -> dict:
    """Query subscriber data from 5G core (MongoDB) and/or IMS (PyHSS).

    Args:
        imsi: The subscriber's IMSI (e.g. '001011234567891').
        domain: 'core' for 5G only, 'ims' for IMS only, 'both' for both.

    Returns:
        Dict with subscriber profiles from the requested domains.
        Missing subscribers are indicated (common root cause).
    """
```

**What it accesses:**
- MongoDB: `docker exec -i mongo mongosh open5gs --eval "db.subscribers.findOne({imsi: '{imsi}'})"`
- PyHSS REST API: `GET http://localhost:8080/subscriber/imsi/{imsi}` and `GET http://localhost:8080/ims_subscriber/ims_subscriber_imsi/{imsi}`

**Why it's needed:** Missing or misconfigured subscribers are a top-3 root cause. The agent needs to verify that the subscriber exists in both databases with correct credentials.

### Tool 5: `read_env_config`

```python
@agent.tool
async def read_env_config(
    ctx: RunContext[AgentDeps],
) -> dict:
    """Read network topology and UE credentials from environment files.

    Returns:
        Dict with:
        - network: IP addresses, PLMN, subnets
        - ue1: IMSI, MSISDN, IP
        - ue2: IMSI, MSISDN, IP
        - ims_domain: computed IMS domain
    """
```

**What it accesses:** Reads and parses `.env` and `operate/e2e.env`.

**Why it's needed:** The agent needs to know the network topology (IPs, PLMN, subscriber identities) to interpret log entries and correlate events.

### Tool 6: `search_logs`

```python
@agent.tool
async def search_logs(
    ctx: RunContext[AgentDeps],
    pattern: str,
    containers: list[str] | None = None,
    since: str | None = None,
) -> str:
    """Search for a pattern across multiple container logs.

    Unlike read_container_logs which reads the tail of one container,
    this tool searches across all (or specified) containers for a
    specific pattern. Essential for tracing a SIP Call-ID, IMSI, or
    error keyword across the entire stack.

    Args:
        pattern: Search pattern (case-insensitive). Can be a Call-ID,
                 IMSI, SIP method, error keyword, etc.
        containers: Optional list of containers to search. If None,
                    searches all known containers.
        since: Optional time filter (e.g. '5m', '1h', '2024-03-12T22:30:00').

    Returns:
        Matching lines grouped by container, with container name prefix.
        Example:
            [pcscf] 22:35:14 INVITE sip:001011234567892@...
            [scscf] 22:35:14 INVITE from 001011234567891
            [icscf] 22:35:14 LIR for 001011234567892
    """
```

**What it accesses:** `docker logs {container} --since {since} 2>&1 | grep -i {pattern}` for each container.

**Why it's needed:** `read_container_logs` with `tail=200` is insufficient for intermittent issues where the root cause occurred minutes before the symptom. This tool lets the agent trace a specific identifier (Call-ID, IMSI) or keyword (BYE, ERROR, 408) across the entire stack. This was identified as a gap in the Gemini peer review — the BYE storm investigation required manually checking multiple containers for related events. `search_logs` enables that in a single tool call.

**Example use cases:**
- `search_logs(pattern="BYE", containers=["pcscf", "scscf"])` — find BYE retransmissions
- `search_logs(pattern="001011234567892")` — trace all activity for UE2's IMSI across all containers
- `search_logs(pattern="408", since="10m")` — find recent timeout errors anywhere in the stack
- `search_logs(pattern="JyjjCuCEILH")` — trace a specific SIP Call-ID end-to-end

### Future Tools (status as of v1.5)

| Tool | Purpose | Status | Target |
|---|---|---|---|
| `query_prometheus(query)` | Execute PromQL queries for metrics | **DONE in v1.5** — Tool 7 | ✅ |
| `get_nf_metrics()` | Full stack metrics snapshot | **DONE in v1.5** — Tool 8 | ✅ |
| `run_kamcmd(container, command)` | Kamailio runtime state (Diameter peers, usrloc, stats) | **DONE in v1.5** — Tool 9 | ✅ |
| `read_running_config(container, grep)` | Read ACTUAL config from running container | **DONE in v1.5** — Tool 10 | ✅ |
| `check_process_listeners(container)` | TCP/UDP listener state | **DONE in v1.5** — Tool 11 | ✅ |
| `get_sip_dialog(call_id)` | Extract complete SIP transaction by Call-ID | Deferred — `search_logs` with Call-ID covers most cases | v2 |
| `get_correlated_timeline(since)` | Merge logs, normalize timestamps, sort | Deferred — becomes critical for sub-agent coordination in v2 | v2 |
| `record_fact(fact, confidence)` | Save finding to short-term memory | Deferred — critical for v2 multi-agent (specialists share findings) | v2 |
| `recall_similar_cases(symptoms)` | Search persistent memory of past diagnoses | Deferred — requires persistent storage | v2 |
| `restart_container(name)` | Restart a container | Deferred — remediation out of scope | v2+ |
| `exec_in_container(name, cmd)` | Run arbitrary command in container | Deferred — security concerns | v2+ |
| `read_log_file(component)` | Read Open5GS log files from `./log/` | Deferred — `read_container_logs` sufficient | v2 |
| `diff_config(component)` | Compare repo config vs running container config | Deferred — `read_running_config` partially addresses this | v2 |

**Note on native DB clients:** The v1 `query_subscriber` tool uses `docker exec mongosh` and PyHSS REST API. A future improvement is to use native Python clients (`pymongo`, `mysql-connector-python`) for cleaner structured output and reduced token cost. Deferred because it adds dependencies and requires direct network access to the databases, whereas `docker exec` works out of the box.

---

## System Prompt Design

The agent's system prompt includes telecom domain knowledge loaded from `operate/docs/`. It is structured as:

### 1. Role

> You are a senior telecom network engineer specializing in 5G SA and IMS troubleshooting. You have deep expertise in SIP, Diameter, NGAP, PFCP, and GTP-U protocols. You are investigating issues in a containerized 5G + IMS stack running Open5GS, Kamailio, PyHSS, UERANSIM, and RTPEngine.

### 2. Stack Architecture

Loaded from `operate/docs/overview.md` — component roles and network layout. **Does NOT hardcode IPs or container names.** The agent discovers the live topology at the start of each investigation via `read_env_config()` and `get_network_status()`.

### 3. Protocol Knowledge

Loaded from `operate/docs/vonr-call-flow.md` and `authentication.md` — call flow sequences, authentication patterns, SIP message structure.

### 4. Troubleshooting Methodology

```
1. ALWAYS start with read_env_config() + get_network_status()
   — discover the live topology: IPs, PLMN, subscriber identities
   — identify what's running/down
   — do NOT assume any hardcoded IPs or container names
2. Check UE logs first (closest to the symptom)
3. Trace upstream based on the problem domain:
   - Data plane: UE → gNB → AMF → SMF → UPF
   - IMS/SIP:   UE → P-CSCF → S-CSCF → I-CSCF → PyHSS
4. Use search_logs() to trace specific identifiers (Call-ID, IMSI)
   across multiple containers when correlating events
5. Check configurations when behavior doesn't match expectations
6. Check subscriber provisioning when auth/registration fails
```

**Critical prompt instruction:** The agent must call `read_env_config()` before interpreting any IP addresses or subscriber identities in logs. The topology is configuration-driven and may change between deployments.

### 5. Known Failure Patterns

| Pattern | Symptoms | Root Cause | Where to Look |
|---|---|---|---|
| BYE storm | Registration 408, P-CSCF overwhelmed | Stale SIP dialogs from mid-call teardown | pcscf logs for BYE retransmissions |
| Auth mismatch | Registration 401 loop | IMS-AKA vs MD5 config mismatch | scscf.cfg `REG_AUTH_DEFAULT_ALG` |
| Missing 5G subscriber | UE can't attach | IMSI not in MongoDB | `query_subscriber(imsi, domain='core')` |
| Missing IMS subscriber | UE attaches but SIP REGISTER rejected | IMSI not in PyHSS | `query_subscriber(imsi, domain='ims')` |
| DNS resolution failure | IMS domain unresolvable | Zone file missing records | dns container logs, `dns/ims_zone` |
| NGAP message 9 warning | `[ngap] error: Unhandled` in gNB | Expected — UERANSIM doesn't implement QoS modify | Not a real error; inform user |
| SDP parsing errors | `unrecognised option [-1]` in SMF/UPF | Cosmetic log noise, call still works | Not a real error; inform user |

### 6. Output Format

The agent produces a structured `Diagnosis`:

```python
class Diagnosis(BaseModel):
    summary: str                    # One-line summary
    timeline: list[TimelineEvent]   # Chronological events across containers
    root_cause: str                 # What went wrong and why
    affected_components: list[str]  # Which containers are involved
    recommendation: str             # What to do about it
    confidence: str                 # 'high' | 'medium' | 'low'
    explanation: str                # Plain-English educational explanation
```

---

## Sub-Agent Decomposition

**Status: v1 → v1.5 confirmed this is necessary. v2 plan now specified.**

v1 used a single agent. v1.5 added better tools and methodology to the single agent. The UE1→UE2 call failure (2026-03-19) proved that the single-agent architecture has fundamental limits: the agent abandoned its methodology, followed the most interesting error (I-CSCF 500) instead of checking the destination (UE2), and scored 10%.

**The v2 multi-agent architecture is now fully specified** in the "v2: Multi-Agent Decomposition" section below. It uses the same ADK framework (SequentialAgent + ParallelAgent) already proven in the chaos monkey platform.

### How v1.5 Enables v2

The v1.5 architecture makes this decomposition straightforward because:

1. **Tools are standalone functions** in `tools.py` — not embedded in the agent. Any agent (triage, tracer, or specialist) can import and use any subset of tools.

2. **The `AgentDeps` dependency injection** provides shared state (repo path, env vars) that any sub-agent can use.

3. **ADK's SequentialAgent + ParallelAgent** (already proven in `agentic_chaos/orchestrator.py`) can wire the phases: triage → trace → parallel specialists → synthesis. The shared `session.state` pattern passes structured data between phases.

4. **Each specialist agent can use a different model** — use Flash for fast triage, Pro for complex IMS analysis:

```python
triage_agent = LlmAgent(model="gemini-2.5-flash", ...)       # Fast, cheap
ims_specialist = LlmAgent(model="gemini-2.5-pro", ...)       # Deep reasoning
transport_specialist = LlmAgent(model="gemini-2.5-flash", ...)  # Simple checks
```

5. **Tool budgets are enforceable** — each specialist agent gets a `max_tool_calls` parameter, preventing the rabbit-hole problem that sank v1.

### Sub-Agent Design Principles

1. **Phase 0 (Triage) runs ALWAYS** — metrics first, no exceptions. This is architectural, not advisory.
2. **Phase 1 (End-to-End Trace) checks the destination** — the single most important lesson from the UE1→UE2 failure. Dedicated agent, not a system prompt suggestion.
3. **Specialists are narrowly scoped** — each knows one domain, carries only its tools, has a bounded context
4. **Specialists run in parallel** when investigating orthogonal domains
5. **Orchestrator gates phases** — Phase 0 results determine whether Phase 1 runs, Phase 1 results determine which specialists to dispatch
6. **Each specialist must report what it checked AND what would disprove its finding** — hypothesis disconfirmation is structural, not optional

---

## Key Design Decisions

### 1. Model Selection (RESOLVED)

Model-agnostic via environment variable. Default to Claude Sonnet for balanced speed/quality. Switch to Opus for complex investigations, Gemini for cost optimization.

```bash
AGENT_MODEL=anthropic:claude-sonnet-4-20250514
```

### 2. Token Budget Strategy

20 containers × 200 log lines × ~50 tokens/line = ~200K tokens if we read everything naively. Strategy:

- **Selective reading**: Agent decides which containers to inspect (this is why tool-use beats prompt-stuffing)
- **Pre-filtering in tools**: `grep` parameter on `read_container_logs` lets the agent filter noise before ingesting
- **Cross-stack search**: `search_logs` returns only matching lines across containers — far more token-efficient than reading 200 lines from each container individually
- **Reasonable defaults**: `tail=200` lines per `read_container_logs` call, agent can request more if needed
- **System prompt loaded once**: ~5K tokens for domain knowledge (loaded from docs files at startup, not on every call)
- **Tool result truncation**: If a tool returns >500 lines, truncate with a warning so the agent can refine its query

### 3. Streaming (RESOLVED)

Stream progress via WebSocket. Pydantic AI's `run_stream_events()` yields events:

```python
async with agent.run_stream(question, deps=deps) as stream:
    async for event in stream.stream_events():
        if event.type == "tool_call":
            await ws.send_json({"type": "tool_call", "name": event.tool_name, "args": event.args})
        elif event.type == "text_delta":
            await ws.send_json({"type": "text", "delta": event.text})
```

The GUI shows: "Checking network status... Reading pcscf logs... Found 47 BYE retransmissions... Reading scscf logs..."

### 4. Remediation (RESOLVED — out of scope for v1)

v1 is **diagnosis only**. The agent produces a `Diagnosis` with a `recommendation` field. The user reads the recommendation and acts on it manually. Remediation tools will be added in v2 with a confirmation flow.

### 5. Error Handling

| Error | Handling |
|---|---|
| API timeout | Retry once with exponential backoff, then return partial diagnosis |
| API rate limit | Queue with backoff, inform user of delay |
| Container not found | Tool returns "Container 'xxx' not found" — agent handles gracefully |
| Docker socket unavailable | Tool returns error message — agent reports infrastructure issue |
| Model returns refusal | Retry with reworded prompt, or return "unable to diagnose" |
| Token limit exceeded | Truncate tool results, warn in diagnosis |
| WebSocket closed mid-investigation | Cancel agent run, clean up |
| Malformed model output | Pydantic validation catches it, retry the turn |

### 6. GCP Deployment (future)

The architecture supports GCP deployment:

- **Cloud Run**: Package as Docker container. `aiohttp` server + agent code. Tools call Docker Engine API over network (remote Docker host) instead of local socket.
- **GKE**: Same container in Kubernetes. Docker-in-Docker or Docker socket mount for container access.
- **Key change for GCP**: Tools must connect to a remote Docker host (the stack runs on a different machine). Swap `subprocess` calls for Docker SDK with remote host config.

---

## Implementation Plan

### Project Structure

```
operate/agentic-ops/
├── plan-review.md          # This document
├── agent.py                # TelecomAgent definition (Pydantic AI Agent + system prompt)
├── tools.py                # Tool function implementations
├── models.py               # Pydantic models (Diagnosis, AgentDeps, etc.)
├── prompts/
│   └── system.md           # System prompt template (loads docs at startup)
├── requirements.txt        # pydantic-ai, aiohttp, etc.
└── tests/
    ├── test_tools.py       # Unit tests for each tool
    └── test_agent.py       # Integration tests with mock model responses
```

### Phase 1: Tools (Day 1)

- [ ] Define `AgentDeps` dataclass and `Diagnosis` result model in `models.py`
- [ ] Implement 6 tool functions in `tools.py`
- [ ] Write unit tests for each tool against a running stack
- [ ] Verify tool output is clean and useful (no noise, correct encoding)
- [ ] Validate `search_logs` with known patterns (Call-ID, IMSI, BYE) across containers

### Phase 2: Agent (Day 2)

- [ ] Write system prompt in `prompts/system.md` (load docs at startup)
- [ ] Create `TelecomAgent` in `agent.py` with Pydantic AI
- [ ] Test agent with known scenarios: BYE storm, missing subscriber, auth mismatch
- [ ] Tune system prompt based on agent behavior
- [ ] Verify model switching works (Sonnet → Opus → Gemini)

### Phase 3: GUI Integration (Day 3)

- [ ] Add `/ws/investigate` WebSocket endpoint to `server.py`
- [ ] Implement streaming: forward agent events to WebSocket
- [ ] Add "Investigate" button and investigation output panel to `index.html`
- [ ] Test end-to-end: user asks question → agent investigates → diagnosis displayed

### Phase 4: Hardening (Day 4)

- [ ] Error handling for all shadow paths (API errors, Docker failures, etc.)
- [ ] Token budget testing with large log volumes
- [ ] Test with multiple models (Sonnet, Opus, Gemini)
- [ ] Write integration tests with recorded scenarios
- [ ] Update documentation

---

## 10x Vision (Deferred)

These capabilities are explicitly **not in v1 scope** but the architecture supports them:

### Proactive Monitoring
A background agent loop that periodically reads logs and alerts on anomalies. Requires: persistent state, alerting mechanism, configurable check intervals.

### Auto-Remediation
Agent proposes fixes with a "Fix it" button in the GUI. Requires: remediation tools (restart_container, exec_in_container), confirmation flow, rollback capability.

### Call Flow Visualization
After a call, reconstruct the INVITE → 100 → 200 → ACK sequence diagram from correlated container logs. Render as ASCII or SVG in the GUI.

### Persistent Knowledge / Memory Architecture
Store past diagnoses in a JSON file or SQLite database. Agent can reference: "This looks like the same BYE storm issue from 2 hours ago."

**Tiered memory model** (from Gemini peer review):
- **Short-Term Memory (STM):** A `SessionContext` in `AgentDeps` tracks live findings during a single investigation — discovered IPs, active Call-IDs, tested hypotheses. Tool: `record_fact(fact, confidence)`. In v1, the LLM's native conversation context serves this purpose adequately for 5-10 turn investigations; STM becomes critical when sub-agents need to share findings or investigations exceed 20+ turns.
- **Long-Term Memory (LTM):** SQLite or JSON store in `operate/agentic-ops/memory/` for past diagnoses, stack nuances, and symptom→fix mappings. Tool: `recall_similar_cases(symptoms)`. Enables the agent to learn from experience across sessions.

### SIP Dialog Extraction
A `get_sip_dialog(call_id)` tool that extracts the entire SIP transaction (INVITE through 200 OK/ACK) for a given Call-ID from IMS container logs. Requires parsing Kamailio's multi-line log format to reconstruct full SIP messages. In v1, `search_logs(pattern=call_id, containers=["pcscf","scscf","icscf"])` covers most cases; the dedicated tool provides cleaner, more complete protocol context.

### Log Normalization Layer
A `LogParser` utility that normalizes timestamps across different container log formats (Open5GS, Kamailio syslog, pjsua, UERANSIM) to ISO8601, enabling precise cross-container timeline construction. In v1, the LLM can parse different timestamp formats adequately; normalization becomes critical for sub-agent coordination and automated timeline generation.

### Native Database Clients
Replace `docker exec mongosh`/PyHSS REST scraping with native Python clients (`pymongo`, `mysql-connector-python`) for cleaner structured JSON output and reduced token cost. Adds dependencies and requires direct network access to databases.

### Sub-Agent Decomposition — NOW PLANNED FOR v2
~~Coordinator + IMS specialist + Core specialist + RAN specialist.~~ **Updated:** Gated multi-phase architecture with Triage → End-to-End Trace → Specialists → Synthesis. Includes a new Transport Specialist (learned from UE1→UE2 failure). See "v2: Multi-Agent Decomposition" section for the full design.

### Multi-Stack Support
Extend from 5G SA + IMS to also support 4G VoLTE, VoWiFi, and hybrid stacks. Different system prompts per stack type.

### pcap Integration
Read packet captures (tcpdump/Wireshark) for wire-level protocol analysis when logs aren't sufficient.

---

## v1.5: Post-Incident Improvements (2026-03-19)

### The Triggering Incident: UE1→UE2 Call Failure

Full postmortem: [`operate/docs/RCAs/postmortem_ue1_calls_ue2_failure.md`](../docs/RCAs/postmortem_ue1_calls_ue2_failure.md)

The v1 agent was deployed on Gemini 2.5 Pro and asked to diagnose why UE1 could not call UE2 (both were registered successfully). The agent scored **10%** — it blamed the I-CSCF's Diameter configuration (wrong) when the actual root cause was a P-CSCF transport mismatch (`udp_mtu_try_proto=TCP` causing SIP INVITEs to be sent via TCP to pjsua UEs that only listen on UDP).

### What Went Wrong

The agent had three fundamental failures:

1. **Did not trace the call to the destination.** The agent checked UE1 (caller) and the intermediate IMS nodes (P-CSCF, I-CSCF, S-CSCF) but never checked UE2 (callee). If it had searched for the Call-ID in UE2's logs and found nothing, it would have immediately known the INVITE never reached UE2 — shifting the investigation from "why can't the I-CSCF talk to HSS?" to "why isn't the INVITE reaching UE2?"

2. **Had no access to metrics.** The agent could not query Prometheus for GTP packet counts, session counts, or any NF KPIs. The entire metrics store — which the `rca_reflections.md` document identifies as the "radiograph" that should precede all log analysis — was invisible to the agent.

3. **Had no access to runtime state.** The agent could not check Kamailio Diameter peer connections (`kamcmd cdp.list_peers`), usrloc registered contacts, or the ACTUAL running config (as opposed to the repo copy). It formed a hypothesis about missing Diameter config and had no tool to verify or disprove it.

### Tools Added in v1.5

| # | Tool | Purpose | Gap it fills |
|---|---|---|---|
| 7 | `query_prometheus(query)` | Execute PromQL queries against Prometheus | Agent can now check GTP packet counts, session counts, auth failures — the "radiograph" triage |
| 8 | `get_nf_metrics()` | Full metrics snapshot: Prometheus + kamcmd + PyHSS + MongoDB | One-call health overview of the entire stack |
| 9 | `run_kamcmd(container, command)` | Execute kamcmd inside Kamailio containers | Diameter peer state, usrloc registrations, transaction stats |
| 10 | `read_running_config(container, grep)` | Read the ACTUAL config from a running container | Catches cases where the running config differs from the repo (volume mount overwrites) |
| 11 | `check_process_listeners(container)` | Show TCP/UDP listeners via `ss -tulnp` | Diagnose transport mismatches (TCP vs UDP) |

### System Prompt Overhaul in v1.5

The investigation methodology was rewritten based on the failure:

1. **Step 1 now includes metrics** — `get_nf_metrics` is called alongside `read_env_config` and `get_network_status`. The agent is told: "metrics are the radiograph — read them before touching any log files."

2. **Step 2 now mandates checking BOTH ends** — for call failures, the agent MUST check the callee's logs for the Call-ID before investigating intermediate nodes. The rule is explicit: "If the callee has no record of the Call-ID, the request never reached the callee. Do NOT investigate intermediate nodes until you have confirmed whether the request reached its destination."

3. **Step 3 now requires Call-ID end-to-end tracing** — search for the Call-ID across ALL containers, build a timeline of which containers saw it and which did NOT.

4. **Step 7 (new) mandates hypothesis disconfirmation** — before reporting a root cause, the agent must run at least one check that could disprove its conclusion.

5. **New failure patterns added** — "SIP INVITE not delivered" (transport mismatch) and "Cascading 500 errors" (timeout propagation) with exact diagnostic steps.

6. **Transport layer knowledge added** — explanation of `udp_mtu_try_proto`, why TCP delivery to pjsua fails silently, and what to check when SIP messages "vanish" between P-CSCF and UE.

### Current State (v1.5)

```
v1 (6 tools):                     v1.5 (11 tools):
  read_container_logs                read_container_logs
  read_config                        read_config
  get_network_status                 get_network_status
  query_subscriber                   query_subscriber
  read_env_config                    read_env_config
  search_logs                        search_logs
                                   + query_prometheus         ← metrics triage
                                   + get_nf_metrics           ← full stack health
                                   + run_kamcmd               ← Kamailio runtime state
                                   + read_running_config      ← actual running config
                                   + check_process_listeners  ← transport layer
```

---

## v2: Multi-Agent Decomposition (Next Phase)

### Why v1.5 Is Not Enough

v1.5 added the right tools and methodology, but the single-agent architecture has fundamental limits that surfaced during the UE1→UE2 investigation:

1. **Context window saturation.** The system prompt is now ~3K tokens of methodology + architecture + failure patterns. Each tool call returns 200-500 lines. After 8 tool calls, the agent has consumed ~50K tokens of context. The investigation methodology and failure patterns get pushed out of the attention window by raw log data.

2. **No enforced investigation discipline.** Despite the system prompt saying "check both ends" and "metrics first", the LLM followed the "most interesting" thread (I-CSCF 500 error) and abandoned the methodology. A single agent can be told to follow a process but cannot be forced to.

3. **Can't parallelize.** Checking UE1 logs, UE2 logs, metrics, and Diameter peer state are independent operations. A single agent runs them sequentially, burning tokens on each round-trip.

4. **Can't prune.** There's no checkpoint where the system stops and asks "given what the metrics agent found, should we even run the IMS log agent?" The single agent makes this decision implicitly (often wrong) rather than explicitly.

These are the exact problems documented in `agent_design_reflections.md` after the first RCA. v1.5 mitigated them with better tools and prompts, but the architectural solution is multi-agent.

### Gated Multi-Phase Architecture

Based on the agent_design_reflections.md design AND the lessons from the UE1→UE2 failure:

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
    │  TRIAGE     │    │ END-TO-END │    │ SPECIALIST   │
    │  AGENT      │    │ TRACE      │    │ AGENTS       │
    │             │    │ AGENT      │    │ (parallel)   │
    │ Tools:      │    │            │    │              │
    │ - metrics   │    │ Tools:     │    │ ┌──────────┐ │
    │ - prom query│    │ - search   │    │ │P-CSCF    │ │
    │ - net status│    │   logs     │    │ │specialist│ │
    │ - env config│    │ - UE logs  │    │ ├──────────┤ │
    │             │    │            │    │ │S-CSCF    │ │
    │ Returns:    │    │ Returns:   │    │ │specialist│ │
    │ structured  │    │ which nodes│    │ ├──────────┤ │
    │ health      │    │ saw the    │    │ │Core NF   │ │
    │ report +    │    │ request,   │    │ │specialist│ │
    │ anomalies   │    │ which did  │    │ ├──────────┤ │
    │             │    │ NOT        │    │ │Transport │ │
    │             │    │            │    │ │specialist│ │
    │             │    │            │    │ └──────────┘ │
    └─────────────┘    └────────────┘    └──────────────┘
```

### Phase 0: Triage Agent (ALWAYS runs, ~3 seconds)

**Purpose:** Quick health assessment. Determines the investigation path.

**Tools:** `get_nf_metrics`, `query_prometheus`, `get_network_status`, `read_env_config`

**Output:** Structured triage report:
```python
class TriageReport(BaseModel):
    stack_phase: str           # "ready" / "partial" / "down"
    data_plane_status: str     # "healthy" / "degraded" / "dead"
    control_plane_status: str  # "healthy" / "degraded" / "down"
    ims_status: str            # "healthy" / "degraded" / "down"
    anomalies: list[str]       # ["GTP packets = 0", "P-CSCF 0 registered contacts"]
    recommended_phase: str     # "end_to_end_trace" / "data_plane_probe" / "ims_analysis"
```

**Decision logic:** The orchestrator reads the triage report and decides:
- If `data_plane_status == "dead"` → skip IMS analysis, run data plane probes
- If `ims_status == "down"` → run IMS specialist agents
- If everything looks healthy → run end-to-end trace (the problem is subtle)

**Why this is Phase 0:** Metrics triage takes 3 seconds and determines the entire investigation path. This is the "radiograph before biopsy" principle from `rca_reflections.md`. In the UE1→UE2 failure, Phase 0 would have shown: GTP packets flowing (data plane OK), sessions active (control plane OK), but P-CSCF registered contacts = 0 (IMS anomaly) → route to IMS specialists.

### Phase 1: End-to-End Trace Agent (CONDITIONAL)

**Purpose:** Trace the specific request (Call-ID, REGISTER, etc.) across ALL containers to find where it stopped.

**Tools:** `search_logs`, `read_container_logs` (for both UEs)

**Output:**
```python
class TraceResult(BaseModel):
    call_id: str
    nodes_that_saw_it: list[str]     # ["e2e_ue1", "pcscf", "scscf", "icscf"]
    nodes_that_should_have: list[str] # ["e2e_ue2"]
    failure_point: str                # "between pcscf and e2e_ue2"
    error_messages: dict[str, str]    # {"icscf": "500 Server error on LIR..."}
```

**Why this is critical:** In the UE1→UE2 failure, this agent would have found that UE2 never saw the Call-ID. That single finding would have redirected the entire investigation from "I-CSCF Diameter" to "P-CSCF → UE2 delivery."

**This is the lesson the v1 agent missed:** always check the destination. The End-to-End Trace Agent exists specifically to enforce this discipline — it's not optional, it's not a recommendation in a system prompt. It's a dedicated agent whose sole purpose is to answer "did the request reach its destination?"

### Phase 2: Specialist Agents (CONDITIONAL, run in parallel)

Based on Phase 0 triage and Phase 1 trace, the orchestrator dispatches relevant specialists:

**IMS Specialist:**
- Tools: `read_container_logs` (pcscf, icscf, scscf, pyhss), `run_kamcmd`, `read_running_config`
- Knowledge: SIP call flows, Diameter Cx, Kamailio config, IMS registration
- Budget: 5 tool calls max

**Core NF Specialist:**
- Tools: `read_container_logs` (amf, smf, upf), `query_prometheus`, `read_running_config`
- Knowledge: 5G NAS, PFCP, GTP-U, PDU sessions
- Budget: 5 tool calls max

**Transport Specialist** (NEW — learned from UE1→UE2 failure):
- Tools: `check_process_listeners`, `read_running_config`, `run_kamcmd`
- Knowledge: UDP vs TCP, `udp_mtu_try_proto`, SIP transport, listener state
- Budget: 3 tool calls max
- **When dispatched:** When Phase 1 shows a request was sent to a destination but never received

**Data Specialist:**
- Tools: `query_subscriber`, `query_prometheus`
- Knowledge: MongoDB schema, PyHSS API, subscriber provisioning
- Budget: 3 tool calls max

### Key Design Changes from v1 → v2

| Aspect | v1/v1.5 (Single Agent) | v2 (Multi-Agent) |
|---|---|---|
| Metrics check | System prompt says "check metrics first" — agent may or may not comply | Phase 0 Triage Agent runs ALWAYS before any other analysis |
| Destination check | System prompt says "check both ends" — agent skipped it | Phase 1 End-to-End Trace Agent exists specifically for this |
| Tool budget | Unlimited — agent can burn 15+ tool calls on wrong thread | Each specialist gets max N tool calls, enforced by orchestrator |
| Parallelism | Sequential — each tool call waits for LLM round-trip | Specialists run in parallel within each phase |
| Context management | All tool output in one context window → saturation | Each specialist has its own context, returns structured summary to orchestrator |
| Investigation discipline | Recommendations in system prompt (advisory) | Enforced by architecture (mandatory phases, gated progression) |
| Hypothesis disconfirmation | Step 7 in system prompt (may be skipped) | Orchestrator requires each specialist to report what it checked AND what would disprove its finding |

### Framework for v2

The chaos monkey platform already demonstrated that ADK's `SequentialAgent`, `ParallelAgent`, and `LoopAgent` work well for multi-phase orchestration with shared state. The troubleshooting agent should use the same pattern:

```python
# Orchestrator as SequentialAgent
troubleshooting_director = SequentialAgent(
    name="TroubleshootingDirector",
    sub_agents=[
        triage_agent,           # Phase 0: always
        end_to_end_tracer,      # Phase 1: trace Call-ID across stack
        specialist_dispatcher,   # Phase 2: ParallelAgent of relevant specialists
        synthesis_agent,         # Phase 3: merge findings into Diagnosis
    ],
)
```

Shared state via `session.state`:
- `state["triage"]` — TriageReport from Phase 0
- `state["trace"]` — TraceResult from Phase 1
- `state["specialist_findings"]` — dict of specialist → SubDiagnosis
- `state["diagnosis"]` — final Diagnosis

### Estimated Impact on the UE1→UE2 Failure

If v2 had been deployed:

| Phase | What it would do | Time | Result |
|---|---|---|---|
| Phase 0 (Triage) | `get_nf_metrics()` + `query_prometheus` | ~3s | IMS stats captured. No obvious metric anomaly (GTP flowing, sessions active). |
| Phase 1 (Trace) | Search for Call-ID across all containers | ~5s | **UE2 has no record of Call-ID.** Failure point: "between pcscf and e2e_ue2". |
| Phase 2 (Specialists) | Transport Specialist dispatched (request sent but not received) | ~5s | `read_running_config(pcscf, "udp_mtu")` → `TCP`. `check_process_listeners(e2e_ue2)` → UDP only. **Root cause identified.** |
| Synthesis | Merge: triage (healthy) + trace (UE2 never received) + transport (TCP/UDP mismatch) | ~3s | Correct diagnosis: P-CSCF sends INVITE via TCP, UE2 only listens UDP. |
| **Total** | | **~16s** | **Correct diagnosis, score ~85%+** |

vs. v1: ~2 minutes, incorrect diagnosis, score 10%.

---

## Peer Review Notes

### Gemini Review (2026-03-15)

Full review in [`plan-review-feedback-gemini.md`](plan-review-feedback-gemini.md).

**Incorporated into v1:**
- **`search_logs` tool (1.4):** Added as Tool 6. Addresses the critical gap where `tail=200` is insufficient for intermittent issues. Enables cross-container pattern search by Call-ID, IMSI, or error keyword.
- **Dynamic topology discovery (1.2):** Updated troubleshooting methodology to mandate `read_env_config()` as the first step. System prompt no longer hardcodes IPs.

**Acknowledged, deferred to v1.1:**
- **Log normalization (1.1):** Timestamp normalization across container formats. LLM handles format differences adequately in v1.
- **SIP dialog extraction (1.6):** Full SIP transaction reconstruction by Call-ID. `search_logs` covers most cases in v1.

**Acknowledged, deferred to v2:**
- **Native DB clients (1.3):** `pymongo`/`mysql-connector` for cleaner output. Docker exec is simpler for v1.
- **Fact buffer / STM (1.5):** `record_fact()` tool. LLM conversation context is sufficient for v1's 5-10 turn investigations.
- **LTM / persistent memory (2.2):** `recall_similar_cases()` tool. Requires persistent storage, premature for v1.

**Agreed with:**
- **Single agent for v1 (Section 4):** Reinforces our existing architecture. The memory tiering proposal captures the benefits of MAS (context compression) without the coordination complexity. ~~Re-evaluate for v2.~~ **UPDATE (2026-03-19):** v1.5 confirmed that single-agent limits are real, not theoretical. The UE1→UE2 call failure demonstrated context saturation, methodology abandonment, and inability to parallelize. v2 multi-agent decomposition is now a concrete plan, not a theoretical future option. See "v2: Multi-Agent Decomposition" section above.

### Post-Incident Review (2026-03-19)

**Triggering event:** UE1→UE2 call failure. Agent scored 10%.

**Key lessons incorporated:**
1. **Metrics tools added** (query_prometheus, get_nf_metrics) — the "radiograph" that was completely missing from v1
2. **Runtime state tools added** (run_kamcmd, read_running_config, check_process_listeners) — the verification tools needed to disprove hypotheses
3. **System prompt rewritten** — mandatory end-to-end verification, hypothesis disconfirmation, metrics-first methodology
4. **v2 multi-agent architecture specified** — moves from "advisory methodology in system prompt" to "enforced discipline via architecture"
5. **Transport Specialist agent designed** — directly from the `udp_mtu_try_proto` lesson, a specialist that checks transport layer state when requests vanish between nodes

**Full postmortem:** [`operate/docs/RCAs/postmortem_ue1_calls_ue2_failure.md`](../docs/RCAs/postmortem_ue1_calls_ue2_failure.md)
**Design reflections:** [`operate/docs/RCAs/agent_design_reflections.md`](../docs/RCAs/agent_design_reflections.md)

