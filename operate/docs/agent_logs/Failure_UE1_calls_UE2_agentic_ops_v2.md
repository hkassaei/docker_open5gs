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