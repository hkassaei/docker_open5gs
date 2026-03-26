# Episode Report: AMF Restart (Upgrade Simulation)

**Agent:** v3  
**Episode ID:** ep_20260325_225555_amf_restart_(upgrade_simulatio  
**Date:** 2026-03-25T22:55:56.144387+00:00  
**Duration:** 125.4s  

---

## Scenario

**Category:** container  
**Blast radius:** multi_nf  
**Description:** Stop the AMF for 10 seconds, then restart it. Simulates a rolling upgrade of the access and mobility management function. UEs will temporarily lose their 5G NAS connection and must re-attach.

## Faults Injected

- **container_stop** on `amf` — {'timeout': 10}

## Baseline (Pre-Fault)

Stack phase before injection: **ready**
All containers running at baseline.

## Symptoms Observed

Symptoms detected: **Yes**  
Observation iterations: 1

### Metrics Changes

| Node | Metric | Baseline | Current | Delta |
|------|--------|----------|---------|-------|
| pcscf | httpclient:connfail | 10003.0 | 10005.0 | 2.0 |
| pcscf | core:rcv_requests_options | 9998.0 | 10000.0 | 2.0 |
| upf | fivegs_ep_n3_gtp_indatapktn3upf | 13287.0 | 13288.0 | 1.0 |

### Notable Log Lines

**amf:**
- `[32m03/25 18:31:14.945[0m: [[33msbi[0m] [1;32mINFO[0m: [b6805032-27b3-41f1-9a04-3f025a6967cf] (NRF-profile-get) NF registered (../lib/sbi/nf-sm.`
**icscf:**
- `[0;39;49m[0;36;49m18(68) INFO: {1 8619 REGISTER dP4b5Jfs.f7epCLv7ESWEs72uVAQ2b7D <null>} ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_result`
- `[0;39;49m[0;36;49m16(66) INFO: {1 41336 REGISTER 3XTNTwFj9xCIs1MxVzLCqD5YTsIhBm6t <null>} ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_resul`
- `[0;39;49m[0;36;49m19(69) INFO: {1 8621 REGISTER dP4b5Jfs.f7epCLv7ESWEs72uVAQ2b7D <null>} ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_result`
**nr_gnb:**
- `[2026-03-25 15:06:47.233] [rls] [[36mdebug[m] UE[7] signal lost`
- `[2026-03-25 15:06:47.233] [rls] [[36mdebug[m] UE[8] signal lost`
- `[2026-03-25 15:32:40.718] [rls] [[36mdebug[m] UE[9] signal lost`
- `[2026-03-25 18:29:24.190] [ngap] [[31m[1merror[m] Association terminated for AMF[2]`

## Ground Truth

**Failure domain:** core_control_plane  
**Protocol impact:** NGAP  
**Affected components:** amf  
**Severity:** degraded

## Agent Diagnosis

**Model:** v3-adk/gemini-2.5-flash+gemini-2.5-pro  
**Time to diagnosis:** 108.5s

**Diagnosis:**

> Based on the evidence from all specialists, I have synthesized the findings to construct the definitive causal chain.
> 
> ### **Primary Cause (Highest Probability)**
> 
> *   **summary**: The AMF container has crashed, leading to a complete 5G core control plane failure and preventing all UEs from attaching to the network.
> *   **timeline**:
>     *   `[nr_gnb]` `[2026-03-25 15:06:47.233]` - `[debug] UE[7] signal lost`
>     *   `[nr_gnb]` `[2026-03-25 18:29:24.190]` - `[error] Association terminated for AMF[2]`
>     *   `[amf]` `[Triage/Core Report]` - Container status confirmed as `exited`. `read_running_config` fails.
> *   **root_cause**: The `amf` container is in an `exited` state. The AMF is the central component for managing UE connections, registration, and mobility in the 5G core. Its failure means it can no longer maintain the N2 interface with the RAN (`nr_gnb`), causing the gNB to terminate the association. This makes it impossible for any UE to attach to the 5G network.
> *   **affected_components**: `amf`, `nr_gnb`, all UEs.
> *   **recommendation**: Restart the `amf` container. After it is running, analyze its persistent logs to determine the underlying reason for the crash (e.g., memory exhaustion, fatal error, misconfiguration).
> *   **confidence**: high
> *   **explanation**: The root cause of the entire outage is the AMF container, which has crashed and is not running. The AMF acts as the "front door" for the 5G core network. With it being offline, the RAN (`nr_gnb`) terminated its connection, as confirmed by the "Association terminated for AMF" log. This prevents any UEs from attaching, authenticated, or maintaining a connection to the network. All other errors observed in the IMS layer are downstream symptoms of this foundational core network failure.
> 
> ### **Secondary Cause (Symptom)**
> 
> *   **summary**: The I-CSCF is failing IMS registration attempts because it cannot retrieve required subscriber data (AVPs) from the HSS.
> *   **timeline**:
>     *   `[icscf]` `[Recent Logs]` - `INFO: ... REGISTER ... cxdx_get_avp(): cxdx_get_result_code: Failed finding avp`
> *   **root_cause**: This is a **cascading symptom** of the primary AMF failure. When the `icscf` receives a `REGISTER` request, it queries the `hss` for the user's profile and assigned S-CSCF. The `hss`'s ability to fulfill this request depends on a functional 5G core for authentication (via AUSF, managed by AMF). With the AMF down, the `hss` cannot authenticate the user and returns an error to the `icscf`, which manifests as the "Failed finding avp" message. The transport layer between `icscf` and `hss` is confirmed to be healthy.
> *   **affected_components**: `icscf`, `hss`, IMS UEs.
> *   **recommendation**: No direct action required. This issue will resolve itself once the primary root cause (the crashed `amf` container) is fixed and the 5G core is restored.
> *   **confidence**: high
> *   **explanation**: The IMS registration failures you are seeing on the `icscf` are a direct consequence of the AMF being down. The `icscf` is correctly trying to fetch subscriber data from the HSS, but the HSS cannot provide it because it relies on the now-offline 5G core for user authentication. The Transport Specialist confirmed the connection between these components is fine; the problem is the HSS is returning an error message because its own dependencies are broken. Fixing the AMF will restore the core functions, which will allow the HSS to operate correctly and resolve these IMS errors.

### Scoring Breakdown

**Overall score: 100%**

**Scorer assessment:** The agent accurately identified the AMF container as the primary cause, its exited state, and the cascading impact on the network, demonstrating excellent diagnostic capabilities.

| Dimension | Result | Rationale |
|-----------|--------|-----------|
| Root cause correct | Yes | The agent correctly identified the AMF container as the primary cause, stating it had 'crashed' or was in an 'exited' state, which accurately reflects the impact of a container_stop fault. |
| Component overlap | 100% | The agent correctly identified 'amf' as the affected component, which was the sole target of the injected fault. |
| Severity correct | Yes | The agent described the AMF as 'crashed' and in an 'exited' state, which accurately reflects the severity of a container_stop fault. |
| Fault type identified | Yes | The agent identified the fault type as a container 'crash' or 'exited' state, which is semantically equivalent to a container_stop fault. |
| Confidence calibrated | Yes | The agent expressed 'high' confidence, which is appropriate given the accuracy and detail of its diagnosis. |

**Ranking position:** #1 — The correct cause (AMF container issue) was identified as the 'Primary Cause', ranking it first.


### Token Usage

| Metric | Count |
|--------|-------|
| Input tokens | 74,781 |
| Output tokens | 6,675 |
| Thinking tokens | 19,468 |
| **Total tokens** | **100,924** |

**Per-phase breakdown:**

| Phase | Tokens | Tool Calls | LLM Calls |
|-------|--------|------------|-----------|
| TriageAgent | 7,585 | 2 | 2 |
| EndToEndTracer | 29,991 | 2 | 3 |
| DispatchAgent | 4,190 | 0 | 1 |
| TransportSpecialist | 25,170 | 3 | 4 |
| CoreSpecialist | 8,097 | 1 | 2 |
| SubscriberDataSpecialist | 5,988 | 0 | 1 |
| IMSSpecialist | 10,795 | 1 | 2 |
| SynthesisAgent | 9,108 | 0 | 1 |


## Resolution

**Heal method:** scheduled  
**Recovery time:** 125.4s
