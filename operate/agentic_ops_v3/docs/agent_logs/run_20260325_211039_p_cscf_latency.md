# Episode Report: P-CSCF Latency

**Agent:** v3  
**Episode ID:** ep_20260325_210824_p_cscf_latency  
**Date:** 2026-03-25T21:08:25.406722+00:00  
**Duration:** 134.0s  

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
- `[0;39;49m[0;36;49m 9(59) INFO: {1 41328 REGISTER 3XTNTwFj9xCIs1MxVzLCqD5YTsIhBm6t <null>} ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_resul`
- `[0;39;49m[0;36;49m10(60) INFO: {1 8613 REGISTER dP4b5Jfs.f7epCLv7ESWEs72uVAQ2b7D <null>} ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_result`
- `[0;39;49m[0;36;49m11(61) INFO: {1 5505 INVITE oQF7tapxwHWBjoT0USNjSpd7qFB4CLrf <null>} ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_result_c`
- `[0;39;49m[0;36;49m12(62) INFO: {1 41330 REGISTER 3XTNTwFj9xCIs1MxVzLCqD5YTsIhBm6t <null>} ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_resul`
- `[0;39;49m[0;36;49m13(63) INFO: {1 8615 REGISTER dP4b5Jfs.f7epCLv7ESWEs72uVAQ2b7D <null>} ims_icscf [cxdx_avp.c:140]: cxdx_get_avp(): cxdx_get_result`
**nr_gnb:**
- `[2026-03-25 11:48:07.657] [rls] [[36mdebug[m] UE[6] signal lost`
- `[2026-03-25 14:04:58.682] [rls] [[36mdebug[m] UE[8] signal lost`
- `[2026-03-25 15:06:29.945] [rls] [[36mdebug[m] UE[8] signal lost`
- `[2026-03-25 15:06:47.233] [rls] [[36mdebug[m] UE[7] signal lost`
- `[2026-03-25 15:06:47.233] [rls] [[36mdebug[m] UE[8] signal lost`
**smf:**
- `[32m03/25 11:48:07.066[0m: [[33msbi[0m] [1;32mINFO[0m: [b6805032-27b3-41f1-9a04-3f025a6967cf] Setup NF Instance [type:PCF] (../lib/sbi/path.c:30`

## Ground Truth

**Failure domain:** ims_signaling  
**Protocol impact:** SIP  
**Affected components:** pcscf  
**Severity:** degraded

## Agent Diagnosis

**Model:** v3-adk/gemini-2.5-flash+gemini-2.5-pro  
**Time to diagnosis:** 133.0s

**Summary:** An RCA (Root Cause Analysis) has been performed. The following causal chains have been identified, ranked by probability.

### Cause 1: Malformed Diameter Response from HSS
- **summary**: The HSS is sending malformed Diameter responses to the I-CSCF, specifically omitting the mandatory `Result-Code` AVP. The I-CSCF cannot process these responses, causing `REGISTER` and `INVITE` transactions to fail.
- **timeline**:
  - `[UE]` sends `SIP REGISTER` or `SIP INVITE`.
  - `[pcscf]` receives and forwa

**Root cause identified:** An RCA (Root Cause Analysis) has been performed. The following causal chains have been identified, ranked by probability.

### Cause 1: Malformed Diameter Response from HSS
- **summary**: The HSS is sending malformed Diameter responses to the I-CSCF, specifically omitting the mandatory `Result-Code` AVP. The I-CSCF cannot process these responses, causing `REGISTER` and `INVITE` transactions to fail.
- **timeline**:
  - `[UE]` sends `SIP REGISTER` or `SIP INVITE`.
  - `[pcscf]` receives and forwards the SIP message.
  - `[icscf]` receives the SIP message.
  - `[icscf]` sends a Diameter request (e.g., `UAR` or `LIR`) to the `hss` to get user or S-CSCF information.
  - `[hss]` processes the request and sends a Diameter answer (e.g., `UAA` or `LIA`) back to the `icscf`. **This response is missing the `Result-Code` AVP.**
  - `[icscf]` attempts to parse the Diameter answer, fails to find the `Result-Code`, and logs `cxdx_get_result_code: Failed finding avp`.
  - `[icscf]` aborts the procedure, leading to a failed registration or call.
- **root_cause**: A misconfiguration or software bug in the `hss` is causing it to generate and send non-compliant Diameter answer messages that lack the mandatory `Result-Code` AVP (Attribute-Value Pair). According to 3GPP standards, the I-CSCF requires this AVP to determine the outcome of its query to the HSS. Its absence is a hard failure.
- **affected_components**:
  - `hss` (Source of the malformed message)
  - `icscf` (Component that fails processing the message)
- **recommendation**: Investigate the `hss` configuration and logs. Ensure that the Diameter stack on the HSS is correctly configured to include the `Result-Code` AVP in all User-Authorization-Answer (`UAA`) and Location-Info-Answer (`LIA`) messages sent over the Cx interface.
- **confidence**: high
- **explanation**: The root cause is a data integrity failure in the IMS core signaling. The `icscf` logs clearly show it is trying to read the `Result-Code` from a Diameter message and failing. This error is not a timeout or a connectivity problem; it indicates the `icscf` received a response from the `hss`, but the response was missing a required field. This points directly to a misconfiguration or bug on the `hss`, which is sending syntactically invalid responses. The `icscf` correctly rejects this message, which in turn causes user registrations and call setups to fail.

### Cause 2: Extreme Network Latency on P-CSCF
- **summary**: The P-CSCF container has an artificial 500ms network delay configured, which severely slows down all initial IMS signaling and may be contributing to transaction timeouts that are being misinterpreted by the I-CSCF.
- **timeline**:
  - `[UE]` sends `SIP REGISTER` or `SIP INVITE`.
  - `[pcscf]` receives the SIP message. A `netem` rule on its interface adds ~500ms of latency before forwarding it.
  - `[icscf]` receives the delayed message and initiates its own downstream requests (e.g., to the HSS).
  - The initial 500ms delay consumes a large portion of the total transaction time budget.
  - A downstream transaction (e.g., I-CSCF to HSS) times out.
  - It is theorized that the `icscf` incorrectly logs this timeout condition with the misleading error `Failed finding avp`, when in fact no complete response was ever processed.
- **root_cause**: A `netem` traffic control rule has been applied to the `pcscf`'s network interface, artificially adding approximately 500ms of latency to every packet it handles. While not the direct cause of the specific AVP error message, this extreme latency severely degrades signaling performance and can cause various timeout-related race conditions.
- **affected_components**:
  - `pcscf` (Source of the delay)
  - `icscf` (Potential victim of timeouts)
- **recommendation**: Remove the traffic-shaping `netem` rules from the `pcscf` container's network interface to restore normal network latency.
- **confidence**: low
- **explanation**: We've confirmed that the `pcscf`, the entry point for IMS traffic, has an artificial 500ms delay. This is a severe performance bottleneck for time-sensitive SIP signaling. While the primary evidence points to a malformed message from the HSS (Cause 1), it is possible this latency is causing downstream timeouts that are being improperly logged by the I-CSCF. Regardless of whether it's the root cause of this specific error, this delay is a critical issue that will cause instability and must be fixed.

**Components identified:** icscf, pcscf

### Scoring Breakdown

**Overall score: 75%**

| Dimension | Result |
|-----------|--------|
| Root cause correct | Yes |
| Component overlap | 100% |
| Severity correct | No |
| Fault type identified | Yes |
| Confidence calibrated | No |

**Verdict:** The agent partially diagnosed this scenario — it identified some elements correctly but missed key aspects.

### Token Usage

| Metric | Count |
|--------|-------|
| Input tokens | 109,486 |
| Output tokens | 3,727 |
| Thinking tokens | 14,426 |
| **Total tokens** | **127,639** |

**Per-phase breakdown:**

| Phase | Tokens | Tool Calls | LLM Calls |
|-------|--------|------------|-----------|
| TriageAgent | 7,343 | 2 | 2 |
| EndToEndTracer | 40,731 | 4 | 5 |
| DispatchAgent | 4,202 | 0 | 1 |
| TransportSpecialist | 43,650 | 10 | 7 |
| IMSSpecialist | 24,058 | 4 | 5 |
| SynthesisAgent | 7,655 | 0 | 1 |


## Resolution

**Heal method:** scheduled  
**Recovery time:** 134.0s
