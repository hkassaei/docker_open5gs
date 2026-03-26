# Episode Report: P-CSCF Latency

**Agent:** v3  
**Episode ID:** ep_20260325_214659_p_cscf_latency  
**Date:** 2026-03-25T21:47:00.443821+00:00  
**Duration:** 136.7s  

---

## Scenario

**Category:** network  
**Blast radius:** single_nf  
**Description:** Inject 500ms latency on the P-CSCF (SIP edge proxy). SIP T1 timer is 500ms, so REGISTER transactions will start timing out. Tests IMS resilience to WAN-like latency on the signaling path.

## Faults Injected

- **network_latency** on `pcscf` — {'delay_ms': 500, 'jitter_ms': 50}

## Baseline (Pre-Fault)

Stack phase before injection: **ready**
All containers running at baseline.

## Symptoms Observed

Symptoms detected: **Yes**  
Observation iterations: 1

### Notable Log Lines

**icscf:**
- `[0;39;49m[0;36;49m11(61) INFO: {1 5505 INVITE oQF7tapxwHWBjoT0USNjSpd7qFB4CLrf <null>} ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_result_c`
- `[0;39;49m[0;36;49m12(62) INFO: {1 41330 REGISTER 3XTNTwFj9xCIs1MxVzLCqD5YTsIhBm6t <null>} ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_resul`
- `[0;39;49m[0;36;49m13(63) INFO: {1 8615 REGISTER dP4b5Jfs.f7epCLv7ESWEs72uVAQ2b7D <null>} ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_result`
- `[0;39;49m[0;36;49m14(64) INFO: {1 41332 REGISTER 3XTNTwFj9xCIs1MxVzLCqD5YTsIhBm6t <null>} ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_resul`
- `[0;39;49m[0;36;49m15(65) INFO: {1 8617 REGISTER dP4b5Jfs.f7epCLv7ESWEs72uVAQ2b7D <null>} ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_result`
**nr_gnb:**
- `[2026-03-25 11:48:07.657] [rls] [[36mdebug[m] UE[6] signal lost`
- `[2026-03-25 14:04:58.682] [rls] [[36mdebug[m] UE[8] signal lost`
- `[2026-03-25 15:06:29.945] [rls] [[36mdebug[m] UE[8] signal lost`
- `[2026-03-25 15:06:47.233] [rls] [[36mdebug[m] UE[7] signal lost`
- `[2026-03-25 15:06:47.233] [rls] [[36mdebug[m] UE[8] signal lost`
**scscf:**
- `[0;39;49m[0;39;49m 5(44) DEBUG: ims_auth [authorize.c:337]: reg_await_timer(): [DONE] Looking for expired/useless at 28925004`
- `[0;39;49m[0;39;49m 5(44) DEBUG: ims_auth [authorize.c:283]: reg_await_timer(): Looking for expired/useless at 28925034`
- `[0;39;49m[0;39;49m 5(44) DEBUG: ims_auth [authorize.c:337]: reg_await_timer(): [DONE] Looking for expired/useless at 28925034`
**smf:**
- `[32m03/25 11:48:07.066[0m: [[33msbi[0m] [1;32mINFO[0m: [b6805032-27b3-41f1-9a04-3f025a6967cf] Setup NF Instance [type:PCF] (../lib/sbi/path.c:30`

## Ground Truth

**Failure domain:** ims_signaling  
**Protocol impact:** SIP  
**Affected components:** pcscf  
**Severity:** degraded

## Agent Diagnosis

**Model:** v3-adk/gemini-2.5-flash+gemini-2.5-pro  
**Time to diagnosis:** 131.2s

**Diagnosis:**

> Based on my analysis of the specialist findings, I have synthesized the definitive causal chain.
> 
> ### Cause 1: Malformed Diameter Responses from HSS
> 
> *   **summary**: The I-CSCF cannot process responses from the HSS because they are missing mandatory data fields (AVPs), leading to a breakdown in user registration and call routing logic.
> *   **timeline**:
>     1.  `[ue]` -> `[pcscf]` -> `[icscf]`: A UE initiates a REGISTER or INVITE request, which is forwarded to the I-CSCF.
>     2.  `[icscf]` -> `[pyhss]`: The I-CSCF sends a Diameter request (UAR for registration, LIR for calls) to the HSS to query subscriber location.
>     3.  `[pyhss]` -> `[icscf]`: The `pyhss` container sends a malformed Diameter answer (UAA/LIA) back to the I-CSCF. This response is missing a mandatory AVP.
>     4.  `[icscf]`: The I-CSCF's Diameter module attempts to read the response, specifically looking for the `Result-Code` AVP, and fails.
> ...

### Scoring Breakdown

**Overall score: 0%**

**Scorer assessment:** The agent's diagnosis was entirely incorrect, missing the actual root cause, affected component, severity, and fault type, despite expressing high confidence.

| Dimension | Result | Rationale |
|-----------|--------|-----------|
| Root cause correct | No | The agent identified a Diameter protocol error on the HSS, but the actual injected fault was network latency on the P-CSCF. |
| Component overlap | 0% | The agent identified 'pyhss' and 'icscf' as affected components, while the injected fault was on 'pcscf'. |
| Severity correct | No | The agent described a 'breakdown' and 'effectively breaking all IMS services', which implies an outage, whereas latency causes degradation. |
| Fault type identified | No | The agent identified a 'Malformed Diameter Responses' / 'protocol violation' fault type, not network latency. |
| Confidence calibrated | No | The agent expressed high confidence in a diagnosis that was completely incorrect. |

**Ranking:** The agent provided only one cause, which was incorrect.


### Token Usage

| Metric | Count |
|--------|-------|
| Input tokens | 80,753 |
| Output tokens | 7,228 |
| Thinking tokens | 19,080 |
| **Total tokens** | **107,061** |

**Per-phase breakdown:**

| Phase | Tokens | Tool Calls | LLM Calls |
|-------|--------|------------|-----------|
| TriageAgent | 8,554 | 2 | 2 |
| EndToEndTracer | 32,047 | 2 | 3 |
| DispatchAgent | 4,549 | 0 | 1 |
| TransportSpecialist | 37,464 | 8 | 5 |
| IMSSpecialist | 11,729 | 1 | 2 |
| SynthesisAgent | 12,718 | 0 | 1 |


## Resolution

**Heal method:** scheduled
**Recovery time:** 136.7s

---

## Post-Run Analysis

### Why the agent failed

**The TransportSpecialist checked the wrong containers.** It ran `check_tc_rules` on `scscf` and `icscf` (8 tool calls total) but **never checked `pcscf`** — the container with the actual netem delay rule. Its tool calls were:

```
check_tc_rules("scscf")          ← clean
check_tc_rules("icscf")          ← clean
check_process_listeners("scscf")
check_process_listeners("icscf")
measure_rtt(scscf → icscf)       ← <1ms, healthy
measure_rtt(icscf → scscf)       ← <1ms, healthy
cdp.list_peers on scscf
cdp.list_peers on icscf
```

It focused on `scscf` and `icscf` because those are where the error logs appeared (`Failed finding avp` on icscf, registration flow through scscf). The actual fault was on `pcscf` (upstream), but the symptoms manifest downstream at `icscf`. The agent investigated where errors were logged, not the full signaling path the traffic traverses.

### Positive: I_Open annotation worked

The TransportSpecialist correctly noted "I_Open state is benign" and the SynthesisAgent called it "a red herring." The `run_kamcmd` annotation (Option 2 fix) successfully prevented I_Open fixation. This is progress — previous runs all concluded I_Open was the root cause.

### Negative: Only one cause returned

The synthesis agent produced a single candidate ("Malformed Diameter Responses from HSS") with high confidence. It did not return multiple ranked causes. The correct cause (pcscf latency) was not listed at all because the TransportSpecialist never found it.

### Root issue: selective container checking

The agent doesn't systematically check tc rules on **all containers in the call path** (UE → pcscf → icscf → scscf → pyhss). It selectively checks only the containers with visible errors, which means it misses faults on upstream containers that cause downstream symptoms. A 500ms delay on pcscf causes timeouts that look like Diameter errors on icscf — the symptom and the cause are on different containers.

### What would fix this

The TransportSpecialist needs to check tc rules on every container in the SIP/Diameter signaling path, not just the ones with errors. This is a general principle: network-layer faults on upstream nodes cause application-layer errors on downstream nodes.
