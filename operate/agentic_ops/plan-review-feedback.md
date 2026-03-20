# Gemini AI Review & Feedback — Telecom Troubleshooting Agent

**Reviewer**: Gemini CLI (AI Senior Engineer)  
**Status**: Approved with 6 Strategic Improvements + Memory Architecture Upgrade

---

## Executive Summary

The base plan in `plan-review.md` provides a solid foundation, particularly in its choice of **Pydantic AI** and the "Hold Scope" focus on diagnosis. However, to handle the high complexity of SIP signaling and 5G state machines without drowning in token costs or hallucinating temporal events, I propose the following enhancements.

---

## 1. Six Strategic Improvements

### 1.1 Log Normalization Layer (Temporal Accuracy)
**Issue:** Different components (Open5GS, Kamailio, pjsua) use different timestamp formats, making cross-container correlation difficult for LLMs.  
**Improvement:** Implement a `LogParser` utility in `tools.py`. The agent should be able to request a **Normalized Timeline** where events from multiple containers are interleaved and sorted by a standard ISO8601 timestamp.

### 1.2 Topology Discovery (Dynamic Awareness)
**Issue:** Hardcoding UE1/UE2 and specific IPs in the system prompt makes the agent brittle to configuration changes.  
**Improvement:** Add a `discover_topology` tool that parses live `docker-compose` and `.env` files to build a "Live Network Map" for the agent at the start of each session.

### 1.3 Native Database Clients (Data Integrity)
**Issue:** Scraping `stdout` from `mongosh` or `mysql` CLI is brittle and token-heavy.  
**Improvement:** Use native Python clients (`pymongo`, `mysql-connector-python`) within the tools. This allows returning filtered, structured JSON to the agent, reducing noise.

### 1.4 Global Search Tool (Beyond Tail)
**Issue:** `tail=200` is insufficient for intermittent issues where the root cause occurred minutes before the symptom.  
**Improvement:** Add a `search_logs` tool that supports `grep`-like searching across all containers or specific time ranges for unique identifiers (IMSI, MSISDN, SIP Call-ID).

### 1.5 Context Window Management (Fact Buffer)
**Issue:** Repeatedly reading logs consumes the context window, causing the agent to lose its "train of thought."  
**Improvement:** Implement a **"Fact Buffer"** (Short-Term Memory). The agent should use a `record_fact()` tool to save verified findings (e.g., "UE1 IP is 172.22.0.51") so it doesn't have to re-read raw data to recall them.

### 1.6 SIP-Specific Intelligence
**Issue:** SIP messages are multi-line and complex; raw log snippets often cut off critical headers.  
**Improvement:** Create a specialized `get_sip_dialog` tool. This tool should extract the *entire* SIP transaction (INVITE through 200 OK/ACK) for a given Call-ID, providing the LLM with the full protocol context.

---

## 2. Agentic Memory Architecture

To evolve this from a "scripted investigator" to a true agentic system, we move from a simple scratchpad to a tiered memory model.

### 2.1 Short-Term Memory (STM): The "Investigation Context"
*   **Purpose:** Tracks live findings during a single troubleshooting run.
*   **Implementation:** A `SessionContext` object in `AgentDeps`.
*   **Stored Data:** Discovered IPs, active Call-IDs, tested hypotheses, and confirmed facts.
*   **Agent Tool:** `record_fact(fact: str, confidence: float)`

### 2.2 Long-Term Memory (LTM): The "Stack History"
*   **Purpose:** Persists knowledge across server restarts and different investigation sessions.
*   **Implementation:** A lightweight SQLite database or JSON store in `operate/agentic-ops/memory/`.
*   **Stored Data:** 
    *   **Past Diagnoses:** Vector-searchable summaries of previous root causes.
    *   **Stack Nuances:** "UE2 always times out on the first attempt."
    *   **Fixed Issues:** Mappings of symptoms to successful remediations.
*   **Agent Tool:** `recall_similar_cases(symptoms: str)`

---

## 3. Revised Implementation Roadmap

### Phase 0: Infrastructure & Memory (The "Agentic Core")
- [ ] Implement `models.MemoryManager` (STM/LTM logic).
- [ ] Create `tools.LogParser` (Universal timestamp normalization).
- [ ] Define `AgentDeps` to include the `MemoryManager` and `TopologyMap`.

### Phase 1: Enhanced Tools
- [ ] Build `read_container_logs` with the normalization layer.
- [ ] Build `query_subscriber` using native DB drivers.
- [ ] Implement `record_fact` and `get_sip_dialog`.

### Phase 2: Reasoning & System Prompt
- [ ] Update `system.md` to instruct the agent on **Memory Tiering**.
- [ ] Add "Known Failure Patterns" from LTM into the prompt dynamically.

---

## 4. Architectural Analysis: Single vs. Multi-Agent

### Option A: Single Agent (Recommended for v1)
A unified expert with direct access to all specialized tools.
*   **Pros:** Unified context, zero handoff loss, lower latency, and simpler debugging.
*   **Cons:** Higher risk of context window bloat and "lost in the middle" attention issues.
*   **Mitigation:** Solved via **Memory Tiering (STM/LTM)** and **Smart Tools** (functional decomposition) that pre-process data.

### Option B: Multi-Agent System (MAS)
A Coordinator delegating to domain-specific specialists (IMS, Core, DB).
*   **Pros:** Deeper domain expertise per prompt, better task parallelism, and natural context compression.
*   **Cons:** High coordination overhead, potential "bystander effect" where cross-domain issues are missed, and increased token/time costs.

### Recommendation
**Start with a Single Agent.** The "Hold Scope" diagnosis requirement for v1 is better served by the speed and context-integrity of a single model. Using **Gemini 3.0 Pro** ensures the highest reasoning density and largest context window available in 2026. The proposed **Memory Architecture** effectively captures the benefits of MAS (context compression) without its complexity. Re-evaluate for v2 when adding **Auto-Remediation**.

---

## 5. Final Peer Review Note
The "BYE Storm" scenario is the perfect benchmark. With the **Log Normalization** and **SIP Dialog** tools, the agent will see the storm as a coherent sequence rather than disconnected log lines, drastically increasing the reliability of the v1 release.
