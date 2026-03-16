# VoNR Call Flow — Full Stack Trace

A detailed trace of an end-to-end VoNR call between two UERANSIM UEs (UE1 → UE2) through the entire 5G SA + IMS stack. All timestamps and log excerpts are from an actual successful call.

## Network Topology

```
UE1 (192.168.101.31)                                          UE2 (192.168.101.30)
  uesimtun1                                                     uesimtun1
      |                                                             |
      v                                                             v
  gNB (nr_gnb)  ----GTP-U---->  UPF (172.22.0.10)  <----GTP-U----  gNB
                                    |
                          Docker network (172.22.0.x)
                                    |
        +---------------------------+---------------------------+
        |                           |                           |
  P-CSCF (172.22.0.21)    S-CSCF (172.22.0.20:6060)    I-CSCF (172.22.0.19:4060)
        |                           |                           |
  RTPEngine (172.22.0.16)   PyHSS (Diameter)            PyHSS (Diameter)
                                    |
                             PCF (172.22.0.27)
                                    |
                              SMF ---- UPF
```

## Phase 1: SIP Signaling (UE1 → IMS → UE2)

### 1. UE1 pjsua — INVITE creation (13:00:18.386–392)

pjsua creates the INVITE with SDP offering 14 audio codecs (Speex, GSM, PCMU, PCMA, G722, AMR, AMR-WB, Opus, etc.) and RTP on `192.168.101.31:4000`.

It first tries TCP (the INVITE is 1675 bytes, exceeding the 1300-byte `udp_mtu` threshold) but `--no-tcp` blocks TCP, so it falls back to UDP:

```
Temporary failure in sending Request msg INVITE/cseq=18422,
will try next server: Unsupported transport (PJSIP_EUNSUPTRANSPORT)
```

The INVITE is sent via UDP to the P-CSCF at `172.22.0.21:5060`. Key headers:

```
INVITE sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org SIP/2.0
Via: SIP/2.0/UDP 192.168.101.31:5060
Route: <sip:172.22.0.21:5060;transport=udp;lr>
Route: <sip:orig@scscf.ims.mnc001.mcc001.3gppnetwork.org:6060;lr>
```

The second `Route` header (`orig@scscf`) was learned from the `Service-Route` during REGISTER — it tells the P-CSCF to forward via the S-CSCF's originating route.

### 2. gNB + UPF — IP transport (13:00:18.392–400)

The SIP INVITE travels as IP packets through the GTP-U tunnel:

```
UE1 uesimtun1 (192.168.101.31) → gNB → GTP-U → UPF → P-CSCF (172.22.0.21)
```

The gNB logs show:

```
[ngap] error: Unhandled NGAP initiating-message received (9)
```

This is the AMF sending **N2 PDU Session Resource Modify** requests to set up a dedicated QoS flow for voice (5QI=1). UERANSIM doesn't fully implement this NGAP message, but it doesn't break the call — SIP and RTP traffic flows over the default bearer instead.

### 3. P-CSCF — MO (Mobile Originating) side (13:00:18.400)

The P-CSCF processes the INVITE through several routes:

**Route `DEFAULT_ROUTE`** — Identifies this as an INVITE from `001011234567891` to `001011234567892`:

```
PCSCF: INVITE sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org
  (sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org (192.168.101.31:5060)
   to sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org)
```

**Route `MO`** — Recognizes UE1 is registered (`pcscf_is_registered()` passes since both REGISTER and INVITE used UDP). Sets destination to `sip:orig@scscf.ims.mnc001.mcc001.3gppnetwork.org:6060` (the S-CSCF's originating route).

```
Destination URI: sip:orig@scscf.ims.mnc001.mcc001.3gppnetwork.org:6060;lr
Next hop domain: (scscf.ims.mnc001.mcc001.3gppnetwork.org)
```

**`P-Charging-Vector` generation** — Generates a charging correlation ID for the call:

```
P-Charging-Vector: icid-value=495653AC1600152D0000002201000000;icid-generated-at=172.22.0.21
```

**Route `N5_INIT_REQ`** — N5 QoS policy authorization for the originating UE. Sends an HTTP/2 POST to the PCF (`172.22.0.27:7777`) at the `npcf-policyauthorization` API:

```
SDP Info MOC: Connection IP is 192.168.101.31 Port is 4000
  Mline dump m=audio 4000 RTP/AVP 96 97 98 99 3 0 8 9 100 101 102 120 121 122 123
Preparing QoS N5 Message to PCF for the INVITE
N5 QoS Session successfully Created 201
AppSession Id for user 001011234567891 is: 16
```

The N5 request includes media component descriptions:

```json
{
  "ascReqData": {
    "afAppId": "+g.3gpp.icsi-ref=\"urn%3Aurn-7%3A3gpp-service.ims.icsi.mmtel\"",
    "dnn": "ims",
    "medComponents": {
      "0": {
        "qosReference": "qosVoNR",
        "medType": "AUDIO",
        "medSubComps": {
          "0": {
            "fDescs": [
              "permit out 17 from any to 192.168.101.31 4000",
              "permit in 17 from 192.168.101.31 4000 to any"
            ],
            "marBwDl": "5000 Kbps",
            "marBwUl": "3000 Kbps",
            "flowUsage": "NO_INFO"
          },
          "1": {
            "fDescs": [
              "permit out 17 from any to 192.168.101.31 4001",
              "permit in 17 from 192.168.101.31 4001 to any"
            ],
            "flowUsage": "RTCP"
          }
        }
      }
    },
    "gpsi": "msisdn-001011234567891",
    "ueIpv4": "192.168.101.31"
  }
}
```

**Route `NATMANAGE`** — RTPEngine media anchoring. Passes the SDP through RTPEngine (`172.22.0.16`) with flags:

```
Offer: replace-origin replace-session-connection ICE=remove RTP AVP
Answer: replace-origin replace-session-connection ICE=force RTP AVP
Handling RTP for initial request from 001011234567891 on mo side
```

RTPEngine allocates proxy ports (`49524/49525`) and replaces UE1's media IP in the SDP with its own (`172.22.0.16`). This anchors all RTP through RTPEngine.

The modified INVITE is forwarded to the S-CSCF.

### 4. S-CSCF — Originating (172.22.0.20:6060)

```
SCSCF: INVITE sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org
  (sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org (172.22.0.21:5060)
   to sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org)
```

**Route `orig`**:

- Creates a new IMS dialog (call-id `JyjjCuCEILH--GQ3m45gbVLZgrYOpPkd`, hash 3602).
- Stores caller's leg info: route set, contact (`sip:001011234567891@192.168.101.31:5060`), cseq 18422, bind address `udp:172.22.0.20:6060`.
- Runs **Initial Filter Criteria** (`isc_match_filter()`) to check if any Application Servers should be triggered for the caller's originating services. No AS triggers match (no supplementary services configured), so the INVITE passes through unmodified.

Forwards to the I-CSCF for callee lookup.

### 5. I-CSCF (172.22.0.19:4060)

```
$ru => sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org
```

Performs a **Diameter LIR (Location-Info-Request)** to PyHSS to find which S-CSCF serves the callee (`001011234567892`).

```
ims_icscf [cxdx_lir.c:72]: create_lia_return_code(): created AVP successfully : [lia_return_code]
```

### 6. PyHSS — Diameter LIR/LIA (13:00:18.582)

Receives the Diameter LIR and queries MySQL:

```sql
SELECT ims_subscriber.ims_subscriber_id, ims_subscriber.msisdn, ims_subscriber.imsi,
       ims_subscriber.scscf, ims_subscriber.scscf_realm, ims_subscriber.scscf_peer, ...
FROM ims_subscriber
WHERE ims_subscriber.imsi = '001011234567892'
```

Finds the subscriber's assigned S-CSCF (`sip:scscf.ims.mnc001.mcc001.3gppnetwork.org:6060`) and returns a Diameter LIA (Location-Info-Answer) with the S-CSCF address.

### 7. I-CSCF → S-CSCF (terminating)

I-CSCF forwards the INVITE to the S-CSCF indicated by PyHSS. The INVITE now arrives at the S-CSCF for the second time, but from the I-CSCF (`172.22.0.19:4060`) instead of the P-CSCF.

### 8. S-CSCF — Terminating (172.22.0.20:6060, second pass)

```
SCSCF: INVITE sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org
  (sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org (172.22.0.19:4060)
   to sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org)
```

**Route `term`**:

- Runs **Initial Filter Criteria** for the callee's terminating services (`isc_match_filter()`). No AS triggers match.
- Looks up UE2's registered contact from the `usrloc` table (stored during REGISTER). Finds UE2 is reachable via P-CSCF with contact `sip:001011234567892@192.168.101.30:5060`.
- Forwards the INVITE back to the P-CSCF with a `mt@` route tag.

### 9. P-CSCF — MT (Mobile Terminating) side

**Route `MT`** — Identifies UE2's connection details:

```
Destination URI: sip:192.168.101.30:5060
Next hop domain: (192.168.101.30)
Term UE connection information : IP is 192.168.101.30 and Port is 5060
Term P-CSCF connection information : IP is 172.22.0.21 and Port is 5060
```

**Route `N5_INIT_MT_REQ`** — N5 QoS policy authorization for the terminating UE. Sends a second HTTP/2 POST to the PCF. The SDP now shows RTPEngine's address (`172.22.0.16:49896`) since MO-side RTPEngine already modified it:

```
SDP Info From INVITE: 172.22.0.16 -- 49896 -- 49897
IMS: MTC INVITE TO 001011234567892
Preparing QoS N5 Message to PCF for INVITE To term UE
N5 QoS Session successfully Created 201
AppSession Id for JyjjCuCEILH--GQ3m45gbVLZgrYOpPkd is: 17
```

**Route `NATMANAGE`** — Passes the INVITE SDP through RTPEngine again (MT side), allocating another set of proxy ports for UE2's direction.

Forwards the INVITE to UE2 at `192.168.101.30:5060` via UDP.

### 10. PCF — Policy Authorization (172.22.0.27:7777, 13:00:18.416 and .652)

Receives two N5 PolicyAuthorization requests (one MO, one MT):

```
Setup NF EndPoint(addr) [172.22.0.21:7777]  (at 13:00:18.416)
Setup NF EndPoint(addr) [172.22.0.21:7777]  (at 13:00:18.652)
```

For each request:

- Looks up the subscriber's PCC rules in the UDR (via MongoDB).
- Finds the voice QoS PCC rule provisioned during setup: 5QI=1, ARP priority 1, 128 Kbps GBR.
- Creates policy sessions and returns 201 Created.
- Instructs the SMF (via `Npcf_SMPolicyControl`) to create dedicated QoS flows for voice traffic.

### 11. SMF + UPF — QoS flow setup (13:00:18.427–430)

SMF receives the PCF policy decision and attempts to install PCC rules and create a GBR QoS flow (5QI=1). The SMF/UPF logs show SDP flow description parsing errors:

```
[smf] ERROR: unrecognised option [-1] IN
[smf] ERROR: unrecognised option [-1] IP4
[smf] ERROR: unrecognised option [-1] 192.168.101.31
```

```
[upf] ERROR: unrecognised option [-1] IN
[upf] ERROR: unrecognised option [-1] IP4
[upf] ERROR: unrecognised option [-1] 192.168.101.31
```

These are cosmetic parsing issues with the SDP flow description filter format — they don't block the call.

SMF sends **N2 PDU Session Resource Modify** to AMF, which forwards to gNB via NGAP (message type 9). This is the dedicated voice bearer setup request. UERANSIM doesn't implement this NGAP message:

```
[ngap] error: Unhandled NGAP initiating-message received (9)
```

As a result, traffic flows on the default QoS flow instead of a dedicated voice bearer. The call still works — just without guaranteed QoS at the radio level.

## Phase 2: Call Answer (UE2 → IMS → UE1)

### 12. UE2 pjsua — auto-answer (13:00:18.658–665)

UE2 receives the 2630-byte INVITE from the P-CSCF. The 6 Via headers show the full path the INVITE traveled:

```
UE1 (192.168.101.31) → P-CSCF (172.22.0.21) → S-CSCF orig (172.22.0.20:6060)
→ I-CSCF (172.22.0.19:4060) → S-CSCF term (172.22.0.20:6060)
→ P-CSCF (172.22.0.21) → UE2 (192.168.101.30)
```

The `P-Asserted-Identity` header confirms the caller was verified by the S-CSCF:

```
P-Asserted-Identity: sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org
```

pjsua's `--auto-answer 200` kicks in immediately:

```
Answering call 0: code=200
SDP negotiation done: Success
Audio updated, stream #0: speex (sendrecv)
```

UE2 selects **Speex/16kHz** (codec 96) from the 14 offered codecs. The SDP answer has RTP on `192.168.101.30:4000`.

The ringtone is briefly connected then replaced with call audio:

```
Port 2 (ring) transmitting to port 0 (Master/sound)         ← ringtone on
Port 2 (ring) stop transmitting to port 0 (Master/sound)     ← ringtone off
Port 3 (sip:001011234567891@...) transmitting to port 0      ← call audio on
```

The 200 OK travels back through the reverse path:

```
UE2 → P-CSCF (MT) → S-CSCF (term) → S-CSCF (orig) → P-CSCF (MO) → UE1
```

### 13. P-CSCF — MO reply (200 OK back to UE1)

The P-CSCF's `NATMANAGE` route passes the 200 OK's SDP through RTPEngine (answer side), completing the RTPEngine media session. RTPEngine now has both sides' addresses and will proxy bidirectionally.

```
MO_reply: Source IP and Port: (172.22.0.20:6060)
```

### 14. UE1 pjsua — ACK (13:00:18.695–698)

UE1 receives the 200 OK. SDP negotiation succeeds.

```
Call 0 state changed to CONNECTING
SDP negotiation done: Success
Audio updated, stream #0: speex (sendrecv)
```

Sends ACK through the full Record-Route path (4 hops):

```
Route: <sip:mo@172.22.0.21;lr>         ← P-CSCF (MO)
Route: <sip:mo@172.22.0.20:6060;lr>    ← S-CSCF (orig)
Route: <sip:mt@172.22.0.20:6060;lr>    ← S-CSCF (term)
Route: <sip:mt@172.22.0.21;lr>         ← P-CSCF (MT)
```

```
Call 0 state changed to CONFIRMED
```

Total time from INVITE sent to CONFIRMED: **312ms**.

## Phase 3: Media Flow

### 15. RTPEngine (172.22.0.16)

RTPEngine proxies all RTP/RTCP bidirectionally:

```
UE1 (192.168.101.31:4000) ↔ RTPEngine (172.22.0.16:49524/49525) ↔ UE2 (192.168.101.30:4000)
```

RTPEngine allocates 4 ports total: two for each direction (RTP + RTCP):

```
[JyjjCuCEILH.../hIHdSslj.../1 port 49896]   ← MT side RTP
[JyjjCuCEILH.../w-80kOBbB.../1 port 49525]   ← MO side RTCP
[JyjjCuCEILH.../w-80kOBbB.../1 port 49524]   ← MO side RTP
[JyjjCuCEILH.../hIHdSslj.../1 port 49897]   ← MT side RTCP
```

The kernel forwarding warnings are expected in Docker (no kernel module available):

```
No support for kernel packet forwarding available (interface to kernel module not open)
```

RTPEngine falls back to userspace forwarding, which works fine for testing.

## Phase 4: Session Refresh (ongoing)

### 16. UPDATE messages

After call establishment, pjsua sends Session-Timer UPDATE requests (per RFC 4028, `Session-Expires: 1800;refresher=uac`). These travel the same Record-Route path through all 4 IMS proxies:

```
UE1 → P-CSCF (MO) → S-CSCF (orig) → S-CSCF (term) → P-CSCF (MT) → UE2
```

The P-CSCF's NATMANAGE route sees these are keepalives with no SDP:

```
No SDP body, skipping RTP handling
```

## Component Summary

| Component | IP | Role in the call |
|---|---|---|
| **pjsua (UE1)** | 192.168.101.31 | SIP user agent, generates INVITE, sends RTP |
| **pjsua (UE2)** | 192.168.101.30 | SIP user agent, auto-answers INVITE, receives RTP |
| **gNB** | — | Radio simulation, GTP-U tunnel to UPF. Receives but ignores NGAP QoS modify (msg 9) |
| **AMF** | 172.22.0.22 | Relays N2 QoS session modify between SMF and gNB |
| **SMF** | 172.22.0.10 | Receives PCF policy, creates QoS flow rules, instructs UPF |
| **UPF** | 172.22.0.10 | Forwards IP packets between UE TUN interfaces and IMS network |
| **P-CSCF** | 172.22.0.21 | SIP edge proxy: MO/MT routing, N5 QoS to PCF, RTPEngine media anchoring, `P-Charging-Vector` generation |
| **S-CSCF** | 172.22.0.20:6060 | SIP core: originating/terminating service logic, ISC filter checks, dialog management |
| **I-CSCF** | 172.22.0.19:4060 | SIP entry: Diameter LIR to PyHSS to find callee's S-CSCF |
| **PyHSS** | — | IMS HSS: Diameter LIR/LIA subscriber lookup in MySQL |
| **PCF** | 172.22.0.27 | Policy: creates two QoS sessions (AppSession 16 for MO, 17 for MT), instructs SMF |
| **RTPEngine** | 172.22.0.16 | Media proxy: anchors all RTP/RTCP in userspace, replaces SDP addresses |

## Call Flow Diagram

```
     UE1          P-CSCF        S-CSCF(orig)    I-CSCF     S-CSCF(term)    P-CSCF        UE2
      |              |              |              |              |            |              |
      |---INVITE---->|              |              |              |            |              |
      |              |--N5 MO(PCF)->|              |              |            |              |
      |              |<--201--------|              |              |            |              |
      |              |--RTPEngine-->|              |              |            |              |
      |              |---INVITE---->|              |              |            |              |
      |              |              |--isc_match-->|              |            |              |
      |              |              |---INVITE---->|              |            |              |
      |              |              |              |--LIR(PyHSS)->|            |              |
      |              |              |              |<--LIA--------|            |              |
      |              |              |              |---INVITE---->|            |              |
      |              |              |              |              |--isc_match |              |
      |              |              |              |              |---INVITE-->|              |
      |              |              |              |              |            |--N5 MT(PCF)->|
      |              |              |              |              |            |<--201--------|
      |              |              |              |              |            |--RTPEngine-->|
      |              |              |              |              |            |---INVITE---->|
      |              |              |              |              |            |              |
      |              |              |              |              |            |<--200 OK-----|
      |              |              |              |              |<--200 OK---|              |
      |              |              |              |<--200 OK-----|            |              |
      |              |<--200 OK-----|              |              |            |              |
      |<--200 OK-----|              |              |              |            |              |
      |              |              |              |              |            |              |
      |---ACK------->|---ACK------->|---ACK------->|---ACK------->|---ACK----->|              |
      |              |              |              |              |            |              |
      |====RTP=======|==============|==============|==============|============|====RTP=======|
      |              |        RTPEngine (172.22.0.16) proxies all media        |              |
```

## Annex

Logs from UE1:

```
Make call: 13:00:18.386           pjsua_call.c !Making call with acc #1 to sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org
13:00:18.387            pjsua_aud.c  .Set sound device: capture=-99, playback=-99, mode=0, use_default_settings=0
13:00:18.387            pjsua_aud.c  ..Null sound device, mode setting is ignored
13:00:18.387            pjsua_aud.c  ..Setting null sound device..
13:00:18.387            pjsua_app.c  ...Turning sound device -99 -99 ON
13:00:18.387            pjsua_aud.c  ...Opening null sound device..
13:00:18.389          pjsua_media.c  .Call 0: initializing media..
13:00:18.389          pjsua_media.c  ..RTP socket reachable at 192.168.101.31:4000
13:00:18.389          pjsua_media.c  ..RTCP socket reachable at 192.168.101.31:4001
13:00:18.390     srtp0x58e001735ea0  ..SRTP transport created
13:00:18.390          pjsua_media.c  ..Media index 0 selected for audio call 0
13:00:18.390      udp0x58e00181f5d0  ..UDP media transport created
13:00:18.392      tsx0x58e00182fcf8  ....Temporary failure in sending Request msg INVITE/cseq=18422 (tdta0x58e00182cd88), will try next server: Unsupported transport (PJSIP_EUNSUPTRANSPORT)
13:00:18.392           pjsua_core.c  ....TX 1675 bytes Request msg INVITE/cseq=18422 (tdta0x58e00182cd88) to UDP 172.22.0.21:5060:
INVITE sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org SIP/2.0
Via: SIP/2.0/UDP 192.168.101.31:5060;rport;branch=z9hG4bKPj.YTIr3wnVFHYg4Uow18nzJbR0l4QamOF
Max-Forwards: 70
From: sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org;tag=w-80kOBbBU8x48da5YgS5memObfSM6U2
To: sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org
Contact: sip:001011234567891@192.168.101.31:5060;ob
Call-ID: JyjjCuCEILH--GQ3m45gbVLZgrYOpPkd
CSeq: 18422 INVITE
Route: sip:172.22.0.21:5060;transport=udp;lr
Route: sip:orig@scscf.ims.mnc001.mcc001.3gppnetwork.org:6060;lr
Allow: PRACK, INVITE, ACK, BYE, CANCEL, UPDATE, INFO, SUBSCRIBE, NOTIFY, REFER, MESSAGE, OPTIONS
Supported: replaces, 100rel, timer, norefersub
Session-Expires: 1800
Min-SE: 90
User-Agent: PJSUA v2.14.1 Linux-6.6.87.2/x86_64/glibc-2.35
Content-Type: application/sdp
Content-Length:   807

v=0
o=- 3982323618 3982323618 IN IP4 192.168.101.31
s=pjmedia
b=AS:117
t=0 0
a=X-nat:0
m=audio 4000 RTP/AVP 96 97 98 99 3 0 8 9 100 101 102 120 121 122 123
c=IN IP4 192.168.101.31
b=TIAS:96000
a=rtcp:4001 IN IP4 192.168.101.31
a=sendrecv
a=rtpmap:96 speex/16000
a=rtpmap:97 speex/8000
a=rtpmap:98 speex/32000
a=rtpmap:99 iLBC/8000
a=fmtp:99 mode=30
a=rtpmap:3 GSM/8000
a=rtpmap:0 PCMU/8000
a=rtpmap:8 PCMA/8000
a=rtpmap:9 G722/8000
a=rtpmap:100 AMR/8000
a=rtpmap:101 AMR-WB/16000
a=rtpmap:102 opus/48000/2
a=fmtp:102 useinbandfec=1
a=rtpmap:120 telephone-event/16000
a=fmtp:120 0-16
a=rtpmap:121 telephone-event/8000
a=fmtp:121 0-16
a=rtpmap:122 telephone-event/32000
a=fmtp:122 0-16
a=rtpmap:123 telephone-event/48000
a=fmtp:123 0-16
a=ssrc:49664467 cname:2184d8c911b22962

--end msg--
13:00:18.392            pjsua_app.c  .......Call 0 state changed to CALLING
>>> 13:00:18.400           pjsua_core.c !.RX 414 bytes Response msg 100/INVITE/cseq=18422 (rdata0x73937c000b98) from UDP 172.22.0.21:5060:
SIP/2.0 100 Trying
Via: SIP/2.0/UDP 192.168.101.31:5060;rport=5060;received=192.168.101.31;branch=z9hG4bKPj.YTIr3wnVFHYg4Uow18nzJbR0l4QamOF
From: sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org;tag=w-80kOBbBU8x48da5YgS5memObfSM6U2
To: sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org
Call-ID: JyjjCuCEILH--GQ3m45gbVLZgrYOpPkd
CSeq: 18422 INVITE
Server: TelcoSuite Proxy-CSCF
Content-Length: 0


--end msg--
13:00:18.695           pjsua_core.c  .RX 1412 bytes Response msg 200/INVITE/cseq=18422 (rdata0x73937c000b98) from UDP 172.22.0.21:5060:
SIP/2.0 200 OK
Via: SIP/2.0/UDP 192.168.101.31:5060;rport=5060;received=192.168.101.31;branch=z9hG4bKPj.YTIr3wnVFHYg4Uow18nzJbR0l4QamOF
Record-Route: sip:mt@172.22.0.21;lr;ftag=w-80kOBbBU8x48da5YgS5memObfSM6U2;rm=7;did=21e.a5
Record-Route: sip:mt@172.22.0.20:6060;lr;ftag=w-80kOBbBU8x48da5YgS5memObfSM6U2;did=21e.c0c
Record-Route: sip:mo@172.22.0.20:6060;lr;ftag=w-80kOBbBU8x48da5YgS5memObfSM6U2;did=21e.b0c
Record-Route: sip:mo@172.22.0.21;lr;ftag=w-80kOBbBU8x48da5YgS5memObfSM6U2;rm=8;did=21e.95
Call-ID: JyjjCuCEILH--GQ3m45gbVLZgrYOpPkd
From: sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org;tag=w-80kOBbBU8x48da5YgS5memObfSM6U2
To: sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org;tag=hIHdSslj4K8oLOTucLND1m34Np-1sRzD
CSeq: 18422 INVITE
Contact: sip:001011234567892@192.168.101.30:5060;alias=192.168.101.30~5060~1;ob
Allow: PRACK, INVITE, ACK, BYE, CANCEL, UPDATE, INFO, SUBSCRIBE, NOTIFY, REFER, MESSAGE, OPTIONS
Supported: replaces, 100rel, timer, norefersub
Session-Expires: 1800;refresher=uac
Require: timer
Content-Type: application/sdp
Content-Length:   301

v=0
o=- 3982323618 3982323619 IN IP4 172.22.0.16
s=pjmedia
b=AS:117
t=0 0
a=X-nat:0
m=audio 49524 RTP/AVP 96 120
c=IN IP4 172.22.0.16
b=TIAS:96000
a=rtpmap:96 speex/16000
a=rtpmap:120 telephone-event/16000
a=fmtp:120 0-16
a=ssrc:574766892 cname:5be3f8f676030d2b
a=sendrecv
a=rtcp:49525

--end msg--
13:00:18.696            pjsua_app.c  .....Call 0 state changed to CONNECTING
13:00:18.696      inv0x58e001822038  ....SDP negotiation done: Success
13:00:18.696          pjsua_media.c  .....Call 0: updating media..
13:00:18.696          pjsua_media.c  .......Media stream call00:0 is destroyed
13:00:18.696      udp0x58e00181f5d0  ......UDP media transport started
13:00:18.696            pjsua_aud.c  ......Audio channel update..
13:00:18.696     strm0x73937c008658  .......VAD temporarily disabled
13:00:18.697      udp0x58e00181f5d0  .......UDP media transport attached
13:00:18.697     strm0x73937c008658  .......Encoder stream started
13:00:18.697     strm0x73937c008658  .......Decoder stream started
13:00:18.697          pjsua_media.c  ......Audio updated, stream #0: speex (sendrecv)
13:00:18.698            pjsua_app.c  .....Call 0 media 0 [type=audio], status is Active
13:00:18.698            pjsua_aud.c  .....Conf connect: 3 --> 0
13:00:18.698           conference.c  ......Port 3 (sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org) transmitting to port 0 (Master/sound)
13:00:18.698            pjsua_aud.c  .....Conf connect: 0 --> 3
13:00:18.698           conference.c  ......Port 0 (Master/sound) transmitting to port 3 (sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org)
13:00:18.698           pjsua_core.c  .....TX 817 bytes Request msg ACK/cseq=18422 (tdta0x73937c01b3f8) to UDP 172.22.0.21:5060:
ACK sip:001011234567892@192.168.101.30:5060;alias=192.168.101.30~5060~1;ob SIP/2.0
Via: SIP/2.0/UDP 192.168.101.31:5060;rport;branch=z9hG4bKPjNBTnZpKeC6ea3V-tAIpafcmF9TFld-yR
Max-Forwards: 70
From: sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org;tag=w-80kOBbBU8x48da5YgS5memObfSM6U2
To: sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org;tag=hIHdSslj4K8oLOTucLND1m34Np-1sRzD
Call-ID: JyjjCuCEILH--GQ3m45gbVLZgrYOpPkd
CSeq: 18422 ACK
Route: sip:mo@172.22.0.21;lr;ftag=w-80kOBbBU8x48da5YgS5memObfSM6U2;rm=8;did=21e.95
Route: sip:mo@172.22.0.20:6060;lr;ftag=w-80kOBbBU8x48da5YgS5memObfSM6U2;did=21e.b0c
Route: sip:mt@172.22.0.20:6060;lr;ftag=w-80kOBbBU8x48da5YgS5memObfSM6U2;did=21e.c0c
Route: sip:mt@172.22.0.21;lr;ftag=w-80kOBbBU8x48da5YgS5memObfSM6U2;rm=7;did=21e.a5
Content-Length:  0


--end msg--
13:00:18.698            pjsua_app.c  .....Call 0 state changed to CONFIRMED
13:00:18.709     strm0x73937c008658 !Resetting jitter buffer in stream playback start
13:00:19.329     strm0x73937c008658  VAD re-enabled
```

Logs from UE2:

```
13:00:18.658           pjsua_core.c  .RX 2630 bytes Request msg INVITE/cseq=18422 (rdata0x7121fc000b98) from UDP 172.22.0.21:5060:
INVITE sip:001011234567892@192.168.101.30:5060;ob SIP/2.0
Record-Route: sip:mt@172.22.0.21;lr=on;ftag=w-80kOBbBU8x48da5YgS5memObfSM6U2;rm=7;did=21e.a5
Record-Route: sip:mt@172.22.0.20:6060;lr=on;ftag=w-80kOBbBU8x48da5YgS5memObfSM6U2;did=21e.c0c
Record-Route: sip:mo@172.22.0.20:6060;lr=on;ftag=w-80kOBbBU8x48da5YgS5memObfSM6U2;did=21e.b0c
Record-Route: sip:mo@172.22.0.21;lr=on;ftag=w-80kOBbBU8x48da5YgS5memObfSM6U2;rm=8;did=21e.95
Via: SIP/2.0/UDP 172.22.0.21;branch=z9hG4bK74eb.744a33be6e4975aa0e56494759108bf8.0
Via: SIP/2.0/UDP 172.22.0.20:6060;branch=z9hG4bK74eb.3c24ecf872bd32ef0c970431c183a8de.0
Via: SIP/2.0/UDP 172.22.0.19:4060;branch=z9hG4bK74eb.447395881ee4591d65110c73bea6a1c8.1
Via: SIP/2.0/UDP 172.22.0.20:6060;branch=z9hG4bK74eb.1bc915954230425f18b8599085ee8133.0
Via: SIP/2.0/UDP 172.22.0.21;branch=z9hG4bK74eb.1aac7d1e8da819273d313234aa56ab8f.0
Via: SIP/2.0/UDP 192.168.101.31:5060;received=192.168.101.31;rport=5060;branch=z9hG4bKPj.YTIr3wnVFHYg4Uow18nzJbR0l4QamOF
Max-Forwards: 65
From: sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org;tag=w-80kOBbBU8x48da5YgS5memObfSM6U2
To: sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org
Contact: sip:001011234567891@192.168.101.31:5060;alias=192.168.101.31~5060~1;ob
Call-ID: JyjjCuCEILH--GQ3m45gbVLZgrYOpPkd
CSeq: 18422 INVITE
Allow: PRACK, INVITE, ACK, BYE, CANCEL, UPDATE, INFO, SUBSCRIBE, NOTIFY, REFER, MESSAGE, OPTIONS
Supported: replaces, 100rel, timer, norefersub
Session-Expires: 1800
Min-SE: 90
User-Agent: PJSUA v2.14.1 Linux-6.6.87.2/x86_64/glibc-2.35
Content-Type: application/sdp
Content-Length:   781
P-Charging-Vector: icid-value=495653AC1600152D0000002201000000;icid-generated-at=172.22.0.21
P-Visited-Network-ID: ims.mnc001.mcc001.3gppnetwork.org
P-Asserted-Identity: sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org

v=0
o=- 3982323618 3982323618 IN IP4 172.22.0.16
s=pjmedia
b=AS:117
t=0 0
a=X-nat:0
m=audio 49896 RTP/AVP 96 97 98 99 3 0 8 9 100 101 102 120 121 122 123
c=IN IP4 172.22.0.16
b=TIAS:96000
a=rtpmap:96 speex/16000
a=rtpmap:97 speex/8000
a=rtpmap:98 speex/32000
a=rtpmap:99 iLBC/8000
a=fmtp:99 mode=30
a=rtpmap:3 GSM/8000
a=rtpmap:0 PCMU/8000
a=rtpmap:8 PCMA/8000
a=rtpmap:9 G722/8000
a=rtpmap:100 AMR/8000
a=rtpmap:101 AMR-WB/16000
a=rtpmap:102 opus/48000/2
a=fmtp:102 useinbandfec=1
a=rtpmap:120 telephone-event/16000
a=fmtp:120 0-16
a=rtpmap:121 telephone-event/8000
a=fmtp:121 0-16
a=rtpmap:122 telephone-event/32000
a=fmtp:122 0-16
a=rtpmap:123 telephone-event/48000
a=fmtp:123 0-16
a=ssrc:49664467 cname:2184d8c911b22962
a=sendrecv
a=rtcp:49897

--end msg--
13:00:18.659           pjsua_call.c  .Incoming Request msg INVITE/cseq=18422 (rdata0x7121fc000b98)
13:00:18.660          pjsua_media.c  ..Call 0: initializing media..
13:00:18.660          pjsua_media.c  ...RTP socket reachable at 192.168.101.30:4000
13:00:18.660          pjsua_media.c  ...RTCP socket reachable at 192.168.101.30:4001
13:00:18.660     srtp0x7121fc018130  ...SRTP transport created
13:00:18.660          pjsua_media.c  ...Media index 0 selected for audio call 0
13:00:18.660      udp0x5f5f94fa86c0  ...UDP media transport created
13:00:18.661           pjsua_core.c  .....TX 1218 bytes Response msg 100/INVITE/cseq=18422 (tdta0x7121fc021b58) to UDP 172.22.0.21:5060:
SIP/2.0 100 Trying
Via: SIP/2.0/UDP 172.22.0.21;received=172.22.0.21;branch=z9hG4bK74eb.744a33be6e4975aa0e56494759108bf8.0
Via: SIP/2.0/UDP 172.22.0.20:6060;branch=z9hG4bK74eb.3c24ecf872bd32ef0c970431c183a8de.0
Via: SIP/2.0/UDP 172.22.0.19:4060;branch=z9hG4bK74eb.447395881ee4591d65110c73bea6a1c8.1
Via: SIP/2.0/UDP 172.22.0.20:6060;branch=z9hG4bK74eb.1bc915954230425f18b8599085ee8133.0
Via: SIP/2.0/UDP 172.22.0.21;branch=z9hG4bK74eb.1aac7d1e8da819273d313234aa56ab8f.0
Via: SIP/2.0/UDP 192.168.101.31:5060;rport=5060;received=192.168.101.31;branch=z9hG4bKPj.YTIr3wnVFHYg4Uow18nzJbR0l4QamOF
Record-Route: sip:mt@172.22.0.21;lr;ftag=w-80kOBbBU8x48da5YgS5memObfSM6U2;rm=7;did=21e.a5
Record-Route: sip:mt@172.22.0.20:6060;lr;ftag=w-80kOBbBU8x48da5YgS5memObfSM6U2;did=21e.c0c
Record-Route: sip:mo@172.22.0.20:6060;lr;ftag=w-80kOBbBU8x48da5YgS5memObfSM6U2;did=21e.b0c
Record-Route: sip:mo@172.22.0.21;lr;ftag=w-80kOBbBU8x48da5YgS5memObfSM6U2;rm=8;did=21e.95
Call-ID: JyjjCuCEILH--GQ3m45gbVLZgrYOpPkd
From: sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org;tag=w-80kOBbBU8x48da5YgS5memObfSM6U2
To: sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org
CSeq: 18422 INVITE
Content-Length:  0


--end msg--
13:00:18.661            pjsua_aud.c  ..Conf connect: 2 --> 0
13:00:18.661            pjsua_aud.c  ...Set sound device: capture=-99, playback=-99, mode=0, use_default_settings=0
13:00:18.661            pjsua_aud.c  ....Null sound device, mode setting is ignored
13:00:18.661            pjsua_aud.c  ....Setting null sound device..
13:00:18.661            pjsua_app.c  .....Turning sound device -99 -99 ON
13:00:18.661            pjsua_aud.c  .....Opening null sound device..
13:00:18.662           conference.c  ...Port 2 (ring) transmitting to port 0 (Master/sound)
13:00:18.662           pjsua_call.c  ..Answering call 0: code=200
13:00:18.663      inv0x7121fc008e88  ....SDP negotiation done: Success
13:00:18.663          pjsua_media.c  .....Call 0: updating media..
13:00:18.663          pjsua_media.c  .......Media stream call00:0 is destroyed
13:00:18.663      udp0x5f5f94fa86c0  ......UDP media transport started
13:00:18.663            pjsua_aud.c  ......Audio channel update..
13:00:18.664     strm0x7121fc02cef8  .......VAD temporarily disabled
13:00:18.664      udp0x5f5f94fa86c0  .......UDP media transport attached
13:00:18.664     strm0x7121fc02cef8  .......Encoder stream started
13:00:18.665     strm0x7121fc02cef8  .......Decoder stream started
13:00:18.665          pjsua_media.c  ......Audio updated, stream #0: speex (sendrecv)
13:00:18.665            pjsua_app.c  .....Call 0 media 0 [type=audio], status is Active
13:00:18.665            pjsua_aud.c  .....Conf disconnect: 2 -x- 0
13:00:18.665           conference.c  ......Port 2 (ring) stop transmitting to port 0 (Master/sound)
13:00:18.665            pjsua_aud.c  .....Conf connect: 3 --> 0
13:00:18.665           conference.c  ......Port 3 (sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org) transmitting to port 0 (Master/sound)
13:00:18.665            pjsua_aud.c  .....Conf connect: 0 --> 3
13:00:18.665           conference.c  ......Port 0 (Master/sound) transmitting to port 3 (sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org)
13:00:18.665           pjsua_core.c  ......TX 1866 bytes Response msg 200/INVITE/cseq=18422 (tdta0x7121fc026c88) to UDP 172.22.0.21:5060:
SIP/2.0 200 OK
Via: SIP/2.0/UDP 172.22.0.21;received=172.22.0.21;branch=z9hG4bK74eb.744a33be6e4975aa0e56494759108bf8.0
Via: SIP/2.0/UDP 172.22.0.20:6060;branch=z9hG4bK74eb.3c24ecf872bd32ef0c970431c183a8de.0
Via: SIP/2.0/UDP 172.22.0.19:4060;branch=z9hG4bK74eb.447395881ee4591d65110c73bea6a1c8.1
Via: SIP/2.0/UDP 172.22.0.20:6060;branch=z9hG4bK74eb.1bc915954230425f18b8599085ee8133.0
Via: SIP/2.0/UDP 172.22.0.21;branch=z9hG4bK74eb.1aac7d1e8da819273d313234aa56ab8f.0
Via: SIP/2.0/UDP 192.168.101.31:5060;rport=5060;received=192.168.101.31;branch=z9hG4bKPj.YTIr3wnVFHYg4Uow18nzJbR0l4QamOF
Record-Route: sip:mt@172.22.0.21;lr;ftag=w-80kOBbBU8x48da5YgS5memObfSM6U2;rm=7;did=21e.a5
Record-Route: sip:mt@172.22.0.20:6060;lr;ftag=w-80kOBbBU8x48da5YgS5memObfSM6U2;did=21e.c0c
Record-Route: sip:mo@172.22.0.20:6060;lr;ftag=w-80kOBbBU8x48da5YgS5memObfSM6U2;did=21e.b0c
Record-Route: sip:mo@172.22.0.21;lr;ftag=w-80kOBbBU8x48da5YgS5memObfSM6U2;rm=8;did=21e.95
Call-ID: JyjjCuCEILH--GQ3m45gbVLZgrYOpPkd
From: sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org;tag=w-80kOBbBU8x48da5YgS5memObfSM6U2
To: sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org;tag=hIHdSslj4K8oLOTucLND1m34Np-1sRzD
CSeq: 18422 INVITE
Contact: sip:001011234567892@192.168.101.30:5060;ob
Allow: PRACK, INVITE, ACK, BYE, CANCEL, UPDATE, INFO, SUBSCRIBE, NOTIFY, REFER, MESSAGE, OPTIONS
Supported: replaces, 100rel, timer, norefersub
Session-Expires: 1800;refresher=uac
Require: timer
Content-Type: application/sdp
Content-Length:   327

v=0
o=- 3982323618 3982323619 IN IP4 192.168.101.30
s=pjmedia
b=AS:117
t=0 0
a=X-nat:0
m=audio 4000 RTP/AVP 96 120
c=IN IP4 192.168.101.30
b=TIAS:96000
a=rtcp:4001 IN IP4 192.168.101.30
a=sendrecv
a=rtpmap:96 speex/16000
a=rtpmap:120 telephone-event/16000
a=fmtp:120 0-16
a=ssrc:574766892 cname:5be3f8f676030d2b

--end msg--
13:00:18.665            pjsua_app.c  .........Call 0 state changed to CONNECTING
13:00:18.682     strm0x7121fc02cef8 !Resetting jitter buffer in stream playback start
13:00:18.705           pjsua_core.c !.RX 818 bytes Request msg ACK/cseq=18422 (rdata0x7121fc000b98) from UDP 172.22.0.21:5060:
ACK sip:001011234567892@192.168.101.30:5060;ob SIP/2.0
Via: SIP/2.0/UDP 172.22.0.21;branch=z9hG4bK74eb.b36da42952fb7a1126b73eb5419c2cd0.0
Via: SIP/2.0/UDP 172.22.0.20:6060;branch=z9hG4bK74eb.b01bb02bf574c8b6d03b411b7ecce170.0
Via: SIP/2.0/UDP 172.22.0.20:6060;branch=z9hG4bK74eb.d4740f448264f36e8f7fa47502b24ea0.0
Via: SIP/2.0/UDP 172.22.0.21;branch=z9hG4bK74eb.566c7d71753b1339c44c3bce2032d0a6.0
Via: SIP/2.0/UDP 192.168.101.31:5060;received=192.168.101.31;rport=5060;branch=z9hG4bKPjNBTnZpKeC6ea3V-tAIpafcmF9TFld-yR
Max-Forwards: 66
From: sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org;tag=w-80kOBbBU8x48da5YgS5memObfSM6U2
To: sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org;tag=hIHdSslj4K8oLOTucLND1m34Np-1sRzD
Call-ID: JyjjCuCEILH--GQ3m45gbVLZgrYOpPkd
CSeq: 18422 ACK
Content-Length:  0


--end msg--
13:00:18.706            pjsua_app.c  ...Call 0 state changed to CONFIRMED
13:00:19.302     strm0x7121fc02cef8 !VAD re-enabled
```
