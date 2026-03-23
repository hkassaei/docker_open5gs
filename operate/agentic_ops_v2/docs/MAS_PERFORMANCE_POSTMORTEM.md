# Multi-Agent Performance Post-Mortem (v1 vs v2)

**Status**: Performance Degradation Identified (v2 < v1.5)  
**Root Cause**: Context Poisoning / History Accumulation in Google ADK SequentialAgent.

---

## 1. Executive Summary

Despite the architectural promise of specialization, the Multi-Agent System (v2) is currently underperforming the Single Agent (v1.5) on every KPI:
- **Accuracy**: 60% (v2) vs 90% (v1.5).
- **Latency**: 145s (v2) vs 90s (v1.5).
- **Cost**: ~1M tokens (v2) vs 159K tokens (v1.5).

The primary failure mode is that the specialist agents are receiving too much information, causing "attention dilution" and hallucinations.

---

## 2. Key Findings

### 2.1 The "Radioactive" Tracer
The `EndToEndTracer` is the single biggest source of token explosion. It performs a global `search_logs` which returns ~70KB of raw text. Because v2 uses a `SequentialAgent`, this 70KB blob is re-sent in every subsequent LLM turn for every specialist. 
- **Impact**: Specialists start their turn with 200K+ tokens of inherited noise.

### 2.2 Specialist Hallucinations
The `IMSSpecialist` hallucinated a "Diameter Placeholder" error. This is a direct consequence of context saturation. When an LLM is presented with 200K tokens of logs it didn't request, it loses the ability to distinguish between "context evidence" and "tool evidence," leading it to find patterns in the noise.

### 2.3 Dispatcher Overshadowing
The `DispatchAgent` makes correct reasoning decisions but the current orchestrator ignores them by running all specialists in parallel. 
- **Impact**: The system spends 300K+ tokens running specialists (like `SubscriberData`) that the system already knows are irrelevant.

---

## 3. Implementation Roadmap for v2 Optimization

### Phase 1: Context Isolation (Immediate)
- [ ] **Reset History**: Modify the orchestrator to prune or reset the message history between agents.
- [ ] **State-Only Injection**: Specialists should only receive the `TriageReport` and `TraceResult` via their system prompt templates, not via message history.

### Phase 2: Data Distillation
- [ ] **Tracer Refactoring**: Instruct the `EndToEndTracer` to "Summarize and Clear." It must distill the 70KB log dump into a 500-token summary before the next agent starts.
- [ ] **Tool Truncation**: Update `agentic_ops/tools.py` to provide a "summary" mode for large outputs.

### Phase 3: Dynamic Parallelism
- [ ] **Conditional Dispatch**: Update `orchestrator.py` to dynamically construct the `ParallelAgent` based on the `DispatchAgent`'s output. 

---

## 4. Final Verdict
The multi-agent architecture is the correct long-term path for handling 5G/IMS complexity, but only if the **Conversation History** is managed as a scarce resource. Without context isolation, the system's reasoning will continue to degrade as the stack grows.
