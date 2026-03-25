# Episode Report: P-CSCF Latency

**Agent:** v3  
**Episode ID:** ep_20260325_204620_p_cscf_latency  
**Date:** 2026-03-25T20:46:21.642908+00:00  
**Duration:** 95.0s  

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

### Metrics Changes

| Node | Metric | Baseline | Current | Delta |
|------|--------|----------|---------|-------|
| pcscf | httpclient:connfail | 8461.0 | 8462.0 | 1.0 |
| pcscf | core:rcv_requests_options | 8456.0 | 8457.0 | 1.0 |

### Notable Log Lines

**icscf:**
- `[0;39;49m[0;36;49m24(74) INFO: ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_result_code: Failed finding avp`
- `[0;39;49m[0;36;49m 9(59) INFO: {1 41328 REGISTER 3XTNTwFj9xCIs1MxVzLCqD5YTsIhBm6t <null>} ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_resul`
- `[0;39;49m[0;36;49m10(60) INFO: {1 8613 REGISTER dP4b5Jfs.f7epCLv7ESWEs72uVAQ2b7D <null>} ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_result`
- `[0;39;49m[0;36;49m11(61) INFO: {1 5505 INVITE oQF7tapxwHWBjoT0USNjSpd7qFB4CLrf <null>} ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_result_c`
- `[0;39;49m[0;36;49m12(62) INFO: {1 41330 REGISTER 3XTNTwFj9xCIs1MxVzLCqD5YTsIhBm6t <null>} ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_resul`
**nr_gnb:**
- `[2026-03-25 11:48:07.657] [rls] [[36mdebug[m] UE[6] signal lost`
- `[2026-03-25 14:04:58.682] [rls] [[36mdebug[m] UE[8] signal lost`
- `[2026-03-25 15:06:29.945] [rls] [[36mdebug[m] UE[8] signal lost`
- `[2026-03-25 15:06:47.233] [rls] [[36mdebug[m] UE[7] signal lost`
- `[2026-03-25 15:06:47.233] [rls] [[36mdebug[m] UE[8] signal lost`
**smf:**
- `[32m03/25 11:48:07.066[0m: [[33msbi[0m] [1;32mINFO[0m: [b6805032-27b3-41f1-9a04-3f025a6967cf] Setup NF Instance [type:PCF] (../lib/sbi/path.c:30`
- `[32m03/25 11:48:07.066[0m: [[33msbi[0m] [1;32mINFO[0m: [b6805032-27b3-41f1-9a04-3f025a6967cf] Setup NF Instance [type:PCF] (../lib/sbi/path.c:30`

## Ground Truth

**Failure domain:** ims_signaling  
**Protocol impact:** SIP  
**Affected components:** pcscf  
**Severity:** degraded

## Agent Diagnosis

**Model:** v3-adk/gemini-2.5-flash+gemini-2.5-pro  
**Time to diagnosis:** 94.2s

**Summary:** Incomplete subscriber profiles in the HSS database are causing I-CSCF to fail Diameter queries, preventing IMS call setup and registration.

**Root cause identified:** The `ims_subscriber` table in the HSS database contains incomplete data; specifically, the `attributes` list is empty (`[]`) for affected subscribers. When the I-CSCF queries the HSS via a Diameter LIR, the HSS returns a valid but incomplete LIA response. The I-CSCF, expecting a specific AVP that is not present, fails its internal processing and discards the user's SIP request, causing a delivery failure.

**Components identified:** hss, icscf

### Scoring Breakdown

**Overall score: 0%**

| Dimension | Result |
|-----------|--------|
| Root cause correct | No |
| Component overlap | 0% |
| Severity correct | No |
| Fault type identified | No |
| Confidence calibrated | No |

**Verdict:** The agent failed to diagnose this scenario. The root cause was either missed entirely or the agent fixated on the wrong issue.

### Token Usage

| Metric | Count |
|--------|-------|
| Input tokens | 79,966 |
| Output tokens | 4,099 |
| Thinking tokens | 13,293 |
| **Total tokens** | **97,358** |

**Per-phase breakdown:**

| Phase | Tokens | Tool Calls | LLM Calls |
|-------|--------|------------|-----------|
| TriageAgent | 9,105 | 2 | 2 |
| EndToEndTracer | 28,833 | 3 | 4 |
| DispatchAgent | 4,442 | 0 | 1 |
| TransportSpecialist | 26,425 | 5 | 5 |
| SubscriberDataSpecialist | 11,776 | 1 | 2 |
| IMSSpecialist | 9,777 | 1 | 2 |
| SynthesisAgent | 7,000 | 0 | 1 |


## Resolution

**Heal method:** scheduled  
**Recovery time:** 95.0s
