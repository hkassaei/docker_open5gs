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

### Future Tools (not in v1)

These tools are designed but deferred:

| Tool | Purpose | Why deferred | Target |
|---|---|---|---|
| `get_sip_dialog(call_id)` | Extract a complete SIP transaction (INVITE→200→ACK) by Call-ID from IMS container logs | Requires SIP message parsing from Kamailio logs; `search_logs` with Call-ID covers most cases in v1 | v1.1 |
| `get_correlated_timeline(since)` | Merge logs from all containers, normalize timestamps to ISO8601, sort chronologically | Valuable for cross-container correlation; LLM can parse different timestamp formats adequately for v1 | v1.1 |
| `record_fact(fact, confidence)` | Save a verified finding to short-term memory so the agent doesn't re-read raw data | Within a single investigation (5-10 tool calls), LLM's conversation context is sufficient; becomes critical with sub-agents or 20+ turn investigations | v2 |
| `recall_similar_cases(symptoms)` | Search persistent memory of past diagnoses for similar patterns | Requires persistent storage (SQLite/JSON); premature for v1 | v2 |
| `query_prometheus(query)` | Execute PromQL queries for metrics | Not needed for log-based diagnosis | v2 |
| `restart_container(name)` | Restart a container | Remediation is out of scope for v1 | v2 |
| `exec_in_container(name, cmd)` | Run arbitrary command in container | Security concerns, needs careful design | v2 |
| `read_log_file(component)` | Read Open5GS log files from `./log/` | `read_container_logs` covers most cases | v1.1 |
| `diff_config(component)` | Compare on-disk vs in-container config | Delight feature, not core diagnosis | v1.1 |

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

## Sub-Agent Decomposition (Future)

v1 uses a single agent. The architecture is designed so that when investigations become more complex, we can decompose into specialized sub-agents.

### Future Multi-Agent Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Coordinator Agent                                                   │
│  "Receive user question, dispatch to specialists, synthesize"        │
│                                                                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────┐ │
│  │ IMS Agent    │  │ Core Agent  │  │ RAN Agent   │  │ Data Agent │ │
│  │             │  │             │  │             │  │            │ │
│  │ Tools:      │  │ Tools:      │  │ Tools:      │  │ Tools:     │ │
│  │ - pcscf logs│  │ - amf logs  │  │ - gnb logs  │  │ - mongodb  │ │
│  │ - scscf logs│  │ - smf logs  │  │ - ue logs   │  │ - pyhss    │ │
│  │ - icscf logs│  │ - upf logs  │  │ - ue config │  │ - metrics  │ │
│  │ - pyhss logs│  │ - pcf logs  │  │             │  │            │ │
│  │ - ims config│  │ - core cfg  │  │             │  │            │ │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └─────┬──────┘ │
│         │                │                │                │        │
│         └────────────────┴────────────────┴────────────────┘        │
│                                    │                                 │
│                          Coordinator merges                          │
│                          findings into Diagnosis                     │
└─────────────────────────────────────────────────────────────────────┘
```

### How v1 Enables This

The v1 architecture makes this decomposition straightforward because:

1. **Tools are standalone functions** in `tools.py` — not embedded in the agent. Any agent (coordinator or specialist) can import and use any subset of tools.

2. **The `AgentDeps` dependency injection** provides shared state (repo path, env vars) that any sub-agent can use.

3. **Pydantic AI's delegation pattern** lets a coordinator agent hand off to specialist agents:

```python
# Future: coordinator delegates to IMS specialist
ims_agent = Agent(
    model=os.environ["AGENT_MODEL"],
    system_prompt="You specialize in IMS/SIP troubleshooting...",
    tools=[read_container_logs, read_config],  # subset of tools
    result_type=SubDiagnosis,
)

@coordinator_agent.tool
async def investigate_ims(ctx: RunContext[AgentDeps], question: str) -> str:
    """Delegate IMS investigation to the IMS specialist agent."""
    result = await ims_agent.run(question, deps=ctx.deps)
    return result.data.model_dump_json()
```

4. **Each specialist agent can use a different model** — use Sonnet for fast log scanning, Opus for complex reasoning:

```python
ims_agent = Agent(model=os.environ.get("IMS_AGENT_MODEL", "anthropic:claude-sonnet-4-20250514"), ...)
coordinator = Agent(model=os.environ.get("COORDINATOR_MODEL", "anthropic:claude-opus-4-20250514"), ...)
```

### Sub-Agent Design Principles (for when we get there)

1. **Specialists are narrowly scoped** — each agent knows one domain deeply
2. **Coordinator is protocol-aware** — knows which specialist to dispatch based on symptoms
3. **Specialists run in parallel** when investigating orthogonal domains (IMS + Core simultaneously)
4. **Each specialist returns a `SubDiagnosis`** — structured findings that the coordinator synthesizes
5. **Tools are shared, prompts are specialized** — same `read_container_logs` function, different system prompts

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

### Sub-Agent Decomposition
Coordinator + IMS specialist + Core specialist + RAN specialist. Each specialist uses the optimal model for its domain.

### Multi-Stack Support
Extend from 5G SA + IMS to also support 4G VoLTE, VoWiFi, and hybrid stacks. Different system prompts per stack type.

### pcap Integration
Read packet captures (tcpdump/Wireshark) for wire-level protocol analysis when logs aren't sufficient.

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
- **Single agent for v1 (Section 4):** Reinforces our existing architecture. The memory tiering proposal captures the benefits of MAS (context compression) without the coordination complexity. Re-evaluate for v2.

