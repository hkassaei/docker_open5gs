# Episode Report: Data Plane Degradation

**Agent:** v3  
**Episode ID:** ep_20260325_235250_data_plane_degradation  
**Date:** 2026-03-25T23:52:51.606670+00:00  
**Duration:** 142.0s  

---

## Scenario

**Category:** network  
**Blast radius:** single_nf  
**Description:** Inject 30% packet loss on the UPF. RTP media streams will degrade, voice quality drops. Tests whether the stack detects and reports data plane quality issues.

## Faults Injected

- **network_loss** on `upf` — {'loss_pct': 30}

## Baseline (Pre-Fault)

Stack phase before injection: **ready**
All containers running at baseline.

## Symptoms Observed

Symptoms detected: **Yes**  
Observation iterations: 1

### Metrics Changes

| Node | Metric | Baseline | Current | Delta |
|------|--------|----------|---------|-------|
| icscf | ims_icscf:lir_avg_response_time | 54.0 | 73.0 | 19.0 |
| icscf | core:rcv_requests_invite | 1.0 | 2.0 | 1.0 |
| icscf | cdp:replies_response_time | 2575.0 | 2668.0 | 93.0 |
| icscf | ims_icscf:lir_replies_received | 1.0 | 2.0 | 1.0 |
| icscf | cdp:replies_received | 29.0 | 30.0 | 1.0 |
| icscf | ims_icscf:lir_replies_response_time | 54.0 | 147.0 | 93.0 |
| pcscf | httpclient:connfail | 10686.0 | 10689.0 | 3.0 |
| pcscf | httpclient:connok | 2.0 | 4.0 | 2.0 |
| pcscf | dialog_ng:active | 0.0 | 2.0 | 2.0 |
| pcscf | dialog_ng:processed | 2.0 | 4.0 | 2.0 |
| pcscf | core:rcv_requests_invite | 2.0 | 4.0 | 2.0 |
| pcscf | core:rcv_requests_options | 10681.0 | 10682.0 | 1.0 |
| pcscf | sl:1xx_replies | 58.0 | 60.0 | 2.0 |
| scscf | dialog_ng:active | 0.0 | 2.0 | 2.0 |
| scscf | dialog_ng:processed | 0.0 | 2.0 | 2.0 |
| scscf | core:rcv_requests_invite | 0.0 | 2.0 | 2.0 |
| smf | bearers_active | 4.0 | 5.0 | 1.0 |
| upf | fivegs_ep_n3_gtp_indatapktn3upf | 13815.0 | 13816.0 | 1.0 |

### Notable Log Lines

**amf:**
- `[32m03/25 18:58:01.869[0m: [[33msbi[0m] [1;32mINFO[0m: [b6805032-27b3-41f1-9a04-3f025a6967cf] (NRF-profile-get) NF registered (../lib/sbi/nf-sm.`
**e2e_ue1:**
- `19:52:55.818     strm0x7ac744009298 !Resetting jitter buffer in stream playback start`
**e2e_ue2:**
- `19:52:55.803     strm0x76a6a402dda8 !Resetting jitter buffer in stream playback start`
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
- `[0;39;49m[0;39;49m 2(41) DEBUG: {1 7435 ACK wgNlNJPhsOxtVh8HKINCUWgG.vQ.3oHT DEFAULT_ROUTE} ims_usrloc_scscf [contact_dlg_handlers.c:251]: contact_d`
**smf:**
- `[32m03/25 19:52:55.606[0m: [[33msmf[0m] [1;33mERROR[0m: No N1N2MessageTransferRspData [status:504] (../src/smf/namf-handler.c:61)`
- `[32m03/25 19:52:55.778[0m: [[33msmf[0m] [1;33mERROR[0m: No N1N2MessageTransferRspData [status:504] (../src/smf/namf-handler.c:61)`
- `[32m03/25 19:52:55.801[0m: [[33msmf[0m] [1;33mERROR[0m: No N1N2MessageTransferRspData [status:504] (../src/smf/namf-handler.c:61)`
- `[32m03/25 19:52:55.815[0m: [[33msmf[0m] [1;33mERROR[0m: No N1N2MessageTransferRspData [status:504] (../src/smf/namf-handler.c:61)`

## Ground Truth

**Failure domain:** data_plane  
**Protocol impact:** GTP-U  
**Affected components:** upf  
**Severity:** degraded

## Agent Diagnosis

**Model:** v3-adk/gemini-2.5-flash+gemini-2.5-pro  
**Time to diagnosis:** 129.6s

**Diagnosis:**

> Here is my synthesis of the specialist findings. I have identified two primary, independent root causes and one latent configuration issue contributing to the observed failures. They are ranked by their impact on the overall service.
> 
> ### **Cause #1: 5G Core Control Plane Failure**
> 
> - **summary**: The fundamental issue is a complete breakdown of the 5G control plane. The Access and Mobility Management Function (AMF) is misconfigured and cannot establish a connection with the RAN (gNB). This prevents any UE from attaching to the network, rendering all other services inaccessible.
> - **timeline**:
>     - `[nr_gnb]` boots and attempts to establish an N2 interface connection to the AMF.
>     - `[amf]` receives the connection attempt but lacks the necessary configuration to identify and authorize the `nr_gnb` as a valid peer.
>     - `[amf]` rejects or terminates the connection.
>     - `[nr_gnb]` logs `[ngap] [error] Association terminated for AMF[2]`.
>     - `[amf]` metric `ran_ue` remains at `0.0` as no UEs can complete the attachment procedure.
>     - `[smf]` attempts to send messages to UEs (e.g., for PDU session modification) via the AMF, but these fail because there is no path to the UE, resulting in `ERROR: No N1N2MessageTransferRspData`.
> - **root_cause**: **Missing gNB peer configuration in the AMF.** The Core Specialist correctly identified that the AMF's configuration file is missing the IP address of the gNB in its `ngap` settings. The N2 interface between the gNB and AMF is the foundation of the control plane; without this explicit peering information, the AMF cannot form a stable NGAP association with the RAN.
> - **affected_components**: `amf`, `nr_gnb`, `smf`, and all UEs attempting to connect.
> - **recommendation**: In the AMF's configuration file, add the gNB's IP address to the `ngap` peer list. This will allow the AMF to recognize the gNB and successfully establish the required N2 association.
> - **confidence**: high
> - **explanation**: The root cause of the entire outage is a critical misconfiguration in the 5G Core. UEs are unable to attach to the network because the AMF (the "brain" of the control plane) does not know the address of the gNB (the radio tower). This is like an airport's control tower not having the runway on its map. The `gNB-AMF association terminated` error is the direct result of this. Consequently, no UE can get on the network, which is why the `ran_ue` count is zero. All downstream errors, like the SMF failing to transfer messages, are symptoms of this fundamental connectivity failure.
> 
> ---
> ### **Cause #2: Invalid IMS Subscriber Profile in HSS**
> 
> - **summary**: A specific VoNR call is failing due to corrupted subscriber data in the Home Subscriber Server (HSS). While unrelated to the core network outage, this prevents successful call completion for the affected user.
> - **timeline**:
>     - `[e2e_ue1]` sends an `INVITE` for user `001011234567892`.
>     - The `INVITE` traverses the `P-CSCF` and `S-CSCF` to the `I-CSCF`.
>     - `[icscf]` receives the `INVITE` and sends a Diameter Location-Info-Request (LIR) to the HSS (`pyhss`) to find the currently assigned S-CSCF for the called party.
>     - `[pyhss]` retrieves the profile for IMSI `001011234567892` and finds the `sh_profile` field contains the invalid literal value `"string"`.
>     - `[pyhss]` cannot construct a valid Diameter response because the data is malformed. It sends back a response missing the required Attribute-Value Pairs (AVPs).
>     - `[icscf]` receives the deficient response and logs `cxdx_get_avp(): cxdx_get_result_code: Failed finding avp`, followed by `ERROR: {1 7435 INVITE ...}`. The call fails.
> - **root_cause**: **Malformed `sh_profile` data in the HSS database.** The Subscriber Data Specialist provided direct evidence that the user's profile contains `sh_profile: "string"`. This is not a valid XML document as required by the Sh interface specification. When the I-CSCF queries the HSS for this user's location, the HSS cannot process this invalid data and fails to return the necessary routing information (AVPs), causing the I-CSCF to abort the call setup.
> - **affected_components**: `icscf`, `pyhss` (HSS), `e2e_ue1` (as the caller to the affected subscriber).
> - **recommendation**: Access the HSS database and correct the `ims_details` record for the subscriber with IMSI `001011234567892`. The `sh_profile` field must be updated from `"string"` to a valid, well-formed XML document that defines the user's service profile.
> - **confidence**: high
> - **explanation**: The reason the specific VoNR call is failing is due to a "typo" in the subscriber's master record within the HSS. When the I-CSCF asks the HSS "Where do I send this call?", the HSS looks up the user's profile. However, a critical field, `sh_profile`, contains the garbage value "string" instead of the required XML data. Unable to make sense of this, the HSS fails to provide a complete answer. The I-CSCF, not receiving the information it needs, gives up and terminates the call, logging the "Failed finding avp" error.
> 
> ---
> ### **Cause #3: Latent I-CSCF Misconfiguration**
> 
> - **summary**: The I-CSCF is configured with a static, hardcoded HSS peer. This is a fragile design that eliminates redundancy and was a competing but less likely cause of the IMS failure. It is a latent risk that should be remediated.
> - **timeline**: This configuration is static and affects every Diameter query from the I-CSCF. During the IMS call failure, this setting forced the I-CSCF to send its LIR to the one and only peer it knew, rather than using dynamic discovery.
> - **root_cause**: **The `cxdx_forced_peer` parameter is enabled in the I-CSCF configuration.** The IMS specialist provided evidence of this setting. This parameter overrides standard Diameter routing (based on destination realm) and forces all Cx/Dx requests to a single HSS instance. If that instance is down or not authoritative for a user, requests will fail.
> - **affected_components**: `icscf`.
> - **recommendation**: In the `icscf.cfg` file, comment out or remove the `modparam("ims_icscf", "cxdx_forced_peer", ...)` line. This will allow the I-CSCF to revert to standard, more resilient Diameter routing using the `cxdx_dest_realm` for dynamic peer discovery.
> - **confidence**: high (for the existence of the misconfiguration); low (as the direct cause of this specific incident compared to Cause #2).
> - **explanation**: The I-CSCF is currently configured to only talk to a single, hardcoded HSS. This is risky and not best practice, as it creates a single point of failure. While the immediate call failure was caused by bad subscriber data (Cause #2), this configuration is a ticking time bomb. If that one HSS peer were to fail, all IMS location queries would fail. Disabling this forced-peer setting will allow the I-CSCF to use standard, more robust service discovery to find an available HSS, improving the overall resilience of the IMS platform.

### Scoring Breakdown

**Overall score: 0%**

**Scorer assessment:** The agent completely failed to identify the injected fault, diagnosing multiple unrelated configuration issues with high confidence, resulting in a total score of 0.0.

| Dimension | Result | Rationale |
|-----------|--------|-----------|
| Root cause correct | No | The agent failed to identify the injected fault of 30% packet loss on the UPF, instead diagnosing unrelated control plane and IMS configuration issues. |
| Component overlap | 0% | The agent did not identify the 'upf' container, which was the target of the injected network loss. |
| Severity correct | No | The injected fault was a degradation (30% packet loss), but the agent diagnosed complete outages and failures, which is a higher severity than the actual impact. |
| Fault type identified | No | The agent identified configuration issues and data corruption as fault types, not network loss. |
| Confidence calibrated | No | The agent expressed high confidence in a diagnosis that was entirely incorrect, indicating poor calibration. |

**Ranking:** The actual injected fault was not identified or ranked by the agent.


### Token Usage

| Metric | Count |
|--------|-------|
| Input tokens | 149,806 |
| Output tokens | 5,821 |
| Thinking tokens | 24,565 |
| **Total tokens** | **180,192** |

**Per-phase breakdown:**

| Phase | Tokens | Tool Calls | LLM Calls |
|-------|--------|------------|-----------|
| TriageAgent | 14,507 | 2 | 3 |
| EndToEndTracer | 27,724 | 2 | 3 |
| DispatchAgent | 6,287 | 0 | 1 |
| TransportSpecialist | 71,487 | 12 | 9 |
| SubscriberDataSpecialist | 16,157 | 1 | 2 |
| IMSSpecialist | 20,417 | 2 | 3 |
| CoreSpecialist | 12,651 | 1 | 2 |
| SynthesisAgent | 10,962 | 0 | 1 |


## Resolution

**Heal method:** scheduled
**Recovery time:** 136.7s

---

## Post-Run Analysis

### Why the agent failed

#### 1. TransportSpecialist never checked `upf`

12 tool calls, 71K tokens, and `check_tc_rules("upf")` was never called. The agent checked `nr_gnb`, `amf`, and `icscf` — containers mentioned in error logs. The UPF wasn't mentioned in any error log because 30% packet loss doesn't produce UPF-level errors — packets are silently dropped at the kernel level by the netem rule. Since the UPF had no errors, the agent had no reason to look at it.

TransportSpecialist tool calls:
```
check_tc_rules("nr_gnb")              ← wrong container
check_tc_rules("amf")                 ← wrong container
check_tc_rules("icscf")               ← wrong container
read_running_config(icscf, "diameter")
read_running_config(icscf, "HSS")
cdp.list_peers on icscf
measure_rtt(icscf → "hss")
measure_rtt(nr_gnb → "amf")
read_running_config(icscf, "hss.ims")
check_process_listeners("icscf")
check_process_listeners("hss")
check_process_listeners("pyhss")
```

Never once inspected the UPF — the container with the actual fault.

#### 2. Triage marked the data plane GREEN (false negative)

Triage reported "5G Data Plane Layer: GREEN" because `fivegs_ep_n3_gtp_indatapktn3upf = 13899` — non-zero. But triage only checks zero/non-zero, not whether the *rate* has dropped. With 30% packet loss, the counter still increments (70% of packets get through), so triage sees "packets flowing" and calls it healthy. Detecting degradation requires comparing the current increment rate against the baseline rate — a rate-based anomaly check, not a threshold check.

#### 3. Stale logs dominated the investigation (third consecutive run)

- **Cause #1** ("AMF misconfiguration"): Built entirely on `Association terminated for AMF[2]` from `18:29:24` — **over 1.5 hours old**, from a previous AMF restart scenario.
- **Cause #2** ("Invalid subscriber profile"): Built on `Failed finding avp` — the permanent I_Open artifact, not caused by packet loss.
- **Cause #3** ("Latent I-CSCF misconfiguration"): A real but irrelevant config observation unrelated to the injected fault.

The SMF `N1N2MessageTransferRspData` errors from `19:52:55` are actually fresh and plausibly related to the packet loss (PFCP messages between SMF↔UPF getting dropped), but the agent attributed them to the stale AMF error instead.

#### 4. Active call symptoms were present but unrecognized

The UE logs showed `Resetting jitter buffer in stream playback start` — this is a pjsua symptom of packet loss causing audio glitches. The call was active and degraded, but the agent didn't recognize jitter buffer resets as a data plane quality indicator.

The GTP packet counter delta was only +1 in the 5-second observation window — far below the expected ~50 pkt/s during an active RTP call. This is a clear anomaly but the agent didn't flag it because triage only checks non-zero, not rate.

### Gaps exposed

1. **TransportSpecialist has no concept of "data path"** — it doesn't know that for an active call, the path is UE → gNB → UPF → ogstun → UPF → gNB → UE. It should check tc rules on every node in the data path, not just containers with errors.
2. **Triage doesn't detect rate degradation** — only checks zero vs non-zero for metrics, not whether the rate dropped relative to baseline. 30% packet loss shows up as a reduced rate, not a zero.
3. **Stale log contamination** — third consecutive scenario where hours-old logs from previous runs drove the entire diagnosis. Observation logs must be time-filtered to the current episode window.
4. **Jitter buffer resets not recognized** — the agent doesn't know that pjsua's "Resetting jitter buffer" is a symptom of packet loss on the media path.
