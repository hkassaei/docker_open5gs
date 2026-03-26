# Episode Report: HSS Unresponsive

**Agent:** v3  
**Episode ID:** ep_20260325_220835_hss_unresponsive  
**Date:** 2026-03-25T22:08:36.257142+00:00  
**Duration:** 118.7s  

---

## Scenario

**Category:** container  
**Blast radius:** single_nf  
**Description:** Pause PyHSS (freeze all processes). The HSS is still 'running' from Docker's perspective but cannot process Diameter requests. Tests how the I-CSCF and S-CSCF handle a hung Diameter peer.

## Faults Injected

- **container_pause** on `pyhss`

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
**smf:**
- `[32m03/25 11:48:07.066[0m: [[33msbi[0m] [1;32mINFO[0m: [b6805032-27b3-41f1-9a04-3f025a6967cf] Setup NF Instance [type:PCF] (../lib/sbi/path.c:30`

## Ground Truth

**Failure domain:** ims_signaling  
**Protocol impact:** Diameter  
**Affected components:** pyhss  
**Severity:** degraded

## Agent Diagnosis

**Model:** v3-adk/gemini-2.5-flash+gemini-2.5-pro  
**Time to diagnosis:** 109.5s

**Diagnosis:**

> Based on my analysis of the Triage report, trace data, and specialist findings, I have synthesized the following diagnosis.
> 
> ### Final Diagnosis
> 
> *   **summary**: The `pyhss` container is in a `paused` state, causing a complete failure of the Diameter Cx interface and blocking all IMS subscriber lookups.
> *   **timeline**:
>     *   `T0`: The `pyhss` container enters a `paused` state, freezing its process.
>     *   `T1`: The `icscf` container attempts to establish a Diameter connection with `pyhss` by sending a Capabilities-Exchange-Request (CER).
>     *   `T2`: Because it is paused, `pyhss` never responds with the required Capabilities-Exchange-Answer (CEA).
>     *   `T3`: The `icscf`'s Diameter peer status for the HSS (`hss.ims.mnc001.mcc001.3gppnetwork.org`) becomes stuck in the `Wait_I_CEA` state, indicating a failed connection.
>     *   `T4`: A UE sends an `INVITE` or `REGISTER` request, which is forwarded to the `icscf`.
> ...

### Scoring Breakdown

**Overall score: 100%**

**Scorer assessment:** The agent provided a perfectly accurate and detailed diagnosis, correctly identifying the paused HSS container as the root cause and its severe impact.

| Dimension | Result | Rationale |
|-----------|--------|-----------|
| Root cause correct | Yes | The agent correctly identified the 'pyhss' container being in a 'paused' state as the root cause, which directly matches the injected 'container_pause' fault on 'pyhss'. |
| Component overlap | 100% | The agent correctly identified 'pyhss' as an affected component, which was the sole target of the injected fault; listing 'icscf' as a downstream component is not penalized. |
| Severity correct | Yes | The agent accurately described the impact as a 'complete failure' and 'total breakdown of IMS services' due to the HSS being 'unresponsive' and 'frozen', which aligns with the 'HSS Unresponsive' and 'freeze all processes' nature of the fault. |
| Fault type identified | Yes | The agent clearly identified the fault type as a 'paused state' and described the container as 'frozen' and 'unresponsive', which perfectly matches the 'container_pause' fault. |
| Confidence calibrated | Yes | The agent stated 'high' confidence, which is appropriate given the diagnosis was entirely accurate and comprehensive across all dimensions. |

**Ranking position:** #1 — The agent provided only one root cause, which was correct, placing it as the top and only candidate.


### Token Usage

| Metric | Count |
|--------|-------|
| Input tokens | 57,374 |
| Output tokens | 3,435 |
| Thinking tokens | 23,105 |
| **Total tokens** | **83,914** |

**Per-phase breakdown:**

| Phase | Tokens | Tool Calls | LLM Calls |
|-------|--------|------------|-----------|
| TriageAgent | 7,647 | 2 | 2 |
| EndToEndTracer | 17,178 | 1 | 2 |
| DispatchAgent | 5,199 | 0 | 1 |
| TransportSpecialist | 22,380 | 3 | 4 |
| IMSSpecialist | 8,075 | 1 | 2 |
| CoreSpecialist | 7,544 | 1 | 2 |
| SubscriberDataSpecialist | 8,737 | 0 | 1 |
| SynthesisAgent | 7,154 | 0 | 1 |


## Resolution

**Heal method:** scheduled  
**Recovery time:** 118.7s
