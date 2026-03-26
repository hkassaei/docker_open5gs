# Episode Report: Cascading IMS Failure

**Agent:** v3  
**Episode ID:** ep_20260326_000932_cascading_ims_failure  
**Date:** 2026-03-26T00:09:33.404561+00:00  
**Duration:** 121.0s  

---

## Scenario

**Category:** compound  
**Blast radius:** multi_nf  
**Description:** Kill PyHSS AND add 2-second latency to the S-CSCF. This simulates a cascading failure: the HSS is gone (no Diameter auth) AND the S-CSCF is degraded (slow SIP processing). Total IMS outage.

## Faults Injected

- **container_kill** on `pyhss`
- **network_latency** on `scscf` — {'delay_ms': 2000}

## Baseline (Pre-Fault)

Stack phase before injection: **ready**
All containers running at baseline.

## Symptoms Observed

Symptoms detected: **Yes**  
Observation iterations: 1

### Metrics Changes

| Node | Metric | Baseline | Current | Delta |
|------|--------|----------|---------|-------|
| upf | fivegs_ep_n3_gtp_indatapktn3upf | 14767.0 | 14768.0 | 1.0 |

### Notable Log Lines

**amf:**
- `[32m03/25 18:58:01.869[0m: [[33msbi[0m] [1;32mINFO[0m: [b6805032-27b3-41f1-9a04-3f025a6967cf] (NRF-profile-get) NF registered (../lib/sbi/nf-sm.`
**icscf:**
- `[0;39;49m[0;36;49m16(66) INFO: {1 41336 REGISTER 3XTNTwFj9xCIs1MxVzLCqD5YTsIhBm6t <null>} ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_resul`
- `[0;39;49m[0;36;49m19(69) INFO: {1 8621 REGISTER dP4b5Jfs.f7epCLv7ESWEs72uVAQ2b7D <null>} ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_result`
- `[0;39;49m[0;36;49m20(70) INFO: {1 41338 REGISTER 3XTNTwFj9xCIs1MxVzLCqD5YTsIhBm6t <null>} ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_resul`
- `[0;39;49m[0;36;49m21(71) INFO: {1 8623 REGISTER dP4b5Jfs.f7epCLv7ESWEs72uVAQ2b7D <null>} ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_result`
- `[0;39;49m[0;31;49m 4(54) ERROR: {1 7435 INVITE wgNlNJPhsOxtVh8HKINCUWgG.vQ.3oHT initial_request} <script>: $ru => sip:001011234567892@ims.mnc001.mcc`
**nr_gnb:**
- `[2026-03-25 15:06:47.233] [rls] [[36mdebug[m] UE[7] signal lost`
- `[2026-03-25 15:06:47.233] [rls] [[36mdebug[m] UE[8] signal lost`
- `[2026-03-25 15:32:40.718] [rls] [[36mdebug[m] UE[9] signal lost`
- `[2026-03-25 18:29:24.190] [ngap] [[31m[1merror[m] Association terminated for AMF[2]`
**scscf:**
- `[0;39;49m[0;36;49m26(65) INFO: cdp [receiver.c:923]: receive_loop(): [hss.ims.mnc001.mcc001.3gppnetwork.org] read on socket [12] returned 0 > ... dr`
**smf:**
- `[32m03/25 19:52:55.606[0m: [[33msmf[0m] [1;33mERROR[0m: No N1N2MessageTransferRspData [status:504] (../src/smf/namf-handler.c:61)`
- `[32m03/25 19:52:55.778[0m: [[33msmf[0m] [1;33mERROR[0m: No N1N2MessageTransferRspData [status:504] (../src/smf/namf-handler.c:61)`
- `[32m03/25 19:52:55.801[0m: [[33msmf[0m] [1;33mERROR[0m: No N1N2MessageTransferRspData [status:504] (../src/smf/namf-handler.c:61)`
- `[32m03/25 19:52:55.815[0m: [[33msmf[0m] [1;33mERROR[0m: No N1N2MessageTransferRspData [status:504] (../src/smf/namf-handler.c:61)`
- `[32m03/25 19:55:14.603[0m: [[33msmf[0m] [1;33mERROR[0m: No N1N2MessageTransferRspData [status:504] (../src/smf/namf-handler.c:61)`

## Ground Truth

**Failure domain:** ims_signaling  
**Protocol impact:** SIP  
**Affected components:** scscf, pyhss  
**Severity:** degraded

## Agent Diagnosis

**Model:** v3-adk/gemini-2.5-flash+gemini-2.5-pro  
**Time to diagnosis:** 107.7s

**Diagnosis:**

> An investigation has been conducted into the 5G SA and IMS service degradation. All specialist findings point to a single, definitive root cause.
> 
> ### **Final Diagnosis**
> 
> - **summary**: The IMS Home Subscriber Server (HSS) is down because its container (`pyhss`) has exited, causing all IMS call and registration attempts to fail.
> - **timeline**:
>     1.  `pyhss` container enters an `exited` state.
>     2.  `scscf` detects the HSS is unreachable and drops its Diameter connection (`read on socket [12] returned 0 > ... dropping`).
>     3.  `icscf`'s Diameter peer state for the HSS transitions to `Closed`.
>     4.  A UE initiates a call, sending an `INVITE` which is forwarded through the `pcscf` and `scscf` to the `icscf`.
>     5.  The `icscf` receives the `INVITE` and attempts to query the HSS to find the assigned S-CSCF for the destination subscriber.
>     6.  The query fails instantly because the connection to the HSS is `Closed`, triggering `cxdx_get_result_code: Failed finding avp` and `ERROR: initial_request` logs.
>     7.  The `icscf` cannot route the call and sends back an error, causing the call to fail.
> - **root_cause**: The `pyhss` Docker container, which provides the critical IMS Home Subscriber Server (HSS) functionality, is in an `exited` state. The HSS is the authoritative database for all subscriber identity, authentication, and routing information. Its complete unavailability means other IMS components cannot perform their functions, breaking the entire IMS signaling flow.
> - **affected_components**: `pyhss`, `icscf`, `scscf`.
> - **recommendation**: Restart the `pyhss` container using the appropriate container management command (e.g., `docker restart pyhss`). After restoring service, investigate the container's logs (e.g., `docker logs pyhss`) to determine the underlying reason for the crash and prevent recurrence.
> - **confidence**: high
> - **explanation**: The root cause of the outage is a critical infrastructure failure. The `pyhss` container, which runs the Home Subscriber Server (HSS), has crashed. The HSS is essential for the IMS network, as it tells components like the I-CSCF and S-CSCF how to authenticate users and where to route calls. Since the HSS is down, all Diameter connections to it are closed. When the I-CSCF receives a new call or registration, its attempt to query the HSS fails immediately. This is the direct cause of the `initial_request` errors and `cxdx_get_avp` failures seen in the logs, resulting in a total failure of all IMS services. Restarting the `pyhss` container will restore HSS functionality and resolve the issue.

### Scoring Breakdown

**Overall score: 100%**

**Scorer assessment:** The agent provided an excellent diagnosis, correctly identifying the primary root cause, its affected component, severity, and fault type with high confidence, leading to a complete understanding of the IMS outage.

| Dimension | Result | Rationale |
|-----------|--------|-----------|
| Root cause correct | Yes | The agent correctly identified the 'container_kill' on 'pyhss' as the primary root cause, which is one of the actual injected faults. |
| Component overlap | 100% | The agent identified both 'pyhss' and 'scscf', which were the two containers targeted by the injected faults. It also listed 'icscf' but this is not penalized. |
| Severity correct | Yes | The agent correctly assessed the severity of the 'pyhss' fault as 'down', 'exited', and 'crashed', matching the 'container_kill' injection. |
| Fault type identified | Yes | The agent identified the fault type for 'pyhss' as 'exited'/'crashed', which accurately describes a 'container_kill' event. |
| Confidence calibrated | Yes | The agent's high confidence is appropriate as it accurately identified a critical root cause ('pyhss' kill) that explains the total IMS outage, even though it missed a secondary injected fault. |

**Ranking position:** #1 — The agent provided only one root cause, which was correct, placing it at position 1.


### Token Usage

| Metric | Count |
|--------|-------|
| Input tokens | 100,953 |
| Output tokens | 3,721 |
| Thinking tokens | 14,064 |
| **Total tokens** | **118,738** |

**Per-phase breakdown:**

| Phase | Tokens | Tool Calls | LLM Calls |
|-------|--------|------------|-----------|
| TriageAgent | 11,428 | 2 | 3 |
| EndToEndTracer | 64,987 | 8 | 5 |
| DispatchAgent | 4,760 | 0 | 1 |
| TransportSpecialist | 13,093 | 2 | 3 |
| SubscriberDataSpecialist | 7,472 | 1 | 2 |
| IMSSpecialist | 9,762 | 1 | 2 |
| SynthesisAgent | 7,236 | 0 | 1 |


## Resolution

**Heal method:** scheduled  
**Recovery time:** 121.0s
