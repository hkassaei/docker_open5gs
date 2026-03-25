# Episode Report: P-CSCF Latency

**Agent:** v1.5  
**Episode ID:** ep_20260324_211613_p_cscf_latency  
**Date:** 2026-03-24T21:16:13.859602+00:00  
**Duration:** 95.4s  

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
- `[0;39;49m[0;36;49m10(60) INFO: ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_result_code: Failed finding avp`
- `[0;39;49m[0;31;49m 1(51) ERROR: {1 5505 INVITE oQF7tapxwHWBjoT0USNjSpd7qFB4CLrf initial_request} <script>: $ru => sip:001011234567892@ims.mnc001.mcc`
- `[0;39;49m[0;36;49m11(61) INFO: ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_experimental_result_code: Failed finding avp`
- `[0;39;49m[0;36;49m12(62) INFO: ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_result_code: Failed finding avp`
- `[0;39;49m[0;36;49m13(63) INFO: ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_result_code: Failed finding avp`
**nr_gnb:**
- `[2026-03-24 15:02:40.218] [ngap] [[31m[1merror[m] Unhandled NGAP initiating-message received (9)`
- `[2026-03-24 15:02:40.335] [ngap] [[31m[1merror[m] Unhandled NGAP initiating-message received (9)`
- `[2026-03-24 15:02:40.349] [ngap] [[31m[1merror[m] Unhandled NGAP initiating-message received (9)`
- `[2026-03-24 15:02:40.357] [ngap] [[31m[1merror[m] Unhandled NGAP initiating-message received (9)`
- `[2026-03-24 15:26:53.517] [ngap] [[31m[1merror[m] Unhandled NGAP initiating-message received (9)`

## Ground Truth

**Failure domain:** ims_signaling  
**Protocol impact:** SIP  
**Affected components:** pcscf  
**Severity:** degraded

## Agent Diagnosis

**Model:** v1.5-pydantic/google-vertex:gemini-2.5-pro  
**Time to diagnosis:** 94.5s

**Summary:** VoNR call failure due to loss of Diameter connectivity between IMS CSCFs and the HSS.

**Root cause identified:** The Diameter service within the PyHSS container or the underlying transport has failed. Both the I-CSCF and S-CSCF are unable to establish a functional Diameter connection with the HSS (PyHSS), as evidenced by their peer connections being stuck in the 'I_Open' state. This prevents the I-CSCF from executing a Location-Information-Request (LIR) to find the terminating subscriber, causing the call setup to fail.

**Components identified:** icscf, scscf, pyhss

### Scoring Breakdown

**Overall score: 15%**

| Dimension | Result |
|-----------|--------|
| Root cause correct | No |
| Component overlap | 0% |
| Severity correct | Yes |
| Fault type identified | No |
| Confidence calibrated | No |

**Verdict:** The agent failed to diagnose this scenario. The root cause was either missed entirely or the agent fixated on the wrong issue.

### Token Usage

| Metric | Count |
|--------|-------|
| Input tokens | 507,949 |
| Output tokens | 6,140 |
| **Total tokens** | **514,089** |
| LLM requests | 11 |
| Tool calls | 13 |


## Resolution

**Heal method:** scheduled  
**Recovery time:** 95.4s
