# Postmortem: UE1 → UE2 Voice Call Failure

**Date:** 2026-03-19
**Severity:** Complete call failure (registration works, calls do not)
**Duration:** ~45 minutes from detection to permanent fix
**Impact:** All voice calls between UEs fail. SIP registration and 5G data plane unaffected.

---

## Symptom

Both UEs (UE1 and UE2) successfully registered with IMS via SIP REGISTER. However, when UE1 attempts to call UE2, the call fails within a few seconds. UE1 receives a `500 Server error on LIR select next S-CSCF` and disconnects.

---

## What the Troubleshooting Agent Found (Incorrect)

The Pydantic AI troubleshooting agent (Gemini 2.5 Pro) was invoked via the GUI's Investigate button. It performed 8 tool calls across 6 containers and produced this diagnosis:

> **Agent's Root Cause:** "The I-CSCF is missing the required Diameter client configuration to connect to the PyHSS (HSS). Its configuration file lacks the address of the HSS, so it cannot send the Location-Information-Request (LIR) needed to route the call to the destination subscriber."

> **Agent's Recommendation:** "Add the Diameter peer configuration to the I-CSCF so it can connect to the PyHSS."

> **Agent's Confidence:** High

**This was wrong.** The agent correctly identified the I-CSCF as the source of the 500 error and correctly traced the SIP call path, but it attributed the failure to a missing Diameter peer configuration. In reality, the I-CSCF's Diameter connection to PyHSS was fully operational (`State: I_Open`, all Cx applications registered).

### Why the Agent Got It Wrong

1. The agent checked the I-CSCF config file and didn't find explicit Diameter peer configuration inline — but the Diameter config is in a separate XML file (`icscf.xml`), not in `kamailio_icscf.cfg`. The agent didn't know to look there.
2. The agent checked PyHSS logs for LIR activity and found nothing — but PyHSS doesn't log individual Diameter messages at INFO level. The absence of logs was mistaken for absence of activity.
3. The agent stopped investigating after forming its hypothesis. It never verified the hypothesis by checking `kamcmd cdp.list_peers` (which would have shown the Diameter connection was healthy).

**Key lesson:** The agent exhibited the same "confirmation bias" pattern documented in `rca_reflections.md` — it found a plausible explanation early (missing config) and didn't seek disconfirming evidence.

---

## What the Manual Investigation Found (Correct)

### Step 1: Verify the Agent's Hypothesis — DISPROVED

```bash
docker exec icscf kamcmd cdp.list_peers
```

Result: Diameter peer to HSS is **fully connected** — `State: I_Open`, `Disabled: False`, all Cx applications registered. The agent's root cause was wrong.

### Step 2: Check the I-CSCF Logs More Carefully

```bash
docker logs icscf 2>&1 | grep -B2 -A2 "6-0LW.nZAM"
```

Found a critical line the agent missed:

```
cxdx_get_experimental_result_code: Failed finding avp
```

This initially appeared to be a Diameter AVP formatting issue between PyHSS and the I-CSCF. However, further investigation showed this was a red herring — the LIA was being processed, and the `lia_return_code` AVP was created successfully.

### Step 3: Check UE Registration State — Both UEs Registered

```bash
docker exec scscf kamcmd ulscscf.showimpu sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org
```

Both UEs were fully registered at the S-CSCF with valid contacts and thousands of seconds remaining on their registrations. The stale-registration hypothesis was also wrong.

### Step 4: Trace the Full Call Path Through the I-CSCF Config

Reading `route[LIR_REPLY]` in `kamailio_icscf.cfg` revealed the call flow:

1. LIA returns successfully (`lia_return_code == 1`) ✓
2. `I_scscf_select("0")` succeeds and forwards INVITE to S-CSCF ✓
3. The S-CSCF receives the INVITE and processes it through `orig` and `term` routes ✓
4. The S-CSCF finds UE2's contact (`192.168.101.3:5060`) via `lookup()` ✓
5. The INVITE is forwarded to the P-CSCF for terminating delivery ✓
6. The P-CSCF receives the terminating INVITE and routes it toward UE2 at `192.168.101.3:5060` ✓
7. **The P-CSCF gets a timeout.** The INVITE never reaches UE2's pjsua.
8. The timeout propagates back: P-CSCF → S-CSCF (408) → I-CSCF `failure_route` → "500 Server error on LIR select next S-CSCF"

The 500 error at the I-CSCF was a **symptom**, not the root cause. The actual failure was between the P-CSCF and UE2.

### Step 5: Check Network Path — Healthy

```bash
docker exec pcscf ping -c 2 192.168.101.3
# Result: 100% success, 1.37ms RTT
```

The IP path from P-CSCF → UPF → UE2 was working. ICMP packets traverse the GTP tunnel fine.

### Step 6: Check UE2 — Never Received the INVITE

```bash
docker logs e2e_ue2 2>&1 | grep "6-0LW.nZAM"
# Result: nothing — UE2 never saw this Call-ID
```

UE2's pjsua logs had no record of the INVITE. The network was reachable by ping, but the SIP INVITE wasn't arriving.

### Step 7: Check Transport — THE ROOT CAUSE

```bash
docker exec pcscf grep "udp_mtu_try_proto" /etc/kamailio_pcscf/kamailio_pcscf.cfg
# Result: udp_mtu_try_proto = TCP
```

**Found it.** The P-CSCF's `udp_mtu_try_proto` was set to `TCP`. When a SIP message exceeds `udp_mtu` (1300 bytes), Kamailio automatically switches from UDP to TCP. A SIP INVITE with SDP body is typically 1500-2000 bytes — well over 1300.

UE2's pjsua only listens on **UDP** port 5060:

```
UNCONN  192.168.101.3:5060  ← UDP only
```

The P-CSCF sent the terminating INVITE via TCP. UE2 has no TCP listener. The INVITE was silently dropped. The TCP connection attempt timed out, which propagated back through the SIP call path as a 408 → 500.

### Step 8: Why the Fix Was Lost

The deploy scripts (`e2e-vonr-test.sh`, `deploy-ues.sh`) correctly copy a fixed config with `udp_mtu_try_proto = UDP` into the running container. This worked during deployment. However:

- The host file `./pcscf/kamailio_pcscf.cfg` (mounted as a Docker volume) still had `TCP`
- The P-CSCF container was restarted at 18:23 (when the stack was brought up fresh)
- On restart, the container entrypoint copies files from the volume mount (`/mnt/pcscf/`) to `/etc/kamailio_pcscf/`, overwriting the runtime fix with the original `TCP` value

The fix was a **runtime patch** that didn't survive container restarts.

---

## Root Cause

**The P-CSCF's `udp_mtu_try_proto = TCP` setting causes SIP INVITEs (which exceed 1300 bytes with SDP) to be sent via TCP to UE endpoints that only listen on UDP.** The INVITE is silently undelivered, causing a timeout that cascades back through the IMS signaling path as a 500 error at the I-CSCF.

This is the same root cause as the previous RCA (`ims_registration_failed_408.md`), but manifesting on a different SIP method (INVITE vs REGISTER) and appearing at a different point in the call path (I-CSCF 500 vs P-CSCF 408).

---

## Fix Applied

**Permanent fix:** Changed `udp_mtu_try_proto` from `TCP` to `UDP` in the **source file** on the host:

```
File: pcscf/kamailio_pcscf.cfg (line 134)
Before: udp_mtu_try_proto = TCP
After:  udp_mtu_try_proto = UDP
```

This is the file mounted into the container via Docker Compose (`volumes: ./pcscf:/mnt/pcscf`). Because it's the source of truth — not a runtime copy — the fix survives:

- `docker restart pcscf`
- `docker compose down && docker compose up`
- "Deploy Stack" button
- "Deploy UEs" button
- Any other container lifecycle operation

The `operate/kamailio/pcscf/kamailio_pcscf.cfg` (the deploy script's copy) already had the correct `UDP` value. The deploy scripts' `docker cp` commands are now redundant for this setting, which is the correct state — the source of truth and the runtime copy agree.

---

## Timeline

| Time | Event |
|---|---|
| ~14:24 | Stack deployed via "Deploy Stack" button. `e2e-vonr-test.sh` copies fixed config (`UDP`). P-CSCF restarted with correct config. |
| ~18:23 | Stack brought up fresh (docker compose). P-CSCF container restarts, volume mount overwrites fix with original `TCP` value. |
| ~18:35 | UE1 attempts to call UE2. Call fails with 500 at I-CSCF. |
| ~18:36 | Troubleshooting agent invoked. Agent diagnoses (incorrectly) as missing Diameter config. |
| ~18:40 | Manual investigation begins. Agent's hypothesis disproved via `kamcmd cdp.list_peers`. |
| ~18:55 | Full call path traced through I-CSCF, S-CSCF, P-CSCF. INVITE reaches P-CSCF but never arrives at UE2. |
| ~19:00 | `udp_mtu_try_proto = TCP` identified as root cause. |
| ~19:05 | Permanent fix applied to host source file. P-CSCF restarted. Verified fix survives restart. |

---

## Lessons Learned

### 1. The Agent Did Not Trace the Call Path to the End

This is the most important lesson. The agent claimed it "traced the call path" but it stopped at the I-CSCF. It never checked:
- Did the S-CSCF receive the terminating INVITE? (It did.)
- Did the S-CSCF find UE2's contact and forward the INVITE? (It did.)
- Did the P-CSCF receive the terminating INVITE and attempt to deliver it to UE2? (It did.)
- **Did UE2 actually receive the INVITE?** (It did not.)

If the agent had checked UE2's logs for the specific Call-ID (`6-0LW.nZAM`), it would have found **nothing** — UE2 never saw the INVITE. That single observation would have shifted the entire investigation from "why can't the I-CSCF talk to the HSS?" to "why isn't the INVITE reaching UE2?" — which is the correct question.

In telecom troubleshooting, a call path has two ends. You must verify both. The agent verified the originating end (UE1 sent INVITE, P-CSCF forwarded, S-CSCF processed, I-CSCF returned error) but never verified the terminating end (did UE2 receive anything?). The error message at the I-CSCF was seductive — it looked like the root cause — but it was just the point where the cascading timeout surfaced.

**Rule:** When investigating a call failure, always check both ends. If the originating side shows an error, check whether the terminating side even received the request. The absence of evidence at the terminating endpoint is itself a critical diagnostic signal.

**Improvement for the agent:** The investigation methodology should include a mandatory step: "Verify that the request reached the destination endpoint." For SIP call failures, this means checking UE2's logs for the Call-ID, not just tracing upstream errors.

### 2. The Agent's Transport Layer Blind Spot

Even after the end-to-end check would have revealed the INVITE wasn't reaching UE2, the agent would still need to figure out *why*. The transport layer (UDP vs TCP) was the actual mechanism of failure. The agent never investigated:
- What transport the P-CSCF used to send the terminating INVITE
- The `udp_mtu_try_proto` setting
- Whether UE2 had a TCP listener

**Improvement for the agent:** Add a tool or investigation step that checks SIP transport settings (`udp_mtu_try_proto`, TCP/UDP listener state) when SIP messages are not being received at an endpoint that is known to be running and reachable by ICMP.

### 3. Runtime Patches Don't Survive Restarts

The deploy scripts applied the fix correctly as a runtime `docker cp`, but the source of truth (the volume-mounted host file) was never updated. This is a fundamental flaw in the "patch at runtime" approach.

**Rule:** Always fix the source of truth. Runtime patches should be a temporary measure, not a permanent fix.

### 4. The 500 Error Was a Symptom, Not the Cause

The `500 Server error on LIR select next S-CSCF` appeared to originate at the I-CSCF, leading the agent to investigate I-CSCF Diameter connectivity. In reality, the error was a cascading timeout:

```
P-CSCF sends INVITE via TCP → UE2 doesn't receive (no TCP listener)
→ P-CSCF times out → S-CSCF gets 408
→ I-CSCF failure_route: "select next S-CSCF" fails (only one S-CSCF)
→ I-CSCF returns 500 to originating S-CSCF → propagates to UE1
```

**Rule:** When you see a 500 at an intermediate node, trace the full path to the terminal endpoint before blaming the intermediate node.

### 5. This Was a Repeat Failure

The same `udp_mtu_try_proto = TCP` issue caused the 408 registration failure documented in `ims_registration_failed_408.md`. The fix was applied at the time but as a runtime patch, not a permanent source fix. The failure recurred because the patch was lost on restart.

**Rule:** When fixing a root cause, verify the fix persists across all lifecycle events (restart, redeploy, scale). If the fix is applied to a running container, it MUST also be applied to the source (Dockerfile, volume mount, compose file, or host config).

---

## Scoring the Troubleshooting Agent

If we score the agent's diagnosis using the Challenge Mode scorer:

| Dimension | Score | Notes |
|---|---|---|
| Root cause correct | 0 | Blamed I-CSCF Diameter config. Actual root cause: P-CSCF transport setting. |
| Component overlap | 0 | Agent said {icscf, pyhss, scscf}. Actual: {pcscf}. Zero overlap. |
| Severity correct | 1.0 | Correctly identified as "call failure" severity. |
| Fault type identified | 0 | Did not identify transport/config issue. |
| Confidence calibrated | 0 | Said "High confidence" but was wrong. Worst possible calibration. |
| Investigation thoroughness | 0 | Did not verify the INVITE reached UE2. Stopped at the first plausible-looking error (I-CSCF 500) without tracing to the terminal endpoint. |
| **Total** | **~10%** | |

**The agent's fundamental failure was not an inability to understand transport protocols — it was an incomplete investigation.** It stopped at the first error it found and built a hypothesis around it, without verifying the hypothesis against the other end of the call path. A single check — "did UE2 receive the INVITE?" — would have changed the entire trajectory of the investigation.

This is the most valuable training signal from this episode: an RCA agent must verify that requests reach their destination, not just trace errors backward from where they surface. The I-CSCF's 500 error was 4 hops away from the actual failure point. The agent needed to check UE2 (the destination) to find that the INVITE never arrived, then work backward from there.

This episode, if recorded via the chaos platform's Challenge Mode, would teach the agent: **when a call fails, check the callee's logs first.**
