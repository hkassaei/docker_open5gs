# Agentic RCA

# Scenario
We brought up the entire stack and the two UEs a few minutes ago. From the logs, we see that both UEs have successfully registered with IMS. However, when we try making a call from UE1 to UE2, we see a failure and UE1 cannot call UE2 and disconnects after a few seconds. Investigate this issue and tell me what's going on.

## Attempt 1

## Troubleshooting Agent Logs
Starting investigation...
🔧 _tool_read_env_config({})
🔧 _tool_get_network_status({})
↳ _tool_read_env_config: { "network": { "mcc": "001", "mnc": "01", "ims_domain": "ims.mnc001.mcc001.3gppnetwork.org", "test_net...
↳ _tool_get_network_status: { "phase": "ready", "running": [ "mongo", "nrf", "scp", "ausf", "udr", "udm", "amf", ...
🔧 _tool_read_container_logs({'container': 'e2e_ue1', 'tail': 100})
↳ _tool_read_container_logs: To: sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org Contact: <sip:001011234567891@192.168.101.2:5060;ob> Call-...
🔧 _tool_search_logs({'containers': ['pcscf', 'icscf', 'scscf'], 'pattern': '6-0LW.nZAM-kpPhqNFgKTm6b...)
↳ _tool_search_logs: [pcscf] [0;39;49m[0;32;49m 3(56) NOTICE: {1 21075 INVITE 6-0LW.nZAM-kpPhqNFgKTm6bUr6fxueD DEFAULT_ROUTE} <script>: PCS...
🔧 _tool_read_container_logs({'grep': '6-0LW.nZAM-kpPhqNFgKTm6bUr6fxueD', 'container': 'icscf'})
🔧 _tool_read_container_logs({'container': 'pyhss', 'grep': 'LIR'})
↳ _tool_read_container_logs: [0;39;49m[0;31;49m 1(46) ERROR: {1 21075 INVITE 6-0LW.nZAM-kpPhqNFgKTm6bUr6fxueD initial_request} <script>: $ru => sip...
↳ _tool_read_container_logs: (no log output)
🔧 _tool_read_config({'component': 'icscf'})
↳ _tool_read_config: # SIP / UDP listen=udp:ICSCF_IP:4060 # SIP / TCP listen=tcp:ICSCF_IP:4060 # SIP / TCP/TLS #listen=tls:ICSCF_IP:4061 ali...
🔧 _tool_search_logs({'pattern': 'pyhss'})
↳ _tool_search_logs: [pyhss] [03/19/2026 14:23:38] [INFO] Product Name: PyHSS-client-API [pyhss] [03/19/2026 14:23:48] [INFO] Product Name: p...
🔧 final_result({'timeline': [{'event': 'UE1 sends SIP INVITE to UE2 (IMSI 001011234567892).', '...)

## Troubleshooting Agent Summary of the assessment
### Summary
Call from UE1 to UE2 fails because the I-CSCF cannot query the HSS to find the called subscriber (UE2).

### Timeline 
14:35:43.431 [e2e_ue1] UE1 sends SIP INVITE to UE2 (IMSI 001011234567892).
14:35:43.431 [pcscf] P-CSCF receives the INVITE and forwards it to the S-CSCF.
14:35:43.431 [scscf] S-CSCF (originating) receives the INVITE and forwards it to the I-CSCF to find the terminating user.
14:35:46.526 [icscf] I-CSCF fails to query the HSS (PyHSS) for UE2's location (S-CSCF). It generates and sends a 'SIP 500 Server error'.
14:35:46.526 [e2e_ue1] UE1 receives the '500 Server error on LIR select next S-CSCF' and terminates the call.
14:35:46.526 [pyhss] No Diameter LIR (Location-Information-Request) is ever received from the I-CSCF, confirming the I-CSCF never sent the query.

### Root Cause 
The I-CSCF is missing the required Diameter client configuration to connect to the PyHSS (HSS). Its configuration file lacks the address of the HSS, so it cannot send the Location-Information-Request (LIR) needed to route the call to the destination subscriber.

### Affected Components
icscf, pyhss, scscf

### Recommendation

Add the Diameter peer configuration to the I-CSCF so it can connect to the PyHSS. This typically involves adding a configuration block that defines the HSS hostname, realm, and port, and loading the Kamailio Diameter module (e.g., `cxdx_hss.cfg`).

### Detailed Explanation
The investigation followed the SIP call path from the calling UE (UE1) through the IMS core. The error message `500 Server error on LIR select next S-CSCF`, which was sent from the `icscf` container, was the critical clue. This error explicitly states that the I-CSCF failed during the Location-Information-Request (LIR) process, which is a Diameter query to the HSS. By cross-referencing logs, I confirmed the call reached the I-CSCF and then stopped. Crucially, the `pyhss` (HSS) logs showed no record of receiving an LIR request from the I-CSCF. This proves the fault lies within the I-CSCF

Confidence: High

Investigation complete · 200,108 tokens # Is this 200K token really correct give that the agent ran for about 2 minutes.

## Outcome

This was a very poor diagnosis of the situation. The details can be found in 'postmortem_ue1_calls_ue2_failure.md'. The agent scored 10 out of 100.

## Attempt 2

Based on the outcome and reflections from attempt 1, we made two major improvements:
1) updated the system prompt to tell the agent to check the end-to-end flow from UE-1 to UE-2 before diving deeper into individual NFs and jumping to conclusions.
2) we gave the agent two new tools to check the metrics of all the containers.

With that update, we reproduce the scenario and see how the agent scores.


## Troubleshooting Agent Logs
Starting investigation...
🔧 _tool_read_env_config({})
🔧 _tool_get_network_status({})
🔧 _tool_get_nf_metrics({})
↳ _tool_read_env_config: { "network": { "mcc": "001", "mnc": "01", "ims_domain": "ims.mnc001.mcc001.3gppnetwork.org", "test_net...
↳ _tool_get_network_status: { "phase": "ready", "running": [ "mongo", "nrf", "scp", "ausf", "udr", "udm", "amf", ...
↳ _tool_get_nf_metrics: AMF [2 UE] (via prometheus): amf_session = 4.0 gnb = 1.0 ran_ue = 2.0 ICSCF [4 req] (via kamcmd): cdp:average_...
🔧 _tool_read_container_logs({'container': 'e2e_ue1'})
🔧 _tool_read_container_logs({'container': 'e2e_ue2'})
↳ _tool_read_container_logs: CSeq: 28289 REGISTER Server: TelcoSuite Proxy-CSCF Content-Length: 0 --end msg-- 17:22:59.597 pjsu...
↳ _tool_read_container_logs: [2026-03-19 17:22:55.385] [nas] [[36mdebug[m] Registration accept received [2026-03-19 17:22:55.386] [nas] [[32minfo...
🔧 _tool_search_logs({'pattern': 'XHGdGdHf7OluqkF53j-QSALZM5Emcm68'})
↳ _tool_search_logs: [icscf] [0;39;49m[0;31;49m 1(46) ERROR: {1 31371 INVITE XHGdGdHf7OluqkF53j-QSALZM5Emcm68 initial_request} <script>: $r...
🔧 _tool_read_running_config({'grep': 'udp_mtu', 'container': 'pcscf'})
🔧 _tool_check_process_listeners({'container': 'e2e_ue2'})
↳ _tool_read_running_config: 133:udp_mtu = 1300 136:udp_mtu_try_proto = TCP
↳ _tool_check_process_listeners: Netid State Recv-Q Send-Q Local Address:Port Peer Address:PortProcess udp UNCONN 0 0 ...
🔧 final_result({'recommendation': "To fix this, you must modify the P-CSCF's configuration to p...)

## Troubleshooting Agent Summary of the assessment
### Summary
Call from UE1 to UE2 failed because the P-CSCF tried to send the INVITE message using TCP, but UE2 can only receive messages over UDP. This silent delivery failure caused the call to time out.

### Timeline 
17:25:35.419 [e2e_ue1] Call initiated. Sends INVITE with Call-ID XHGdGdHf7OluqkF53j-QSALZM5Emcm68.
17:25:35.425 [pcscf] Receives INVITE from UE1 and forwards to S-CSCF.
17:25:35.425 [scscf] Receives INVITE from P-CSCF (as originating S-CSCF) and forwards to I-CSCF.
17:25:35.428 [icscf] Receives INVITE, queries HSS to find UE2's S-CSCF, and forwards INVITE to S-CSCF.
17:25:35.430 [scscf] Receives INVITE from I-CSCF (as terminating S-CSCF), looks up UE2's location, and forwards INVITE to P-CSCF.
17:25:35.431 [pcscf] Receives INVITE for UE2. The message with SDP is >1300 bytes, triggering a switch to TCP.
17:25:35.431 [P-CSCF -> UE2 (Data Plane)] P-CSCF attempts to deliver INVITE via TCP to 192.168.101.5. UE2 is not listening on TCP, so the packet is dropped. **This is the point of failure.**
17:25:38.481 [scscf, icscf] The transaction from the S-CSCF to the P-CSCF times out. This timeout cascades backward, causing the I-CSCF to generate a 'SIP/2.0 500' error.
17:25:38.481 [e2e_ue1] Receives the 500 error and terminates the call.

### Root Cause
The P-CSCF container is configured with `udp_mtu_try_proto = TCP`. This causes Kamailio (the P-CSCF software) to re-transmit SIP messages larger than 1300 bytes (like an INVITE with SDP) over TCP. The UE client (pjsua), however, is only listening for SIP messages on UDP. The INVITE is therefore never delivered to the destination UE, leading to a transaction timeout in the IMS core.

### Affected Components
pcscf, e2e_ue1, e2e_ue2


### Recommendation
To fix this, you must modify the P-CSCF's configuration to prevent it from switching to TCP. The `udp_mtu_try_proto` parameter should be set to `UDP` instead of `TCP`. This will force Kamailio to fragment large SIP messages into multiple UDP packets, which the UE can correctly receive and reassemble. Change the setting in the `pcscf.cfg` file and restart the `pcscf` container.

### Detailed Explanation
The evidence is conclusive. We traced the SIP Call-ID from the caller to the final hop before the callee (the P-CSCF). We confirmed the callee never received the message. We then inspected the configuration of the P-CSCF and found the `udp_mtu_try_proto = TCP` setting, and verified with `check_process_listeners` that the destination UE was only listening on UDP. This combination of configuration and runtime state perfectly explains the observed silent delivery failure. The zero-packet count on the UPF was a supporting symptom of this delivery failure, not a separate data plane fault.

Confidence: High

Investigation complete · 159,386 tokens were consumed and took around 1.5 minutes.


## Score

There was dramatic improvement.

  ┌───────────────────────┬─────────────┬──────────────┬────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │       Dimension       │ Attempt 1   │  Attempt 2   │                                                                       Notes                                                                        │
  │                       │    (v1)     │    (v1.5)    │                                                                                                                                                    │
  ├───────────────────────┼─────────────┼──────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Root cause correct    │ 0           │ 1.0          │ Correctly identified udp_mtu_try_proto = TCP on P-CSCF                                                                                             │
  ├───────────────────────┼─────────────┼──────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Component overlap     │ 0           │ 0.67         │ Agent said {pcscf, e2e_ue1, e2e_ue2}. Actual: {pcscf}. pcscf is the root cause component, UEs are affected but not causal. Partial credit for      │
  │                       │             │              │ including pcscf.                                                                                                                                   │
  ├───────────────────────┼─────────────┼──────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Severity correct      │ 1.0         │ 1.0          │ Correctly identified as call failure                                                                                                               │
  ├───────────────────────┼─────────────┼──────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Fault type identified │ 0           │ 1.0          │ Identified transport mismatch, TCP vs UDP, udp_mtu_try_proto setting                                                                               │
  ├───────────────────────┼─────────────┼──────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Confidence calibrated │ 0           │ 1.0          │ High confidence AND correct — well calibrated                                                                                                      │
  ├───────────────────────┼─────────────┼──────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Investigation         │ 0           │ 0.9          │ Checked UE1, UE2, traced Call-ID across stack, checked running config, checked process listeners. Only gap: didn't explicitly confirm UE2 never    │
  │ thoroughness          │             │              │ saw the Call-ID (jumped from the cross-stack trace directly to the config check).                                                                  │
  ├───────────────────────┼─────────────┼──────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Total (weighted)      │ ~10%        │ ~90%         │                                                                                                                                                    │
  └───────────────────────┴─────────────┴──────────────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  What the agent did right this time

  1. Called get_nf_metrics in the first batch — metrics first, as instructed. The agent saw the full stack health before touching any logs.
  2. Checked BOTH UEs' logs — read_container_logs(e2e_ue1) AND read_container_logs(e2e_ue2) in parallel. This was the #1 lesson from the postmortem.
  3. Traced the Call-ID across the stack — search_logs(pattern='XHGdGdHf7OluqkF53j-QSALZM5Emcm68') found the INVITE in pcscf, scscf, icscf but NOT in e2e_ue2.
  4. Pivoted to the right question — instead of diving into I-CSCF Diameter (the v1 rabbit hole), it immediately checked read_running_config(pcscf, "udp_mtu") and check_process_listeners(e2e_ue2).
  5. Correctly explained the cascading error — the timeline shows the 500 at the I-CSCF as a symptom of the P-CSCF timeout, not the root cause. The agent wrote: "This timeout cascades backward, causing the
  I-CSCF to generate a '500' error."
  6. Used only 7 tool calls (vs 8 in attempt 1) and 159K tokens (vs 200K) — more efficient and more accurate.

  The one gap

  The agent didn't explicitly log "UE2 has no record of Call-ID XHGdGdHf7OluqkF53j" as a finding. It inferred this from the search_logs result (which only showed hits in pcscf/icscf/scscf, not e2e_ue2), but it
   would have been stronger to call that out explicitly in the timeline: "UE2 never received the INVITE."

  Score: 10% → 90%

  The two changes that made the difference:
  1. System prompt: "check both ends" + "metrics first" + "SIP INVITE not delivered" failure pattern
  2. New tools: read_running_config and check_process_listeners gave the agent the evidence it needed to close the diagnosis

  ┌───────────────────────┬─────────────┬──────────────┬────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │       Dimension       │ Attempt 1   │  Attempt 2   │                                                                       Notes                                                                        │
  │                       │    (v1)     │    (v1.5)    │                                                                                                                                                    │
  ├───────────────────────┼─────────────┼──────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Root cause correct    │ 0           │ 1.0          │ Correctly identified udp_mtu_try_proto = TCP on P-CSCF                                                                                             │
  ├───────────────────────┼─────────────┼──────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Component overlap     │ 0           │ 0.67         │ Agent said {pcscf, e2e_ue1, e2e_ue2}. Actual: {pcscf}. pcscf is the root cause component, UEs are affected but not causal. Partial credit for      │
  │                       │             │              │ including pcscf.                                                                                                                                   │
  ├───────────────────────┼─────────────┼──────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Severity correct      │ 1.0         │ 1.0          │ Correctly identified as call failure                                                                                                               │
  ├───────────────────────┼─────────────┼──────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Fault type identified │ 0           │ 1.0          │ Identified transport mismatch, TCP vs UDP, udp_mtu_try_proto setting                                                                               │
  ├───────────────────────┼─────────────┼──────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Confidence calibrated │ 0           │ 1.0          │ High confidence AND correct — well calibrated                                                                                                      │
  ├───────────────────────┼─────────────┼──────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Investigation         │ 0           │ 0.9          │ Checked UE1, UE2, traced Call-ID across stack, checked running config, checked process listeners. Only gap: didn't explicitly confirm UE2 never    │
  │ thoroughness          │             │              │ saw the Call-ID (jumped from the cross-stack trace directly to the config check).                                                                  │
  ├───────────────────────┼─────────────┼──────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Total (weighted)      │ ~10%        │ ~90%         │                                                                                                                                                    │
  └───────────────────────┴─────────────┴──────────────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  What the agent did right this time

  1. Called get_nf_metrics in the first batch — metrics first, as instructed. The agent saw the full stack health before touching any logs.
  2. Checked BOTH UEs' logs — read_container_logs(e2e_ue1) AND read_container_logs(e2e_ue2) in parallel. This was the #1 lesson from the postmortem.
  3. Traced the Call-ID across the stack — search_logs(pattern='XHGdGdHf7OluqkF53j-QSALZM5Emcm68') found the INVITE in pcscf, scscf, icscf but NOT in e2e_ue2.
  4. Pivoted to the right question — instead of diving into I-CSCF Diameter (the v1 rabbit hole), it immediately checked read_running_config(pcscf, "udp_mtu") and check_process_listeners(e2e_ue2).
  5. Correctly explained the cascading error — the timeline shows the 500 at the I-CSCF as a symptom of the P-CSCF timeout, not the root cause. The agent wrote: "This timeout cascades backward, causing the
  I-CSCF to generate a '500' error."
  6. Used only 7 tool calls (vs 8 in attempt 1) and 159K tokens (vs 200K) — more efficient and more accurate.

  The one gap

  The agent didn't explicitly log "UE2 has no record of Call-ID XHGdGdHf7OluqkF53j" as a finding. It inferred this from the search_logs result (which only showed hits in pcscf/icscf/scscf, not e2e_ue2), but it
   would have been stronger to call that out explicitly in the timeline: "UE2 never received the INVITE."

  Score: 10% → 90%

  The two changes that made the difference:
  1. System prompt: "check both ends" + "metrics first" + "SIP INVITE not delivered" failure pattern
  2. New tools: read_running_config and check_process_listeners gave the agent the evidence it needed to close the diagnosis

## Token Consumption

● In the 1st attempt, the agent consumed ~200K tokens while in the 2nd attempt it consumed ~150K tokens. The 50K token reduction is not accidental. There's a clear structural reason for it.

  Where the tokens go

  Each tool call has a cost: the LLM sends a request (with the full conversation history + tool results so far), gets back a response, then the tool result is appended to the conversation. The token cost grows
   quadratically with the number of rounds — each new round re-sends all previous tool results.

  Attempt 1: 8 tool calls, wrong path, 200K tokens

  Call 1: read_env_config         
  Call 2: get_network_status      
  Call 3: read_container_logs(ue1) 
  Call 4: search_logs(Call-ID)     
  Call 5: read_container_logs(icscf, grep=Call-ID) 
  Call 6: read_container_logs(pyhss, grep=LIR)
  Call 7: read_config(icscf)    
  Call 8: search_logs(pyhss)   
  Final: synthesize diagnosis     

  Total ≈ sum of all cumulative contexts ≈ 200K

  The agent read the entire I-CSCF config file (call 7, ~15K tokens) and did two speculative searches (calls 6, 8) looking for PyHSS Diameter activity that didn't exist. These were wasted rounds chasing the
  wrong hypothesis, and each round re-sent everything that came before.

  Attempt 2: 7 tool calls, right path, 159K tokens

  Call 1: read_env_config  
  Call 2: get_network_status  
  Call 3: get_nf_metrics         
  Call 4: read_container_logs(ue1)
  Call 5: read_container_logs(ue2) 
  Call 6: search_logs(Call-ID) 
  Call 7: read_running_config(pcscf, grep="udp_mtu") 
  Call 8: check_process_listeners(ue2) 
  Final: synthesize diagnosis

  Three things saved tokens:

  1. No wasted rounds. The agent didn't go down a rabbit hole. It checked both UEs (calls 4-5), traced the Call-ID (call 6), and went straight to the transport config (call 7). No speculative "let me read the
  entire I-CSCF config" or "let me search PyHSS logs for something that isn't there."
  2. Targeted tools return less data. read_running_config(pcscf, grep="udp_mtu") returned 2 lines (~20 tokens). Compare that to read_config(icscf) which returned the entire config file (~15K tokens). The grep
  parameter on read_running_config is a massive token saver — the agent asked a specific question and got a specific answer.
  3. Fewer rounds means less context re-sending. 7 effective calls vs 8, but more importantly, the conversation didn't accumulate a 15K config dump that gets re-sent on every subsequent round.

  The deeper reason: methodology drives efficiency

  The token reduction is a direct consequence of investigation discipline. When the agent follows the right methodology (check both ends → trace Call-ID → targeted config check), it converges on the root cause
   in fewer steps with smaller tool results. When it follows the wrong methodology (chase the most interesting error → read full configs → speculative searches), it burns tokens on irrelevant data that also
  pollutes the context for future reasoning.

  Better methodology → fewer rounds → smaller tool results → less context re-sending → fewer tokens.

  This is also the argument for the v2 multi-agent architecture: each specialist agent starts with a clean context containing only its tools and findings from previous phases. The Triage Agent's 5K metrics
  report is the only context the End-to-End Trace Agent inherits — not 50K of accumulated log dumps. Context hygiene is a token budget strategy, not just an architecture preference.