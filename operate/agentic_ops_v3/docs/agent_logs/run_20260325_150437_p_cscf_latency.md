# Episode Report: P-CSCF Latency

**Agent:** v3  
**Episode ID:** ep_20260325_150246_p_cscf_latency  
**Date:** 2026-03-25T15:02:47.261578+00:00  
**Duration:** 109.4s  

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

**e2e_ue1:**
- `10:58:51.812            pjsua_acc.c  ...SIP registration failed, status=408 (Request Timeout)`
**e2e_ue2:**
- `10:59:21.307            pjsua_acc.c  ...SIP registration failed, status=408 (Request Timeout)`
**icscf:**
- `[0;39;49m[0;36;49m19(69) INFO: ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_result_code: Failed finding avp`
- `[0;39;49m[0;36;49m20(70) INFO: ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_result_code: Failed finding avp`
- `[0;39;49m[0;36;49m21(71) INFO: ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_result_code: Failed finding avp`
- `[0;39;49m[0;36;49m22(72) INFO: ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_result_code: Failed finding avp`
- `[0;39;49m[0;36;49m23(73) INFO: ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_result_code: Failed finding avp`
**nr_gnb:**
- `[2026-03-24 22:23:56.032] [rls] [[36mdebug[m] UE[3] signal lost`
- `[2026-03-24 22:23:57.036] [rls] [[36mdebug[m] UE[4] signal lost`
- `[2026-03-25 03:49:42.859] [rls] [[36mdebug[m] UE[5] signal lost`
- `[2026-03-25 07:33:57.300] [rls] [[36mdebug[m] UE[5] signal lost`
- `[2026-03-25 09:12:27.019] [rls] [[36mdebug[m] UE[6] signal lost`
**scscf:**
- `[0;39;49m[0;39;49m 5(44) DEBUG: ims_usrloc_scscf [ims_usrloc_scscf_mod.c:500]: timer(): Syncing cache`

## Ground Truth

**Failure domain:** ims_signaling  
**Protocol impact:** SIP  
**Affected components:** pcscf  
**Severity:** degraded

## Agent Diagnosis

**Model:** v3-adk/eod-sbox-entitlement-server  
**Time to diagnosis:** 108.7s

**Summary:** UE registration is failing due to a broken Diameter connection between the I-CSCF and HSS.

**Root cause identified:** The Diameter peer connection from the I-CSCF to the HSS is stuck in the `I_Open` state, as confirmed by the `kamcmd` query. This indicates an incomplete connection handshake. This prevents the I-CSCF from performing User-Authorization-Request (UAR) lookups, which are mandatory for finding the correct S-CSCF for a registering user. Without a successful HSS lookup, the SIP REGISTER request cannot be forwarded, causing the entire transaction to stall and eventually time out at the UE.

**Components identified:** icscf, hss, pcscf, e2e_ue1, e2e_ue2

### Scoring Breakdown

**Overall score: 25%**

| Dimension | Result |
|-----------|--------|
| Root cause correct | No |
| Component overlap | 100% |
| Severity correct | No |
| Fault type identified | No |
| Confidence calibrated | No |

**Verdict:** The agent failed to diagnose this scenario. The root cause was either missed entirely or the agent fixated on the wrong issue.

### Token Usage

| Metric | Count |
|--------|-------|
| Input tokens | 78,700 |
| Output tokens | 3,120 |
| Thinking tokens | 16,203 |
| **Total tokens** | **98,023** |

**Per-phase breakdown:**

| Phase | Tokens | Tool Calls | LLM Calls |
|-------|--------|------------|-----------|
| TriageAgent | 12,746 | 2 | 3 |
| EndToEndTracer | 28,523 | 3 | 4 |
| DispatchAgent | 4,459 | 0 | 1 |
| TransportSpecialist | 29,185 | 4 | 5 |
| IMSSpecialist | 15,899 | 2 | 3 |
| SynthesisAgent | 7,211 | 0 | 1 |


## Resolution

**Heal method:** scheduled  
**Recovery time:** 109.4s
