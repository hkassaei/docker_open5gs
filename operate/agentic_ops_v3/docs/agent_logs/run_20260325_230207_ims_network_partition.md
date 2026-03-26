# Episode Report: IMS Network Partition

**Agent:** v3  
**Episode ID:** ep_20260325_225953_ims_network_partition  
**Date:** 2026-03-25T22:59:53.754533+00:00  
**Duration:** 132.5s  

---

## Scenario

**Category:** network  
**Blast radius:** multi_nf  
**Description:** Partition the P-CSCF from both the I-CSCF and S-CSCF using iptables DROP rules. SIP signaling between the edge proxy and the core IMS is completely severed. Tests IMS behavior under a network split.

## Faults Injected

- **network_partition** on `pcscf` — {'target_ip': '172.22.0.19'}
- **network_partition** on `pcscf` — {'target_ip': '172.22.0.20'}

## Baseline (Pre-Fault)

Stack phase before injection: **ready**
All containers running at baseline.

## Symptoms Observed

Symptoms detected: **Yes**  
Observation iterations: 1

### Metrics Changes

| Node | Metric | Baseline | Current | Delta |
|------|--------|----------|---------|-------|
| pcscf | core:rcv_requests_options | 10045.0 | 10046.0 | 1.0 |
| pcscf | httpclient:connfail | 10050.0 | 10051.0 | 1.0 |
| upf | fivegs_ep_n3_gtp_indatapktn3upf | 13324.0 | 13325.0 | 1.0 |

### Notable Log Lines

**amf:**
- `[32m03/25 18:58:01.869[0m: [[33msbi[0m] [1;32mINFO[0m: [b6805032-27b3-41f1-9a04-3f025a6967cf] (NRF-profile-get) NF registered (../lib/sbi/nf-sm.`
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

**Failure domain:** ims_signaling  
**Protocol impact:** SIP  
**Affected components:** pcscf  
**Severity:** degraded

## Agent Diagnosis

**Model:** v3-adk/gemini-2.5-flash+gemini-2.5-pro  
**Time to diagnosis:** 120.0s

**Diagnosis:**

> Based on my analysis of the specialist reports and raw evidence, I have identified two distinct, concurrent root causes for this outage. They are presented in order of severity, with the most fundamental failure listed first.
> 
> ### Cause #1: 5G Core Control Plane Failure
> 
> *   **summary**: The Access and Mobility Management Function (AMF) is completely disconnected from the Radio Access Network (gNB) due to a critical N2 interface configuration error. This prevents any User Equipment (UE) from attaching to the 5G network, representing a total control plane outage.
> *   **timeline**:
>     1.  `AMF` starts with a misconfigured IP address for its N2/NGAP interface.
>     2.  `AMF` fails to create a listening SCTP socket on the expected address for the gNB.
>     3.  `nr_gnb` attempts to establish an NGAP association with the AMF at its configured (but non-listening) address.
>     4.  The connection fails, leading to the gNB logging `[ngap] [error] Association terminated for AMF[2]`.
>     5.  As a result, no UEs can complete the attachment procedure with the core network.
>     6.  This is confirmed by the metric `AMF: ran_ue` dropping to and remaining at `0.0`.
> *   **root_cause**: The `ngap.sctp.addr` parameter in the AMF configuration file is incorrect. This prevented the AMF from binding to the proper network interface and listening for SCTP connections from the gNB, severing the essential N2 control plane link between the RAN and the 5G Core.
> *   **affected_components**: `amf`, `nr_gnb`
> *   **recommendation**: On the `amf` server, correct the `ngap.sctp.addr` parameter in its configuration file to match the IP address of the network interface intended for N2 communication. Restart the AMF process to apply the change.
> *   **confidence**: high
> *   **explanation**: The core of the problem is a fundamental disconnect between the radio network (gNB) and the 5G core brain (AMF). The AMF was configured with the wrong address for its N2 interface, which is like giving someone the wrong phone number. The gNB tried to call the AMF to register new users, but the AMF wasn't listening at that "number." This resulted in a terminated association, causing a complete failure for any UE trying to join the network.
> 
> ### Cause #2: IMS Signaling Failure
> 
> *   **summary**: The Interrogating-CSCF (I-CSCF) cannot properly communicate with the Home Subscriber Server (HSS) over the Diameter protocol. This prevents the I-CSCF from discovering the correct Serving-CSCF (S-CSCF) for users, causing nearly all IMS registration attempts to fail.
> *   **timeline**:
>     1.  The Diameter protocol connection between `icscf` and `hss` enters a stuck `I_Open` state, indicating an incomplete handshake.
>     2.  A UE (likely one with a stale, pre-outage connection) sends a `REGISTER` request, which successfully traverses the `pcscf` to the `icscf`.
>     3.  `icscf` receives the `REGISTER` and must query the `hss` to authorize the user and find their assigned S-CSCF.
>     4.  `icscf` sends a User-Authorization-Request (UAR) over the faulty Diameter connection.
>     5.  The transaction fails due to the half-open connection state. The I-CSCF does not receive a valid User-Authorization-Answer (UAA).
>     6.  The `icscf` logs `cxdx_get_result_code: Failed finding avp` because the expected data from the HSS is missing.
>     7.  Unable to determine the next hop, the `icscf` drops the `REGISTER` request, preventing it from ever reaching the `scscf`.
> *   **root_cause**: The Diameter connection between the I-CSCF and the HSS is in a non-functional `I_Open` state. This indicates the I-CSCF initiated a connection, but the full two-way handshake required for message exchange never completed successfully. All subsequent Diameter queries (UAR/LIR) from the I-CSCF to the HSS fail, making it impossible to resolve S-CSCF addresses for incoming registrations.
> *   **affected_components**: `icscf`, `hss`, `scscf`
> *   **recommendation**: Reset the Diameter peer connection on the `icscf` for the `hss.ims.mnc001.mcc001.3gppnetwork.org` peer. This will tear down the stuck `I_Open` session and force a new handshake, which should establish a healthy `R_Open` state.
> *   **confidence**: high
> *   **explanation**: A secondary, independent failure occurred within the IMS system. Think of the I-CSCF as a receptionist and the HSS as the employee directory. When a user tried to register, the I-CSCF needed to look up the user in the HSS directory to find out where to send them (to the S-CSCF). However, the phone line between the I-CSCF and HSS was faulty—it could dial out but couldn't receive a proper response. Because the lookup failed, the I-CSCF had no choice but to hang up, causing the user's registration to fail. This explains why very few registration requests made it to the S-CSCF.

### Scoring Breakdown

**Overall score: 15%**

**Scorer assessment:** The agent completely missed the injected network partition, diagnosing two unrelated issues with high confidence, though it correctly assessed the severity of the observed symptoms as an outage.

| Dimension | Result | Rationale |
|-----------|--------|-----------|
| Root cause correct | No | The agent did not identify the injected network partition on the P-CSCF as the root cause; instead, it diagnosed two entirely different issues (AMF configuration error and I-CSCF-HSS Diameter connection issue). |
| Component overlap | 0% | The agent did not identify the 'pcscf' container, which was the target of the injected fault, in its diagnosis. |
| Severity correct | Yes | The agent correctly assessed the impact as a severe outage ('total control plane outage', 'nearly all IMS registration attempts to fail'), which aligns with the 'SIP signaling severed' and 'New REGISTER and INVITE fail' described in the ground truth for a network partition. |
| Fault type identified | No | The agent identified configuration and protocol state issues, not a network partition or an equivalent class of failure. |
| Confidence calibrated | No | The agent expressed high confidence in a diagnosis that was entirely incorrect regarding the root cause, affected components, and fault type. |

**Ranking:** The correct cause was not identified or ranked by the agent.


### Token Usage

| Metric | Count |
|--------|-------|
| Input tokens | 112,561 |
| Output tokens | 4,826 |
| Thinking tokens | 18,716 |
| **Total tokens** | **136,103** |

**Per-phase breakdown:**

| Phase | Tokens | Tool Calls | LLM Calls |
|-------|--------|------------|-----------|
| TriageAgent | 8,562 | 2 | 2 |
| EndToEndTracer | 42,058 | 3 | 4 |
| DispatchAgent | 5,086 | 0 | 1 |
| TransportSpecialist | 48,745 | 13 | 6 |
| CoreSpecialist | 15,969 | 3 | 4 |
| IMSSpecialist | 8,704 | 1 | 2 |
| SynthesisAgent | 6,979 | 0 | 1 |


## Resolution

**Heal method:** scheduled
**Recovery time:** 132.5s

---

## Post-Run Analysis

### Why the agent failed

#### 1. Right container, wrong tool

The TransportSpecialist **did check pcscf** this time — `check_tc_rules("pcscf")` was its second call. But this fault is an **iptables partition** (`network_partition`), not a tc rule. `check_tc_rules` runs `tc qdisc show` which only detects netem/tbf rules — it doesn't inspect iptables. It correctly returned "no faults detected" because there are no tc rules, but it missed the iptables DROP rules blocking all traffic from pcscf to icscf and scscf.

#### 2. No iptables inspection tool

The agent has no way to see iptables rules. A `check_iptables_rules(container)` tool running `iptables -L -n` in the container's network namespace would have immediately revealed the DROP rules on pcscf.

#### 3. RTT measured in the wrong direction

The TransportSpecialist measured RTT from `icscf → scscf` (healthy — they can reach each other). But the partition is `pcscf → icscf` and `pcscf → scscf`. It never tested connectivity **from** pcscf to anything. A `measure_rtt("pcscf", "172.22.0.19")` call would have shown 100% packet loss — instant smoking gun. Same pattern as the latency scenario: the agent tests connectivity between containers with errors rather than from the container on the fault path.

Full TransportSpecialist tool calls:
```
check_tc_rules("amf")             ← irrelevant
check_tc_rules("pcscf")           ← correct container, wrong tool (tc not iptables)
check_tc_rules("icscf")           ← clean
check_tc_rules("scscf")           ← clean
check_process_listeners("icscf")
check_process_listeners("scscf")
cdp.list_peers on icscf
measure_rtt(icscf → scscf)        ← wrong direction, should be pcscf → icscf
check_tc_rules("icscf")           ← duplicate
check_tc_rules("scscf")           ← duplicate
check_process_listeners("icscf")  ← duplicate
check_process_listeners("scscf")  ← duplicate
measure_rtt(icscf → scscf)        ← duplicate
```

13 tool calls, 5 duplicates, and never tested the actual partition path.

#### 4. Stale log contamination

Cause #1 ("AMF N2 interface configuration error") was built on a stale log: `Association terminated for AMF[2]` from timestamp `18:29:24`, but the episode started at `22:59:53` — that error is from 4.5 hours ago, likely from the previous AMF Restart scenario. The agent doesn't filter logs by time.

#### 5. I_Open annotation partially worked

The TransportSpecialist correctly treated I_Open as non-critical ("active connection attempts"). But the SynthesisAgent still built Cause #2 entirely around I_Open as "a non-functional state" and "incomplete handshake." The annotation prevented the TransportSpecialist from fixating on it, but didn't prevent the IMSSpecialist and SynthesisAgent from re-interpreting it as a root cause.

### Gaps exposed

1. **Missing tool: iptables inspection.** Need `check_iptables_rules(container)` to detect DROP/REJECT rules — the iptables equivalent of `check_tc_rules` for tc.
2. **RTT direction.** The TransportSpecialist should test connectivity **from** the suspected container outward, not between other containers. The partition is only visible when testing from the partitioned node.
3. **Stale log filtering.** Observation logs passed to the agent should be time-filtered to the current episode window, not the entire container lifetime.
