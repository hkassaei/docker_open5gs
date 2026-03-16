
## VoNR UE Log Walkthrough

### 1. 5G NR Registration (11:27:32 - 11:27:35)

The UE (UERANSIM simulated phone) powers on and searches for a network. It finds cell[1] on PLMN 001/01, selects it as suitable, and begins **initial registration** with the 5G core.

- **Authentication hiccup**: The first auth attempt fails with "SQN out of range" — this means the sequence number between the UE's SIM and the network was out of sync. The network sends a new challenge, and the second attempt succeeds. This is normal 5G-AKA resync behavior, not an error.
- **Security**: NAS integrity algorithm 2 (128-bit Snow3G) selected, ciphering algorithm 0 (null/no encryption).
- **Registration accepted** and completed successfully.

### 2. PDU Session Setup (11:27:35)

Immediately after registration, the UE requests **two PDU sessions** (data bearers):

| Session | TUN Interface | IP Address | Purpose |
|---------|--------------|------------|---------|
| PSI[1] | uesimtun0 | 192.168.100.10 | Internet APN (data) |
| PSI[2] | uesimtun1 | 192.168.101.10 | **IMS APN** (voice/SIP) |

Both establish successfully. The IMS bearer on 192.168.101.x is what the SIP client needs.

### 3. SIP/IMS Registration (11:27:38 - 11:27:39)

The pjsua SIP client starts on the IMS bearer IP and begins IMS registration:

1. **REGISTER #1** → Sent to the P-CSCF (172.22.0.21) as the outbound proxy.
2. **100 Trying** ← P-CSCF acknowledges.
3. **401 Unauthorized** ← The S-CSCF (Kamailio) challenges with a Digest auth nonce. This is the standard IMS authentication challenge — expected behavior.
4. **REGISTER #2** → UE resends with the MD5 Digest credentials filled in.
5. **100 Trying** ← P-CSCF acknowledges again.
6. **200 OK** ← **Registration successful.** The response includes:
   - **Contact** with expires=3240 (~54 min re-registration timer)
   - **P-Associated-URI**: Three public identities bound to this registration — the IMSI-based SIP URI, the MSISDN-based SIP URI (`sip:0100001111@...`), and a tel URI (`tel:0100001111`)
   - **Service-Route**: Future requests route through the S-CSCF at port 6060

### Notable Observations

- **Everything succeeded.** 5G registration, both PDU sessions, and IMS registration all completed without errors.
- **No call was placed** — this log only covers registration. The UE is now registered and ready to make/receive VoNR calls (pjsua is in auto-answer mode with null audio for E2E testing).
- **SQN resync on NAS** is benign — common in lab/test environments where the SIM sequence counter drifts.
- **NAS ciphering is disabled** (algorithm 0) — fine for a lab environment, would be a concern in production.
- **Total time**: ~7 seconds from UE power-on to fully IMS-registered. Clean and fast.

### Raw UE1 logs
```
Deploying component: 'ueransim-ue1'
============================================
  UERANSIM UE1 + pjsua E2E VoNR Test
  IMSI:       001011234567891
  MSISDN:     0100001111
  IMS Domain: ims.mnc001.mcc001.3gppnetwork.org
  P-CSCF:     172.22.0.21
============================================
Starting UERANSIM nr-ue...
Waiting for IMS APN bearer (192.168.101.x)...
UERANSIM v3.2.6
[2026-03-13 11:27:32.945] [nas] [[32minfo[m] UE switches to state [MM-DEREGISTERED/PLMN-SEARCH]
[2026-03-13 11:27:32.945] [rrc] [[36mdebug[m] New signal detected for cell[1], total [1] cells in coverage
[2026-03-13 11:27:32.946] [nas] [[32minfo[m] Selected plmn[001/01]
[2026-03-13 11:27:35.445] [rrc] [[32minfo[m] Selected cell plmn[001/01] tac[1] category[SUITABLE]
[2026-03-13 11:27:35.445] [nas] [[32minfo[m] UE switches to state [MM-DEREGISTERED/PS]
[2026-03-13 11:27:35.445] [nas] [[32minfo[m] UE switches to state [MM-DEREGISTERED/NORMAL-SERVICE]
[2026-03-13 11:27:35.445] [nas] [[36mdebug[m] Initial registration required due to [MM-DEREG-NORMAL-SERVICE]
[2026-03-13 11:27:35.445] [nas] [[36mdebug[m] UAC access attempt is allowed for identity[0], category[MO_sig]
[2026-03-13 11:27:35.445] [nas] [[36mdebug[m] Sending Initial Registration
[2026-03-13 11:27:35.445] [nas] [[32minfo[m] UE switches to state [MM-REGISTER-INITIATED]
[2026-03-13 11:27:35.445] [rrc] [[36mdebug[m] Sending RRC Setup Request
[2026-03-13 11:27:35.446] [rrc] [[32minfo[m] RRC connection established
[2026-03-13 11:27:35.446] [rrc] [[32minfo[m] UE switches to state [RRC-CONNECTED]
[2026-03-13 11:27:35.446] [nas] [[32minfo[m] UE switches to state [CM-CONNECTED]
[2026-03-13 11:27:35.460] [nas] [[36mdebug[m] Authentication Request received
[2026-03-13 11:27:35.460] [nas] [[36mdebug[m] Sending Authentication Failure due to SQN out of range
[2026-03-13 11:27:35.467] [nas] [[36mdebug[m] Authentication Request received
[2026-03-13 11:27:35.473] [nas] [[36mdebug[m] Security Mode Command received
[2026-03-13 11:27:35.473] [nas] [[36mdebug[m] Selected integrity[2] ciphering[0]
[2026-03-13 11:27:35.485] [nas] [[36mdebug[m] Registration accept received
[2026-03-13 11:27:35.485] [nas] [[32minfo[m] UE switches to state [MM-REGISTERED/NORMAL-SERVICE]
[2026-03-13 11:27:35.485] [nas] [[36mdebug[m] Sending Registration Complete
[2026-03-13 11:27:35.485] [nas] [[32minfo[m] Initial Registration is successful
[2026-03-13 11:27:35.485] [nas] [[36mdebug[m] Sending PDU Session Establishment Request
[2026-03-13 11:27:35.485] [nas] [[36mdebug[m] UAC access attempt is allowed for identity[0], category[MO_sig]
[2026-03-13 11:27:35.485] [nas] [[36mdebug[m] Sending PDU Session Establishment Request
[2026-03-13 11:27:35.485] [nas] [[36mdebug[m] UAC access attempt is allowed for identity[0], category[MO_sig]
[2026-03-13 11:27:35.690] [nas] [[36mdebug[m] Configuration Update Command received
[2026-03-13 11:27:35.711] [nas] [[36mdebug[m] PDU Session Establishment Accept received
[2026-03-13 11:27:35.711] [nas] [[32minfo[m] PDU Session establishment is successful PSI[1]
[2026-03-13 11:27:35.712] [nas] [[36mdebug[m] PDU Session Establishment Accept received
[2026-03-13 11:27:35.712] [nas] [[32minfo[m] PDU Session establishment is successful PSI[2]
[2026-03-13 11:27:35.731] [app] [[32minfo[m] Connection setup for PDU session[1] is successful, TUN interface[uesimtun0, 192.168.100.10] is up.
[2026-03-13 11:27:35.741] [app] [[32minfo[m] Connection setup for PDU session[2] is successful, TUN interface[uesimtun1, 192.168.101.10] is up.
IMS bearer established with IP: 192.168.101.10
Starting pjsua on IMS bearer (192.168.101.10)...
nr-ue PID: 20, pjsua PID: 64
============================================
  pjsua SIP Client for E2E Voice Testing
============================================
  SIP User:     sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org
  Registrar:    sip:ims.mnc001.mcc001.3gppnetwork.org
  Outbound:     sip:172.22.0.21:5060;transport=udp;lr
  Auto-answer:  yes
  Null audio:   yes
============================================
Waiting for IMS APN TUN interface (192.168.101.x)...
IMS TUN interface is up with IP: 192.168.101.10
Starting pjsua with bound address: 192.168.101.10
Command pipe: /tmp/pjsua_cmd
11:27:38.985           pjsua_core.c  SIP UDP socket reachable at 192.168.101.10:5060
11:27:38.985      udp0x5aa4e3c74f70  SIP UDP transport started, published address is 192.168.101.10:5060
11:27:38.985            pjsua_acc.c  Adding account: id=<sip:192.168.101.10:5060>
11:27:38.985            pjsua_acc.c  Modifying account 0
11:27:38.985            pjsua_acc.c  Acc 0: setting online status to 1..
11:27:38.985            pjsua_acc.c  Adding account: id=sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org
REGISTER sip:ims.mnc001.mcc001.3gppnetwork.org SIP/2.0

Via: SIP/2.0/UDP 192.168.101.10:5060;rport;branch=z9hG4bKPjtitiZ0xOBXfvaa59l82AkQ2iU0NpN-9L

Route: <sip:172.22.0.21:5060;transport=udp;lr>

Max-Forwards: 70

From: <sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org>;tag=X5HoCYN7qm7VPAJxJeg7twjV8i2cjR3D

To: <sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org>

Call-ID: ZExVDFnZRZzMoL9xWsmOYPKBQSS1Ks-w

CSeq: 19743 REGISTER

User-Agent: PJSUA v2.14.1 Linux-6.6.87.2/x86_64/glibc-2.35

Contact: <sip:001011234567891@192.168.101.10:5060;ob>

Expires: 3600

Allow: PRACK, INVITE, ACK, BYE, CANCEL, UPDATE, INFO, SUBSCRIBE, NOTIFY, REFER, MESSAGE, OPTIONS

Content-Length:  0

--end msg--
11:27:38.986            pjsua_acc.c  Acc 1: setting online status to 1..
11:27:38.986            pjsua_aud.c  Setting null sound device..
11:27:38.987           pjsua_core.c  PJSUA state changed: INIT --> STARTING
11:27:38.987                 main.c  Ready: Success
Account list:
  [ 0] <sip:192.168.101.10:5060>: does not register
       Online status: Online
 *[ 1] sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org: 100/In Progress (expires=0)
       Online status: Online
+=============================================================================+
|       Call Commands:         |   Buddy, IM & Presence:  |     Account:      |
|                              |                          |                   |
|  m  Make new call            | +b  Add new buddy        | +a  Add new accnt.|
|  M  Make multiple calls      | -b  Delete buddy         | -a  Delete accnt. |
|  a  Answer call              |  i  Send IM              | !a  Modify accnt. |
|  h  Hangup call  (ha=all)    |  s  Subscribe presence   | rr  (Re-)register |
|  H  Hold call                |  u  Unsubscribe presence | ru  Unregister    |
|  v  re-inVite (release hold) |  t  Toggle online status |  >  Cycle next ac.|
|  U  send UPDATE              |  T  Set online status    |  <  Cycle prev ac.|
| ],[ Select next/prev call    +--------------------------+-------------------+
|  x  Xfer call                |      Media Commands:     |  Status & Config: |
|  X  Xfer with Replaces       |                          |                   |
|  #  Send RFC 2833 DTMF       | cl  List ports           |  d  Dump status   |
|  *  Send DTMF with INFO      | cc  Connect port         | dd  Dump detailed |
| dq  Dump curr. call quality  | cd  Disconnect port      | dc  Dump config   |
|                              |  V  Adjust audio Volume  |  f  Save config   |
|  S  Send arbitrary REQUEST   | Cp  Codec priorities     |                   |
+-----------------------------------------------------------------------------+
|  q  QUIT      L  ReLoad       I  IP change     n  detect NAT type           |
|  sleep MS     echo [0|1|txt]                                                |
+=============================================================================+
You have 0 active call
SIP/2.0 100 Trying

Via: SIP/2.0/UDP 192.168.101.10:5060;rport=5060;received=192.168.101.10;branch=z9hG4bKPjtitiZ0xOBXfvaa59l82AkQ2iU0NpN-9L

From: <sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org>;tag=X5HoCYN7qm7VPAJxJeg7twjV8i2cjR3D

To: <sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org>

Call-ID: ZExVDFnZRZzMoL9xWsmOYPKBQSS1Ks-w

CSeq: 19743 REGISTER

Server: TelcoSuite Proxy-CSCF

Content-Length: 0

--end msg--
SIP/2.0 401 Unauthorized - Challenging the UE

Via: SIP/2.0/UDP 192.168.101.10:5060;received=192.168.101.10;rport=5060;branch=z9hG4bKPjtitiZ0xOBXfvaa59l82AkQ2iU0NpN-9L

From: <sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org>;tag=X5HoCYN7qm7VPAJxJeg7twjV8i2cjR3D

To: <sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org>;tag=4d2b7af309c0e63b4f73900cc6bd5790-6e4c573e

Call-ID: ZExVDFnZRZzMoL9xWsmOYPKBQSS1Ks-w

CSeq: 19743 REGISTER

WWW-Authenticate: Digest realm="ims.mnc001.mcc001.3gppnetwork.org", nonce="0f6479f1853246f4ba9e80872ced1cd4", algorithm=MD5, qop="auth"

Path: <sip:term@pcscf.ims.mnc001.mcc001.3gppnetwork.org;lr>

Server: Kamailio S-CSCF

Content-Length: 0

--end msg--
REGISTER sip:ims.mnc001.mcc001.3gppnetwork.org SIP/2.0

Via: SIP/2.0/UDP 192.168.101.10:5060;rport;branch=z9hG4bKPj2YhLJwZQOkGm-nxs8orR6BgH-fgA1Q5f

Route: <sip:172.22.0.21:5060;transport=udp;lr>

Max-Forwards: 70

From: <sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org>;tag=X5HoCYN7qm7VPAJxJeg7twjV8i2cjR3D

To: <sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org>

Call-ID: ZExVDFnZRZzMoL9xWsmOYPKBQSS1Ks-w

CSeq: 19744 REGISTER

User-Agent: PJSUA v2.14.1 Linux-6.6.87.2/x86_64/glibc-2.35

Contact: <sip:001011234567891@192.168.101.10:5060;ob>

Expires: 3600

Allow: PRACK, INVITE, ACK, BYE, CANCEL, UPDATE, INFO, SUBSCRIBE, NOTIFY, REFER, MESSAGE, OPTIONS

Authorization: Digest username="001011234567891", realm="ims.mnc001.mcc001.3gppnetwork.org", nonce="0f6479f1853246f4ba9e80872ced1cd4", uri="sip:ims.mnc001.mcc001.3gppnetwork.org", response="ad92b421959a8e4c5e7c07a2d18a0502", algorithm=MD5, cnonce="7ibQ6KXMaxUzX0YZKIdZFZjZwfvUttvy", qop=auth, nc=00000001

Content-Length:  0

--end msg--
SIP/2.0 100 Trying

Via: SIP/2.0/UDP 192.168.101.10:5060;rport=5060;received=192.168.101.10;branch=z9hG4bKPj2YhLJwZQOkGm-nxs8orR6BgH-fgA1Q5f

From: <sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org>;tag=X5HoCYN7qm7VPAJxJeg7twjV8i2cjR3D

To: <sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org>

Call-ID: ZExVDFnZRZzMoL9xWsmOYPKBQSS1Ks-w

CSeq: 19744 REGISTER

Server: TelcoSuite Proxy-CSCF

Content-Length: 0

--end msg--
SIP/2.0 200 OK

Via: SIP/2.0/UDP 192.168.101.10:5060;received=192.168.101.10;rport=5060;branch=z9hG4bKPj2YhLJwZQOkGm-nxs8orR6BgH-fgA1Q5f

From: <sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org>;tag=X5HoCYN7qm7VPAJxJeg7twjV8i2cjR3D

To: <sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org>;tag=4d2b7af309c0e63b4f73900cc6bd5790-a4ca573e

Call-ID: ZExVDFnZRZzMoL9xWsmOYPKBQSS1Ks-w

CSeq: 19744 REGISTER

Contact: <sip:001011234567891@192.168.101.10:5060;alias=192.168.101.10~5060~1;ob>;expires=3240

Path: <sip:term@pcscf.ims.mnc001.mcc001.3gppnetwork.org;lr>

P-Associated-URI: <sip:0100001111@ims.mnc001.mcc001.3gppnetwork.org>, <tel:0100001111>, <sip:001011234567891@ims.mnc001.mcc001.3gppnetwork.org>

Service-Route: <sip:orig@scscf.ims.mnc001.mcc001.3gppnetwork.org:6060;lr>

Server: Kamailio S-CSCF

Content-Length: 0

--end msg--
11:27:39.987            pjsua_aud.c  Closing sound device after idle for 1 second(s)
```



## VoNR UE2 Log Walkthrough

### 1. 5G NR Registration (11:27:32–11:27:33)

The UE (IMSI `001011234567892`) powers on and searches for a network. It finds cell[1] on PLMN `001/01`, deems it suitable, and kicks off **Initial Registration**.

- **RRC connection** established instantly — the UE is now connected at the radio layer.
- **Authentication** hits a minor snag: the first attempt fails with **"SQN out of range"** — the UE's sequence number was out of sync with the network. This is normal; the network resynchronizes and sends a second Authentication Request, which succeeds.
- **Security Mode** is negotiated: integrity algorithm 2 (Snow3G), no ciphering (0). No encryption on NAS — worth noting if this is meant to be a production-like setup.
- **Registration Accept** received — the UE is now registered on the 5G core.

### 2. PDU Session Setup (11:27:33)

Immediately after registration, the UE requests **two PDU sessions** simultaneously:

| Session | TUN Interface | IP Address | Purpose |
|---------|--------------|------------|---------|
| PSI[1] | `uesimtun0` | `192.168.100.9` | Default internet bearer |
| PSI[2] | `uesimtun1` | `192.168.101.9` | **IMS bearer** (for VoNR) |

Both succeed. The IMS bearer on `192.168.101.9` is the one that will carry SIP/voice traffic.

### 3. SIP/IMS Registration (11:27:37–11:27:38)

pjsua (SIP client) starts up bound to the IMS bearer IP and sends a **SIP REGISTER** to the IMS domain via the P-CSCF (`172.22.0.21`).

- **First REGISTER** → gets `401 Unauthorized` with a Digest challenge from the S-CSCF (Kamailio). This is the expected IMS authentication handshake, not an error.
- **Second REGISTER** → includes the Digest `Authorization` header with the computed response. The S-CSCF replies **200 OK**.

The 200 OK confirms:
- **Registration expires** in 3240 seconds (~54 minutes).
- **P-Associated-URI** maps this subscriber to three identities: the IMSI-based SIP URI, `sip:0100002222@...`, and `tel:0100002222` — so the UE can be reached by phone number.
- **Service-Route** is set through the S-CSCF (`scscf...:6060`) for future originating calls.

### Summary

Everything succeeded cleanly:

- **5G registration** — done (with a routine SQN resync)
- **Dual PDU sessions** — internet + IMS, both up
- **IMS/SIP registration** — authenticated and registered via P-CSCF → S-CSCF

The UE is now fully registered for VoNR and ready to make/receive calls. No errors, no retries beyond the expected authentication challenges. The SQN resync on the NAS side and the 401 challenge on the SIP side are both standard first-contact behaviors — not problems.

**One thing to watch:** NAS ciphering is disabled (algorithm 0). Fine for a lab/test environment, but would be a flag in production.

### Raw UE2 logs

```
Deploying component: 'ueransim-ue2'
============================================
  UERANSIM UE2 + pjsua E2E VoNR Test
  IMSI:       001011234567892
  MSISDN:     0100002222
  IMS Domain: ims.mnc001.mcc001.3gppnetwork.org
  P-CSCF:     172.22.0.21
============================================
Starting UERANSIM nr-ue...
Waiting for IMS APN bearer (192.168.101.x)...
UERANSIM v3.2.6
[2026-03-13 11:27:32.945] [nas] [[32minfo[m] UE switches to state [MM-DEREGISTERED/PLMN-SEARCH]
[2026-03-13 11:27:32.946] [rrc] [[36mdebug[m] New signal detected for cell[1], total [1] cells in coverage
[2026-03-13 11:27:32.946] [nas] [[32minfo[m] Selected plmn[001/01]
[2026-03-13 11:27:32.946] [rrc] [[32minfo[m] Selected cell plmn[001/01] tac[1] category[SUITABLE]
[2026-03-13 11:27:32.946] [nas] [[32minfo[m] UE switches to state [MM-DEREGISTERED/PS]
[2026-03-13 11:27:32.946] [nas] [[32minfo[m] UE switches to state [MM-DEREGISTERED/NORMAL-SERVICE]
[2026-03-13 11:27:32.946] [nas] [[36mdebug[m] Initial registration required due to [MM-DEREG-NORMAL-SERVICE]
[2026-03-13 11:27:32.947] [nas] [[36mdebug[m] UAC access attempt is allowed for identity[0], category[MO_sig]
[2026-03-13 11:27:32.947] [nas] [[36mdebug[m] Sending Initial Registration
[2026-03-13 11:27:32.947] [nas] [[32minfo[m] UE switches to state [MM-REGISTER-INITIATED]
[2026-03-13 11:27:32.947] [rrc] [[36mdebug[m] Sending RRC Setup Request
[2026-03-13 11:27:32.949] [rrc] [[32minfo[m] RRC connection established
[2026-03-13 11:27:32.949] [rrc] [[32minfo[m] UE switches to state [RRC-CONNECTED]
[2026-03-13 11:27:32.949] [nas] [[32minfo[m] UE switches to state [CM-CONNECTED]
[2026-03-13 11:27:32.984] [nas] [[36mdebug[m] Authentication Request received
[2026-03-13 11:27:32.984] [nas] [[36mdebug[m] Sending Authentication Failure due to SQN out of range
[2026-03-13 11:27:32.992] [nas] [[36mdebug[m] Authentication Request received
[2026-03-13 11:27:33.000] [nas] [[36mdebug[m] Security Mode Command received
[2026-03-13 11:27:33.000] [nas] [[36mdebug[m] Selected integrity[2] ciphering[0]
[2026-03-13 11:27:33.020] [nas] [[36mdebug[m] Registration accept received
[2026-03-13 11:27:33.020] [nas] [[32minfo[m] UE switches to state [MM-REGISTERED/NORMAL-SERVICE]
[2026-03-13 11:27:33.020] [nas] [[36mdebug[m] Sending Registration Complete
[2026-03-13 11:27:33.020] [nas] [[32minfo[m] Initial Registration is successful
[2026-03-13 11:27:33.020] [nas] [[36mdebug[m] Sending PDU Session Establishment Request
[2026-03-13 11:27:33.020] [nas] [[36mdebug[m] UAC access attempt is allowed for identity[0], category[MO_sig]
[2026-03-13 11:27:33.020] [nas] [[36mdebug[m] Sending PDU Session Establishment Request
[2026-03-13 11:27:33.020] [nas] [[36mdebug[m] UAC access attempt is allowed for identity[0], category[MO_sig]
[2026-03-13 11:27:33.227] [nas] [[36mdebug[m] Configuration Update Command received
[2026-03-13 11:27:33.254] [nas] [[36mdebug[m] PDU Session Establishment Accept received
[2026-03-13 11:27:33.254] [nas] [[32minfo[m] PDU Session establishment is successful PSI[1]
[2026-03-13 11:27:33.256] [nas] [[36mdebug[m] PDU Session Establishment Accept received
[2026-03-13 11:27:33.256] [nas] [[32minfo[m] PDU Session establishment is successful PSI[2]
[2026-03-13 11:27:33.270] [app] [[32minfo[m] Connection setup for PDU session[1] is successful, TUN interface[uesimtun0, 192.168.100.9] is up.
[2026-03-13 11:27:33.278] [app] [[32minfo[m] Connection setup for PDU session[2] is successful, TUN interface[uesimtun1, 192.168.101.9] is up.
IMS bearer established with IP: 192.168.101.9
Starting pjsua on IMS bearer (192.168.101.9)...
nr-ue PID: 19, pjsua PID: 58
============================================
  pjsua SIP Client for E2E Voice Testing
============================================
  SIP User:     sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org
  Registrar:    sip:ims.mnc001.mcc001.3gppnetwork.org
  Outbound:     sip:172.22.0.21:5060;transport=udp;lr
  Auto-answer:  yes
  Null audio:   yes
============================================
Waiting for IMS APN TUN interface (192.168.101.x)...
IMS TUN interface is up with IP: 192.168.101.9
Starting pjsua with bound address: 192.168.101.9
Command pipe: /tmp/pjsua_cmd
11:27:37.001           pjsua_core.c  SIP UDP socket reachable at 192.168.101.9:5060
11:27:37.001      udp0x5b4597b7bf70  SIP UDP transport started, published address is 192.168.101.9:5060
11:27:37.001            pjsua_acc.c  Adding account: id=<sip:192.168.101.9:5060>
11:27:37.002            pjsua_acc.c  Modifying account 0
11:27:37.002            pjsua_acc.c  Acc 0: setting online status to 1..
11:27:37.002            pjsua_acc.c  Adding account: id=sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org
REGISTER sip:ims.mnc001.mcc001.3gppnetwork.org SIP/2.0

Via: SIP/2.0/UDP 192.168.101.9:5060;rport;branch=z9hG4bKPjWHc4eW1l87DozrcJQPVWTKD1mgRXPJvV

Route: <sip:172.22.0.21:5060;transport=udp;lr>

Max-Forwards: 70

From: <sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org>;tag=H-KEZJEx-DxJysgy0kPFaLQrFSjgGCgV

To: <sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org>

Call-ID: yr1R3nP7lM6yOnvEr9bfNDtgvyGTpPJi

CSeq: 36261 REGISTER

User-Agent: PJSUA v2.14.1 Linux-6.6.87.2/x86_64/glibc-2.35

Contact: <sip:001011234567892@192.168.101.9:5060;ob>

Expires: 3600

Allow: PRACK, INVITE, ACK, BYE, CANCEL, UPDATE, INFO, SUBSCRIBE, NOTIFY, REFER, MESSAGE, OPTIONS

Content-Length:  0

--end msg--
11:27:37.002            pjsua_acc.c  Acc 1: setting online status to 1..
11:27:37.002            pjsua_aud.c  Setting null sound device..
11:27:37.003           pjsua_core.c  PJSUA state changed: INIT --> STARTING
11:27:37.003                 main.c  Ready: Success
Account list:
  [ 0] <sip:192.168.101.9:5060>: does not register
       Online status: Online
 *[ 1] sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org: 100/In Progress (expires=0)
       Online status: Online
+=============================================================================+
|       Call Commands:         |   Buddy, IM & Presence:  |     Account:      |
|                              |                          |                   |
|  m  Make new call            | +b  Add new buddy        | +a  Add new accnt.|
|  M  Make multiple calls      | -b  Delete buddy         | -a  Delete accnt. |
|  a  Answer call              |  i  Send IM              | !a  Modify accnt. |
|  h  Hangup call  (ha=all)    |  s  Subscribe presence   | rr  (Re-)register |
|  H  Hold call                |  u  Unsubscribe presence | ru  Unregister    |
|  v  re-inVite (release hold) |  t  Toggle online status |  >  Cycle next ac.|
|  U  send UPDATE              |  T  Set online status    |  <  Cycle prev ac.|
| ],[ Select next/prev call    +--------------------------+-------------------+
|  x  Xfer call                |      Media Commands:     |  Status & Config: |
|  X  Xfer with Replaces       |                          |                   |
|  #  Send RFC 2833 DTMF       | cl  List ports           |  d  Dump status   |
|  *  Send DTMF with INFO      | cc  Connect port         | dd  Dump detailed |
| dq  Dump curr. call quality  | cd  Disconnect port      | dc  Dump config   |
|                              |  V  Adjust audio Volume  |  f  Save config   |
|  S  Send arbitrary REQUEST   | Cp  Codec priorities     |                   |
+-----------------------------------------------------------------------------+
|  q  QUIT      L  ReLoad       I  IP change     n  detect NAT type           |
|  sleep MS     echo [0|1|txt]                                                |
+=============================================================================+
You have 0 active call
SIP/2.0 100 Trying

Via: SIP/2.0/UDP 192.168.101.9:5060;rport=5060;received=192.168.101.9;branch=z9hG4bKPjWHc4eW1l87DozrcJQPVWTKD1mgRXPJvV

From: <sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org>;tag=H-KEZJEx-DxJysgy0kPFaLQrFSjgGCgV

To: <sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org>

Call-ID: yr1R3nP7lM6yOnvEr9bfNDtgvyGTpPJi

CSeq: 36261 REGISTER

Server: TelcoSuite Proxy-CSCF

Content-Length: 0

--end msg--
SIP/2.0 401 Unauthorized - Challenging the UE

Via: SIP/2.0/UDP 192.168.101.9:5060;received=192.168.101.9;rport=5060;branch=z9hG4bKPjWHc4eW1l87DozrcJQPVWTKD1mgRXPJvV

From: <sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org>;tag=H-KEZJEx-DxJysgy0kPFaLQrFSjgGCgV

To: <sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org>;tag=4d2b7af309c0e63b4f73900cc6bd5790-372cc98b

Call-ID: yr1R3nP7lM6yOnvEr9bfNDtgvyGTpPJi

CSeq: 36261 REGISTER

WWW-Authenticate: Digest realm="ims.mnc001.mcc001.3gppnetwork.org", nonce="8f5032548a7b41eba0de9e72f857af55", algorithm=MD5, qop="auth"

Path: <sip:term@pcscf.ims.mnc001.mcc001.3gppnetwork.org;lr>

Server: Kamailio S-CSCF

Content-Length: 0

--end msg--
REGISTER sip:ims.mnc001.mcc001.3gppnetwork.org SIP/2.0

Via: SIP/2.0/UDP 192.168.101.9:5060;rport;branch=z9hG4bKPj.S1jF21q4DOsn1uuaZhIRy49ZuZCMYxS

Route: <sip:172.22.0.21:5060;transport=udp;lr>

Max-Forwards: 70

From: <sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org>;tag=H-KEZJEx-DxJysgy0kPFaLQrFSjgGCgV

To: <sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org>

Call-ID: yr1R3nP7lM6yOnvEr9bfNDtgvyGTpPJi

CSeq: 36262 REGISTER

User-Agent: PJSUA v2.14.1 Linux-6.6.87.2/x86_64/glibc-2.35

Contact: <sip:001011234567892@192.168.101.9:5060;ob>

Expires: 3600

Allow: PRACK, INVITE, ACK, BYE, CANCEL, UPDATE, INFO, SUBSCRIBE, NOTIFY, REFER, MESSAGE, OPTIONS

Authorization: Digest username="001011234567892", realm="ims.mnc001.mcc001.3gppnetwork.org", nonce="8f5032548a7b41eba0de9e72f857af55", uri="sip:ims.mnc001.mcc001.3gppnetwork.org", response="3fdaf81bed20a6310c4c5c4cd7e56b09", algorithm=MD5, cnonce="oph6cVVOkwWvTAPfmuekbYLskbgh7IH", qop=auth, nc=00000001

Content-Length:  0

--end msg--
SIP/2.0 100 Trying

Via: SIP/2.0/UDP 192.168.101.9:5060;rport=5060;received=192.168.101.9;branch=z9hG4bKPj.S1jF21q4DOsn1uuaZhIRy49ZuZCMYxS

From: <sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org>;tag=H-KEZJEx-DxJysgy0kPFaLQrFSjgGCgV

To: <sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org>

Call-ID: yr1R3nP7lM6yOnvEr9bfNDtgvyGTpPJi

CSeq: 36262 REGISTER

Server: TelcoSuite Proxy-CSCF

Content-Length: 0

--end msg--
SIP/2.0 200 OK

Via: SIP/2.0/UDP 192.168.101.9:5060;received=192.168.101.9;rport=5060;branch=z9hG4bKPj.S1jF21q4DOsn1uuaZhIRy49ZuZCMYxS

From: <sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org>;tag=H-KEZJEx-DxJysgy0kPFaLQrFSjgGCgV

To: <sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org>;tag=4d2b7af309c0e63b4f73900cc6bd5790-adf5c98b

Call-ID: yr1R3nP7lM6yOnvEr9bfNDtgvyGTpPJi

CSeq: 36262 REGISTER

Contact: <sip:001011234567892@192.168.101.9:5060;alias=192.168.101.9~5060~1;ob>;expires=3240

Path: <sip:term@pcscf.ims.mnc001.mcc001.3gppnetwork.org;lr>

P-Associated-URI: <sip:0100002222@ims.mnc001.mcc001.3gppnetwork.org>, <tel:0100002222>, <sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org>

Service-Route: <sip:orig@scscf.ims.mnc001.mcc001.3gppnetwork.org:6060;lr>

Server: Kamailio S-CSCF

Content-Length: 0

--end msg--
11:27:38.003            pjsua_aud.c  Closing sound device after idle for 1 second(s)
```