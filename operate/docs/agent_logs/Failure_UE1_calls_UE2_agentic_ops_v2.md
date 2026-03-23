## Agentic_ops_v2

# Scenario
We brought up the entire stack and the two UEs a few minutes ago. From the logs, we see that both UEs have successfully registered with IMS. However, when we try making a call from UE1 to UE2, we see a failure and UE1 cannot call UE2 and disconnects after a few seconds. Investigate this issue and tell me what's going on.


## Attempt 1

## Summary
 Diagnosis **summary:** The call failed because the P-CSCF attempted to send a large INVITE message over TCP to the terminating UE (UE2), but UE2 was only configured to listen for SIP traffic on UD

## Root Cause
## Diagnosis

**summary:** The call failed because the P-CSCF attempted to send a large INVITE message over TCP to the terminating UE (UE2), but UE2 was only configured to listen for SIP traffic on UDP.

**timeline:**
- **16:21:24.884 (e2e_ue1):** UE1 initiates a call by sending a SIP INVITE message with Call-ID `KbLunzrYAuevAPGJxDNJTDXOd.TI1kme`. The message size is 1676 bytes, which is large for a UDP packet.
- **16:21:24.885 (pcscf):** The originating P-CSCF receives the INVITE and forwards it towards the S-CSCF.
- **16:21:24.885 (scscf):** The originating S-CSCF receives the INVITE and routes it to the I-CSCF for terminating user lookup.
- **16:21:28.056 (icscf):** The I-CSCF processes the request. Although it sends a `500 Server error on LIR select next S-CSCF` error message back upstream, the trace shows it successfully routes the call to the terminating S-CSCF. This 500 error is misleading and not the root cause.
- **16:21:28.056 (scscf):** The terminating S-CSCF receives the INVITE, looks up the registered contact for UE2, and forwards the INVITE to the terminating P-CSCF.
- **16:21:28.056 (pcscf):** The terminating P-CSCF receives the INVITE. It notes the packet size (1676 bytes) is larger than its configured UDP MTU (1300 bytes). Due to its `udp_mtu_try_proto = TCP` setting, it attempts to forward the INVITE to UE2's address (`192.168.101.9:5060`) using the TCP protocol.
- **16:21:28.056 (e2e_ue2):** UE2 is only listening for SIP traffic on UDP port 5060. It has no active TCP listener on that port. The TCP packet from the P-CSCF is silently dropped. UE2 is never aware of the incoming call.
- **16:21:28.057 (e2e_ue1):** UE1 receives the `500 Server error` from the I-CSCF and terminates the call attempt.

**root_cause:**
The root cause is a transport protocol mismatch between the terminating P-CSCF and UE2. The P-CSCF is configured to switch from UDP to TCP for SIP messages exceeding 1300 bytes. The INVITE from UE1 was 1676 bytes, triggering this switch. However, the destination client, UE2, was not configured to listen for SIP on TCP, causing the TCP-based INVITE to be silently dropped and never delivered.

**affected_components:**
- `pcscf`
- `e2e_ue2`
- `e2e_ue1` (experiences the symptom)

**recommendation:**
To ensure reliable delivery of large SIP messages, the terminating client must support the same transport protocols as the P-CSCF.

**Action:** Configure the client application on `e2e_ue2` to listen for and accept SIP traffic on **both UDP and TCP** on its signaling port (5060).

**confidence:** high

**explanation:**
Hello NOC engineer,

We've diagnosed the call failure between UE1 and UE2. The root cause is a transport protocol mismatch during call setup, a "silent delivery failure".

Here's the chain of events:
1.  **Large SIP Message:** UE1 sent a call invitation (an INVITE message) that was over 1600 bytes. This is larger than a typical network packet size (MTU).
2.  **P-CSCF Switches Protocol:** The P-CSCF, which handles routing the call to the final user, is configured to handle such large messages by switching the transport from UDP to the more reliable TCP. It correctly attempted to send this large INVITE to UE2 using TCP.
3.  **Client Not Listening:** The problem is that the destination phone, UE2, was only listening for calls on UDP. It wasn't expecting a TCP connection. As a result, when the P-CSCF sent the call invite over TCP, UE2's network stack simply ignored it.
4.  **Call Fails:** Since UE2 never received the INVITE, it never rang, and the call ultimately failed.

You may have noticed a `500 Server error on LIR select next S-CSCF` from the I-CSCF in the logs. While this error is confusing, it was a red herring. The trace confirms that the call was successfully routed past the I-CSCF to the terminating side, meaning the I-CSCF did its job. The true failure happened at the very last step, between the P-CSCF and UE2, due to the TCP/UDP mismatch.

To fix this, the client application on **UE2 needs to be configured to accept both UDP and TCP** for SIP signaling. This will ensure it can receive both standard and large-sized SIP messages from the P-CSCF.

Detailed Explanation
## Diagnosis

**summary:** The call failed because the P-CSCF attempted to send a large INVITE message over TCP to the terminating UE (UE2), but UE2 was only configured to listen for SIP traffic on UDP.

**timeline:**
- **16:21:24.884 (e2e_ue1):** UE1 initiates a call by sending a SIP INVITE message with Call-ID `KbLunzrYAuevAPGJxDNJTDXOd.TI1kme`. The message size is 1676 bytes, which is large for a UDP packet.
- **16:21:24.885 (pcscf):** The originating P-CSCF receives the INVITE and forwards it towards the S-CSCF.
- **16:21:24.885 (scscf):** The originating S-CSCF receives the INVITE and routes it to the I-CSCF for terminating user lookup.
- **16:21:28.056 (icscf):** The I-CSCF processes the request. Although it sends a `500 Server error on LIR select next S-CSCF` error message back upstream, the trace shows it successfully routes the call to the terminating S-CSCF. This 500 error is misleading and not the root cause.
- **16:21:28.056 (scscf):** The terminating S-CSCF receives the INVITE, looks up the registered contact for UE2, and forwards the INVITE to the terminating P-CSCF.
- **16:21:28.056 (pcscf):** The terminating P-CSCF receives the INVITE. It notes the packet size (1676 bytes) is larger than its configured UDP MTU (1300 bytes). Due to its `udp_mtu_try_proto = TCP` setting, it attempts to forward the INVITE to UE2's address (`192.168.101.9:5060`) using the TCP protocol.
- **16:21:28.056 (e2e_ue2):** UE2 is only listening for SIP traffic on UDP port 5060. It has no active TCP listener on that port. The TCP packet from the P-CSCF is silently dropped. UE2 is never aware of the incoming call.
- **16:21:28.057 (e2e_ue1):** UE1 receives the `500 Server error` from the I-CSCF and terminates the call attempt.

**root_cause:**
The root cause is a transport protocol mismatch between the terminating P-CSCF and UE2. The P-CSCF is configured to switch from UDP to TCP for SIP messages exceeding 1300 bytes. The INVITE from UE1 was 1676 bytes, triggering this switch. However, the destination client, UE2, was not configured to listen for SIP on TCP, causing the TCP-based INVITE to be silently dropped and never delivered.

**affected_components:**
- `pcscf`
- `e2e_ue2`
- `e2e_ue1` (experiences the symptom)

**recommendation:**
To ensure reliable delivery of large SIP messages, the terminating client must support the same transport protocols as the P-CSCF.

**Action:** Configure the client application on `e2e_ue2` to listen for and accept SIP traffic on **both UDP and TCP** on its signaling port (5060).

**confidence:** high

**explanation:**
Hello NOC engineer,

We've diagnosed the call failure between UE1 and UE2. The root cause is a transport protocol mismatch during call setup, a "silent delivery failure".

Here's the chain of events:
1.  **Large SIP Message:** UE1 sent a call invitation (an INVITE message) that was over 1600 bytes. This is larger than a typical network packet size (MTU).
2.  **P-CSCF Switches Protocol:** The P-CSCF, which handles routing the call to the final user, is configured to handle such large messages by switching the transport from UDP to the more reliable TCP. It correctly attempted to send this large INVITE to UE2 using TCP.
3.  **Client Not Listening:** The problem is that the destination phone, UE2, was only listening for calls on UDP. It wasn't expecting a TCP connection. As a result, when the P-CSCF sent the call invite over TCP, UE2's network stack simply ignored it.
4.  **Call Fails:** Since UE2 never received the INVITE, it never rang, and the call ultimately failed.

You may have noticed a `500 Server error on LIR select next S-CSCF` from the I-CSCF in the logs. While this error is confusing, it was a red herring. The trace confirms that the call was successfully routed past the I-CSCF to the terminating side, meaning the I-CSCF did its job. The true failure happened at the very last step, between the P-CSCF and UE2, due to the TCP/UDP mismatch.

To fix this, the client application on **UE2 needs to be configured to accept both UDP and TCP** for SIP signaling. This will ensure it can receive both standard and large-sized SIP messages from the P-CSCF.

Confidence: medium

Investigation complete · 1,478,204 tokens

# Evaluation

● The diagnosis is correct this time. Let me score it:

  Scoring: v2 Agent — Attempt 2

  ┌───────────────────────────┬───────┬──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │         Dimension         │ Score │                                                                                Notes                                                                                 │
  ├───────────────────────────┼───────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Root cause correct        │ 1.0   │ Correctly identified udp_mtu_try_proto = TCP on P-CSCF causing TCP delivery to UDP-only UE2                                                                          │
  ├───────────────────────────┼───────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Component overlap         │ 0.67  │ Agent said {pcscf, e2e_ue2, e2e_ue1}. Actual: {pcscf}. pcscf correctly identified as root cause, UEs are affected parties.                                           │
  ├───────────────────────────┼───────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Severity correct          │ 1.0   │ Correctly identified as call failure                                                                                                                                 │
  ├───────────────────────────┼───────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Fault type identified     │ 1.0   │ "transport protocol mismatch", "udp_mtu_try_proto = TCP", "1676 bytes exceeding 1300 MTU" — nailed it                                                                │
  ├───────────────────────────┼───────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Confidence calibrated     │ 0.5   │ Final line says "medium" but the body says "high" — inconsistent. The evidence supports high.                                                                        │
  ├───────────────────────────┼───────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Investigation             │ 0.9   │ Extracted correct Call-ID, traced across containers, correctly identified the I-CSCF 500 as a "red herring" cascading error, found the transport config, checked UE2 │
  │ thoroughness              │       │  listeners                                                                                                                                                           │
  ├───────────────────────────┼───────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Explanation quality       │ 1.0   │ Excellent NOC-oriented explanation. Step-by-step causal chain. Explicitly called out the I-CSCF 500 as misleading. Actionable recommendation.                        │
  ├───────────────────────────┼───────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Total (weighted)          │ ~88%  │                                                                                                                                                                      │
  └───────────────────────────┴───────┴──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  The good

  1. Correct root cause — TCP/UDP transport mismatch, udp_mtu_try_proto = TCP, message size 1676 > 1300 MTU
  2. Correctly dismissed the I-CSCF 500 as a red herring — "This 500 error is misleading and not the root cause. The trace confirms that the call was successfully routed past the I-CSCF." This is exactly the
  lesson from the postmortem.
  3. Full causal chain in the timeline — from UE1 INVITE through every IMS node to the silent TCP drop at UE2
  4. Great NOC explanation — "Hello NOC engineer, here's the chain of events..." with 4 clear steps

  The concerns

  1. 1,478,204 tokens — that's 1.47 MILLION tokens, almost 10x worse than v1.5's 159K. The multi-agent overhead (5 sequential phases, each re-sending context through the ADK Runner) created massive token bloat
   instead of the projected 50K reduction.
  2. Recommendation is wrong-headed — it says "configure UE2 to listen on TCP" instead of "change udp_mtu_try_proto to UDP on the P-CSCF". Fixing the server config is the right answer, not changing every UE
  client. The v1.5 agent got this right.
  3. Confidence inconsistency — says "high" in the body but "medium" in the final line.

  Score comparison across all attempts

  ┌────────────────┬──────────────────────┬─────────────────────────┬──────────────────┐
  │                │ v1 (single, 6 tools) │ v1.5 (single, 11 tools) │ v2 (multi-agent) │
  ├────────────────┼──────────────────────┼─────────────────────────┼──────────────────┤
  │ Score          │ 10%                  │ 90%                     │ 88%              │
  ├────────────────┼──────────────────────┼─────────────────────────┼──────────────────┤
  │ Root cause     │ Wrong                │ Correct                 │ Correct          │
  ├────────────────┼──────────────────────┼─────────────────────────┼──────────────────┤
  │ Tokens         │ 200K                 │ 159K                    │ 1,478K           │
  ├────────────────┼──────────────────────┼─────────────────────────┼──────────────────┤
  │ Recommendation │ Wrong                │ Correct                 │ Wrong direction  │
  ├────────────────┼──────────────────────┼─────────────────────────┼──────────────────┤
  │ Time           │ ~2 min               │ ~1.5 min                │ Long             │
  └────────────────┴──────────────────────┴─────────────────────────┴──────────────────┘

  Verdict

  The v2 multi-agent system got the diagnosis right but at 10x the token cost of v1.5, and with a worse recommendation. The multi-agent architecture added overhead without adding accuracy on this specific
  failure. The v1.5 single agent with 11 tools and the improved system prompt actually performed better overall.

  The token explosion is the critical issue — it suggests the ADK SequentialAgent is re-sending the full conversation context through each phase, and the LlmAgent specialists are burning tokens on their own
  internal reasoning loops. This needs investigation: is the context being properly distilled between phases, or is raw data leaking through the session state?

# Evaluation

● The diagnosis is correct this time. Let me score it:

  Scoring: v2 Agent — Attempt 2

  ┌───────────────────────────┬───────┬──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │         Dimension         │ Score │                                                                                Notes                                                                                 │
  ├───────────────────────────┼───────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Root cause correct        │ 1.0   │ Correctly identified udp_mtu_try_proto = TCP on P-CSCF causing TCP delivery to UDP-only UE2                                                                          │
  ├───────────────────────────┼───────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Component overlap         │ 0.67  │ Agent said {pcscf, e2e_ue2, e2e_ue1}. Actual: {pcscf}. pcscf correctly identified as root cause, UEs are affected parties.                                           │
  ├───────────────────────────┼───────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Severity correct          │ 1.0   │ Correctly identified as call failure                                                                                                                                 │
  ├───────────────────────────┼───────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Fault type identified     │ 1.0   │ "transport protocol mismatch", "udp_mtu_try_proto = TCP", "1676 bytes exceeding 1300 MTU" — nailed it                                                                │
  ├───────────────────────────┼───────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Confidence calibrated     │ 0.5   │ Final line says "medium" but the body says "high" — inconsistent. The evidence supports high.                                                                        │
  ├───────────────────────────┼───────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Investigation             │ 0.9   │ Extracted correct Call-ID, traced across containers, correctly identified the I-CSCF 500 as a "red herring" cascading error, found the transport config, checked UE2 │
  │ thoroughness              │       │  listeners                                                                                                                                                           │
  ├───────────────────────────┼───────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Explanation quality       │ 1.0   │ Excellent NOC-oriented explanation. Step-by-step causal chain. Explicitly called out the I-CSCF 500 as misleading. Actionable recommendation.                        │
  ├───────────────────────────┼───────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Total (weighted)          │ ~88%  │                                                                                                                                                                      │
  └───────────────────────────┴───────┴──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  The good

  1. Correct root cause — TCP/UDP transport mismatch, udp_mtu_try_proto = TCP, message size 1676 > 1300 MTU
  2. Correctly dismissed the I-CSCF 500 as a red herring — "This 500 error is misleading and not the root cause. The trace confirms that the call was successfully routed past the I-CSCF." This is exactly the
  lesson from the postmortem.
  3. Full causal chain in the timeline — from UE1 INVITE through every IMS node to the silent TCP drop at UE2
  4. Great NOC explanation — "Hello NOC engineer, here's the chain of events..." with 4 clear steps

  The concerns

  1. 1,478,204 tokens — that's 1.47 MILLION tokens, almost 10x worse than v1.5's 159K. The multi-agent overhead (5 sequential phases, each re-sending context through the ADK Runner) created massive token bloat
   instead of the projected 50K reduction.
  2. Recommendation is wrong-headed — it says "configure UE2 to listen on TCP" instead of "change udp_mtu_try_proto to UDP on the P-CSCF". Fixing the server config is the right answer, not changing every UE
  client. The v1.5 agent got this right.
  3. Confidence inconsistency — says "high" in the body but "medium" in the final line.

  Score comparison across all attempts

  ┌────────────────┬──────────────────────┬─────────────────────────┬──────────────────┐
  │                │ v1 (single, 6 tools) │ v1.5 (single, 11 tools) │ v2 (multi-agent) │
  ├────────────────┼──────────────────────┼─────────────────────────┼──────────────────┤
  │ Score          │ 10%                  │ 90%                     │ 88%              │
  ├────────────────┼──────────────────────┼─────────────────────────┼──────────────────┤
  │ Root cause     │ Wrong                │ Correct                 │ Correct          │
  ├────────────────┼──────────────────────┼─────────────────────────┼──────────────────┤
  │ Tokens         │ 200K                 │ 159K                    │ 1,478K           │
  ├────────────────┼──────────────────────┼─────────────────────────┼──────────────────┤
  │ Recommendation │ Wrong                │ Correct                 │ Wrong direction  │
  ├────────────────┼──────────────────────┼─────────────────────────┼──────────────────┤
  │ Time           │ ~2 min               │ ~1.5 min                │ Long             │
  └────────────────┴──────────────────────┴─────────────────────────┴──────────────────┘

  Verdict

  The v2 multi-agent system got the diagnosis right but at 10x the token cost of v1.5, and with a worse recommendation. The multi-agent architecture added overhead without adding accuracy on this specific
  failure. The v1.5 single agent with 11 tools and the improved system prompt actually performed better overall.

  The token explosion is the critical issue — it suggests the ADK SequentialAgent is re-sending the full conversation context through each phase, and the LlmAgent specialists are burning tokens on their own
  internal reasoning loops. This needs investigation: is the context being properly distilled between phases, or is raw data leaking through the session state?



## Attempt 2

## Summary
Call failure is caused by a misconfiguration in the I-CSCF's call-forwarding-failure logic, where a retry attempt incorrectly requests capabilities from an HSS that doesn't support it.

## Root Cause
## Diagnosis

**summary:**
Call failure is caused by a misconfiguration in the I-CSCF's call-forwarding-failure logic, where a retry attempt incorrectly requests capabilities from an HSS that doesn't support it.

**timeline:**
- `12:19:50.137` [e2e_ue1] sends SIP INVITE to `pcscf` to initiate a call to UE2.
- `12:19:50.139` [pcscf] receives the INVITE and forwards it to the originating `scscf`.
- `~12:19:50.140` [scscf] receives the INVITE and forwards it to the `icscf` to locate the terminating user (UE2).
- `~12:19:50.141` [icscf] sends a Location-Information-Request (LIR) to `pyhss` to get UE2's assigned S-CSCF. `pyhss` responds with the correct S-CSCF address.
- `~12:19:50.142` [icscf] attempts to forward (relay) the INVITE to the terminating S-CSCF. This relay attempt fails due to a timeout.
- `~12:19:53.255` [icscf] The timeout triggers a failure-handling route. This route attempts to find an alternative S-CSCF by sending a *new* LIR to `pyhss`, but this time it incorrectly requests S-CSCF "capabilities".
- `~12:19:53.255` [pyhss] receives the new LIR but cannot process the capabilities request, returning a response the `icscf` cannot use.
- `12:19:53.256` [icscf] The S-CSCF selection fails. It sends a `SIP/2.0 500 Server error on LIR select next S-CSCF` response back to the originating `scscf`.
- `12:19:53.256` [e2e_ue1] receives the propagated `500 Server error` and terminates the call attempt.
- `12:19:53.257` [e2e_ue1] sends an ACK for the 500 error, ending the session.

**root_cause:**
The root cause is a software bug in the I-CSCF's Kamailio configuration script (`icscf.cfg`).
1.  When the I-CSCF receives the INVITE, it successfully queries the HSS to find the correct terminating S-CSCF.
2.  Its first attempt to forward the INVITE to that S-CSCF times out.
3.  This timeout triggers a failover logic path (`failure_route[initial_request_failure]`).
4.  This failover logic is misconfigured. It attempts to find a *new* S-CSCF by sending a second query to the HSS, but this time it requests S-CSCF capabilities (`I_scscf_select("1")`).
5.  The HSS (`pyhss`) in this environment is not configured to handle capability requests. It returns an answer the I-CSCF cannot parse, causing the S-CSCF selection to fail.
6.  This failure triggers the specific error message `Server error on LIR select next S-CSCF`, which is sent back to the user, terminating the call.

The initial timeout is a symptom, but the configuration bug in the failover logic is the deterministic root cause of the final error.

*Note on conflicting findings:* The Core Specialist incorrectly concluded the HSS data was malformed, misinterpreting the `scscf_peer` field. The actual SIP routing address (`scscf`) was correct in the HSS, as confirmed by the Subscriber Data and IMS specialists. The Transport Specialist found a valid, but latent, issue where the P-CSCF would attempt to use TCP to contact UE2, which only listens on UDP. This issue was never triggered because the call failed earlier at the I-CSCF.

**affected_components:**
- `icscf` (Root cause of failure)
- `pyhss` (Behavior exposed the bug in icscf)
- `scscf` (Propagated the failure)
- `pcscf` (Propagated the failure)
- `e2e_ue1` (Experienced the failure)

**recommendation:**
1.  **Primary Fix:** Correct the I-CSCF configuration to ensure failover logic is consistent with the initial logic.
    - Edit the I-CSCF's Kamailio configuration file (`icscf.cfg`).
    - Locate the `failure_route[initial_request_failure]` block.
    - Change the line `if (I_scscf_select("1"))` to `if (I_scscf_select("0"))`.
    - This change ensures that on a retry, the I-CSCF queries the HSS without requesting capabilities, matching the initial query's behavior and avoiding the incompatibility with the HSS.

2.  **Secondary (Latent Bug) Fix:** Correct the transport protocol mismatch to prevent future failures.
    - On the `pcscf` container, change the `udp_mtu_try_proto` parameter from `TCP` to `UDP`. This will prevent it from trying to switch to TCP for large messages sent to the UEs.
    - *Alternatively*, reconfigure `e2e_ue2`'s pjsua client to listen for SIP on both UDP and TCP.

**confidence:**
high

**explanation:**
Hi NOC team,

The call from UE1 to UE2 is failing because of a configuration bug in the I-CSCF, which acts as a traffic director in the IMS core.

Here's the sequence of events:
1.  The call (an INVITE request) correctly travels from UE1, through the P-CSCF, to the originating S-CSCF, and finally to the I-CSCF. The I-CSCF's job here is to ask the HSS (the user database) where to find the called party, UE2.
2.  The I-CSCF correctly queries the HSS and gets back the right address for UE2's serving node (the terminating S-CSCF).
3.  The I-CSCF's first attempt to forward the call to this S-CSCF timed out. This is likely due to a transient network issue.
4.  Normally, the I-CSCF has failover logic to handle such a timeout. However, this is where the bug is. The failover logic tries to query the HSS *again*, but this time it asks for special "capabilities" of the S-CSCF.
5.  Our HSS isn't set up to understand this "capabilities" request. It sends back a response that the I-CSCF's failover logic can't use.
6.  As a result, the failover fails, and the I-CSCF gives up, sending a `500 Server error on LIR select next S-CSCF` back to UE1, which terminates the call.

**Action to Take:**
The immediate fix is to correct the I-CSCF's configuration. The failover logic needs to be changed so that its retry query to the HSS is identical to its first query (i.e., it should not ask for capabilities). The specific change is in the `icscf.cfg` file, modifying `I_scscf_select("1")` to `I_scscf_select("0")` in the `initial_request_failure` route.

Additionally, our specialists found a second, unrelated issue: the P-CSCF is configured to switch to TCP for large messages, but the UEs are only listening on UDP. This would have caused the call to fail later anyway. We should also correct the P-CSCF configuration to prevent it from switching to TCP.


**explanation:**
Hello NOC engineer,

We've diagnosed the call failure between UE1 and UE2. The root cause is a transport protocol mismatch during call setup, a "silent delivery failure".

Here's the chain of events:
1.  **Large SIP Message:** UE1 sent a call invitation (an INVITE message) that was over 1600 bytes. This is larger than a typical network packet size (MTU).
2.  **P-CSCF Switches Protocol:** The P-CSCF, which handles routing the call to the final user, is configured to handle such large messages by switching the transport from UDP to the more reliable TCP. It correctly attempted to send this large INVITE to UE2 using TCP.
3.  **Client Not Listening:** The problem is that the destination phone, UE2, was only listening for calls on UDP. It wasn't expecting a TCP connection. As a result, when the P-CSCF sent the call invite over TCP, UE2's network stack simply ignored it.
4.  **Call Fails:** Since UE2 never received the INVITE, it never rang, and the call ultimately failed.

You may have noticed a `500 Server error on LIR select next S-CSCF` from the I-CSCF in the logs. While this error is confusing, it was a red herring. The trace confirms that the call was successfully routed past the I-CSCF to the terminating side, meaning the I-CSCF did its job. The true failure happened at the very last step, between the P-CSCF and UE2, due to the TCP/UDP mismatch.

To fix this, the client application on **UE2 needs to be configured to accept both UDP and TCP** for SIP signaling. This will ensure it can receive both standard and large-sized SIP messages from the P-CSCF.

## Detailed Explanation

## Diagnosis

**summary:**
Call failure is caused by a misconfiguration in the I-CSCF's call-forwarding-failure logic, where a retry attempt incorrectly requests capabilities from an HSS that doesn't support it.

**timeline:**
- `12:19:50.137` [e2e_ue1] sends SIP INVITE to `pcscf` to initiate a call to UE2.
- `12:19:50.139` [pcscf] receives the INVITE and forwards it to the originating `scscf`.
- `~12:19:50.140` [scscf] receives the INVITE and forwards it to the `icscf` to locate the terminating user (UE2).
- `~12:19:50.141` [icscf] sends a Location-Information-Request (LIR) to `pyhss` to get UE2's assigned S-CSCF. `pyhss` responds with the correct S-CSCF address.
- `~12:19:50.142` [icscf] attempts to forward (relay) the INVITE to the terminating S-CSCF. This relay attempt fails due to a timeout.
- `~12:19:53.255` [icscf] The timeout triggers a failure-handling route. This route attempts to find an alternative S-CSCF by sending a *new* LIR to `pyhss`, but this time it incorrectly requests S-CSCF "capabilities".
- `~12:19:53.255` [pyhss] receives the new LIR but cannot process the capabilities request, returning a response the `icscf` cannot use.
- `12:19:53.256` [icscf] The S-CSCF selection fails. It sends a `SIP/2.0 500 Server error on LIR select next S-CSCF` response back to the originating `scscf`.
- `12:19:53.256` [e2e_ue1] receives the propagated `500 Server error` and terminates the call attempt.
- `12:19:53.257` [e2e_ue1] sends an ACK for the 500 error, ending the session.

**root_cause:**
The root cause is a software bug in the I-CSCF's Kamailio configuration script (`icscf.cfg`).
1.  When the I-CSCF receives the INVITE, it successfully queries the HSS to find the correct terminating S-CSCF.
2.  Its first attempt to forward the INVITE to that S-CSCF times out.
3.  This timeout triggers a failover logic path (`failure_route[initial_request_failure]`).
4.  This failover logic is misconfigured. It attempts to find a *new* S-CSCF by sending a second query to the HSS, but this time it requests S-CSCF capabilities (`I_scscf_select("1")`).
5.  The HSS (`pyhss`) in this environment is not configured to handle capability requests. It returns an answer the I-CSCF cannot parse, causing the S-CSCF selection to fail.
6.  This failure triggers the specific error message `Server error on LIR select next S-CSCF`, which is sent back to the user, terminating the call.

The initial timeout is a symptom, but the configuration bug in the failover logic is the deterministic root cause of the final error.

*Note on conflicting findings:* The Core Specialist incorrectly concluded the HSS data was malformed, misinterpreting the `scscf_peer` field. The actual SIP routing address (`scscf`) was correct in the HSS, as confirmed by the Subscriber Data and IMS specialists. The Transport Specialist found a valid, but latent, issue where the P-CSCF would attempt to use TCP to contact UE2, which only listens on UDP. This issue was never triggered because the call failed earlier at the I-CSCF.

**affected_components:**
- `icscf` (Root cause of failure)
- `pyhss` (Behavior exposed the bug in icscf)
- `scscf` (Propagated the failure)
- `pcscf` (Propagated the failure)
- `e2e_ue1` (Experienced the failure)

**recommendation:**
1.  **Primary Fix:** Correct the I-CSCF configuration to ensure failover logic is consistent with the initial logic.
    - Edit the I-CSCF's Kamailio configuration file (`icscf.cfg`).
    - Locate the `failure_route[initial_request_failure]` block.
    - Change the line `if (I_scscf_select("1"))` to `if (I_scscf_select("0"))`.
    - This change ensures that on a retry, the I-CSCF queries the HSS without requesting capabilities, matching the initial query's behavior and avoiding the incompatibility with the HSS.

2.  **Secondary (Latent Bug) Fix:** Correct the transport protocol mismatch to prevent future failures.
    - On the `pcscf` container, change the `udp_mtu_try_proto` parameter from `TCP` to `UDP`. This will prevent it from trying to switch to TCP for large messages sent to the UEs.
    - *Alternatively*, reconfigure `e2e_ue2`'s pjsua client to listen for SIP on both UDP and TCP.

**confidence:**
high

**explanation:**
Hi NOC team,

The call from UE1 to UE2 is failing because of a configuration bug in the I-CSCF, which acts as a traffic director in the IMS core.

Here's the sequence of events:
1.  The call (an INVITE request) correctly travels from UE1, through the P-CSCF, to the originating S-CSCF, and finally to the I-CSCF. The I-CSCF's job here is to ask the HSS (the user database) where to find the called party, UE2.
2.  The I-CSCF correctly queries the HSS and gets back the right address for UE2's serving node (the terminating S-CSCF).
3.  The I-CSCF's first attempt to forward the call to this S-CSCF timed out. This is likely due to a transient network issue.
4.  Normally, the I-CSCF has failover logic to handle such a timeout. However, this is where the bug is. The failover logic tries to query the HSS *again*, but this time it asks for special "capabilities" of the S-CSCF.
5.  Our HSS isn't set up to understand this "capabilities" request. It sends back a response that the I-CSCF's failover logic can't use.
6.  As a result, the failover fails, and the I-CSCF gives up, sending a `500 Server error on LIR select next S-CSCF` back to UE1, which terminates the call.

**Action to Take:**
The immediate fix is to correct the I-CSCF's configuration. The failover logic needs to be changed so that its retry query to the HSS is identical to its first query (i.e., it should not ask for capabilities). The specific change is in the `icscf.cfg` file, modifying `I_scscf_select("1")` to `I_scscf_select("0")` in the `initial_request_failure` route.

Additionally, our specialists found a second, unrelated issue: the P-CSCF is configured to switch to TCP for large messages, but the UEs are only listening on UDP. This would have caused the call to fail later anyway. We should also correct the P-CSCF configuration to prevent it from switching to TCP.


Confidence: medium

Investigation complete · 1,359,366 tokens