# RCA: IMS Registration Failed (408 Request Timeout)

**Date:** 2026-03-17
**Affected Components:** UERANSIM gNB, UPF, P-CSCF, I-CSCF, S-CSCF
**Affected UEs:** UE1 (001011234567891), UE2 (001011234567892)
**Symptom:** pjsua reports `SIP registration failed, status=408 (Request Timeout)` repeatedly
**Severity:** Critical — No IMS registration possible for any UE

---

## Summary

The IMS registration failure is caused by **two layered issues**:

1. **Primary (Data Plane):** The UERANSIM gNB's Radio Link Simulation (RLS) is unstable, breaking the GTP-U tunnel between the UE and UPF. SIP REGISTER packets from pjsua enter the `uesimtun1` TUN device but never reach the P-CSCF.

2. **Secondary (SIP Response Path):** Even when the GTP data plane was functional, the S-CSCF's SIP responses (401/200) eventually stopped reaching the I-CSCF, causing 408 timeouts at the P-CSCF transaction layer.

---

## Architecture & Data Flow

### IMS Registration Call Flow (Normal)

```
UE (pjsua)          P-CSCF           I-CSCF           S-CSCF           HSS (PyHSS)
    |                  |                |                 |                  |
    |--- REGISTER ---->|--- REGISTER -->|--- REGISTER --->|                  |
    |  (no auth)       |  (t_relay)     |  (UAR/UAA)      |--- MAR --------->|
    |                  |                |  (t_relay)      |<-- MAA ----------|
    |<-- 401 Challenge-|<-- 401 --------|<-- 401 ---------|  (auth vector)   |
    |                  |                |                 |                  |
    |--- REGISTER ---->|--- REGISTER -->|--- REGISTER --->|                  |
    |  (with auth)     |  (t_relay)     |  (cached SCSCF) |  (verify auth)   |
    |                  |                |  (t_relay)      |--- SAR --------->|
    |                  |                |                 |<-- SAA ----------|
    |<-- 200 OK -------|<-- 200 OK -----|<-- 200 OK ------|  (registered)    |
```

### Actual Data Path (Network Level)

```
UE Container                    gNB Container         UPF Container         P-CSCF Container
+--------------+               +-------------+       +-------------+       +----------------+
| pjsua        |               |             |       |             |       |                |
| bind:        |               |  UERANSIM   |       |  open5gs    |       |  Kamailio      |
| 192.168.101  |  GTP-U tunnel |  gNB        |  GTP  |  UPF        |  UDP  |  P-CSCF        |
| .10:5060     |====[RLS]=====>|  forward    |======>|  ogstun2    |------>|  172.22.0.21   |
|              |               |             |       |  192.168.   |       |  :5060         |
| uesimtun1    |               |             |       |  101.1/24   |       |                |
+--------------+               +-------------+       +-------------+       +----------------+

IP Routing on UE:
  Rule: from 192.168.101.10 lookup rt_uesimtun1
  Route: default dev uesimtun1 (ALL traffic from IMS IP goes through GTP tunnel)
```

---

## Layer 1: GTP-U Data Plane Broken (Primary Cause)

### What Happened

The UERANSIM gNB's Radio Link Simulation (RLS) layer lost connectivity to the UE processes. This broke the GTP-U data plane tunnel between the UE and UPF.

### Evidence

**gNB logs — continuous "signal lost" events:**
```
[2026-03-16 22:57:44.347] [rls] [debug] UE[15] signal lost
[2026-03-16 22:57:44.348] [rls] [debug] UE[16] signal lost
[2026-03-17 02:52:34.676] [rls] [debug] UE[15] signal lost
[2026-03-17 08:01:52.689] [rls] [debug] UE[15] signal lost
[2026-03-17 08:01:52.689] [rls] [debug] UE[16] signal lost
...
```
Signal loss events have been occurring since March 12.

**uesimtun1 interface stats — packets go in but don't come back:**
```
RX:  bytes packets errors dropped
     13010      20      0       0       # Only 20 packets EVER received
TX:  bytes packets errors dropped
   2056833    4088      0       0       # 4088 packets sent (pjsua retransmissions)
```

**tcpdump on P-CSCF — zero SIP packets from UE's IMS IP:**
```
$ docker exec pcscf tcpdump -i any -n "udp port 5060" -c 3 -v
# Sent test SIP from 192.168.101.10 → 172.22.0.21:5060
# Result: 0 packets captured, 0 packets received by filter
```

**tcpdump on UPF — zero GTP-U traffic:**
```
$ docker exec upf tcpdump -i any -n "host 192.168.101.10 or udp port 2152" -c 5 -v
# Result: 0 packets captured, 0 packets received by filter
```

**P-CSCF transaction stats — only 20 transactions ever processed:**
```
$ docker exec pcscf kamcmd tm.stats
current: 0       # No active transactions
total: 20        # Only 20 transactions in entire uptime (since Mar 13)
rpl_received: 40 # 40 replies received
4xx: 10          # 10 x 401 challenges
2xx: 10          # 10 x 200 OK
```

**P-CSCF IS alive (responds to direct SIP):**
```
$ docker exec pcscf kamcmd core.uptime
up_since: Fri Mar 13 11:27:13 2026
uptime: 349228
```
Sending an OPTIONS directly to the P-CSCF from within the container works. The P-CSCF process is healthy — it just never receives the UE's traffic.

### Root Cause Mechanism

```
1. UE's pjsua sends REGISTER from 192.168.101.10:5060 to 172.22.0.21:5060
2. Linux IP rule: "from 192.168.101.10 lookup rt_uesimtun1"
3. rt_uesimtun1 table: "default dev uesimtun1 scope link"
4. Packet enters uesimtun1 TUN device → GTP-U encapsulation
5. gNB should forward GTP-U to UPF, but RLS link is broken ("signal lost")
6. Packet is silently dropped
7. P-CSCF never sees the REGISTER
8. pjsua retransmits 5x (every 4 seconds), then reports 408 timeout
```

### Why pjsua Doesn't Use eth0 Directly

The UE container has both `eth0` (172.22.0.50, direct Docker network access to P-CSCF) and `uesimtun1` (192.168.101.10, IMS PDU session). pjsua binds to `192.168.101.10` because that's the IMS PDN IP assigned by the 5G core. The Linux policy routing forces ALL traffic from this source IP through the GTP tunnel — by design, since IMS traffic should traverse the mobile core for QoS, charging, and policy enforcement.

---

## Layer 2: SIP Response Path Issue (Secondary)

### What Happened

During the brief period when the GTP data plane was functional (March 13, ~15:27 to ~19:25), 10 full registration cycles succeeded (P-CSCF received 10x 401 and 10x 200 responses). But at some point, the S-CSCF's SIP responses stopped reaching the I-CSCF.

### Evidence

**S-CSCF correctly processes REGISTERs (CSeq 19752 example):**
```
19:25:14.199  REGISTER received at S-CSCF from 172.22.0.19:4060 (I-CSCF)
19:25:14.199  Auth: MD5 digest match confirmed
19:25:14.200  Auth succeeded, preparing SAR
19:25:14.200  Suspending SIP TM transaction with index [0] and label [0]
19:25:14.309  SAR callback: saa_return_code = 1 (success)
19:25:14.309  "SAR success - 200 response sent from module"
```
Total S-CSCF processing time: ~110ms — well within the I-CSCF's 5-second timeout (`t_set_fr(5000, 5000)`).

**I-CSCF never receives any replies:**
```
$ docker logs icscf | grep -i "reply\|response\|register_reply"
# Result: ZERO entries. The onreply_route[register_reply] never fires.
```
The I-CSCF's `xlog("L_DBG", "Enter register reply block")` is never triggered, meaning no SIP response from the S-CSCF ever reaches the I-CSCF's transaction module.

**P-CSCF also shows no reply processing after the initial 20 transactions:**
```
$ docker logs pcscf | grep -i "REGISTER_reply\|401\|200"
# Only timer warnings after March 13 19:25
```

### Suspicious Detail: Transaction Suspension

Every SAR-related transaction suspension at the S-CSCF logs the same values:
```
save(): Suspending SIP TM transaction with index [0] and label [0]
```
The `index [0] and label [0]` values appear for EVERY transaction, across all CSeqs and Call-IDs. These values are used by `t_continue()` to resume the correct transaction when the async Diameter callback fires. If these are incorrect, the resumed transaction may not properly send the SIP reply back through the Via headers.

### Possible Causes (Not Yet Confirmed)

1. **Kamailio async transaction bug**: The `t_suspend()`/`t_continue()` mechanism in the S-CSCF may not properly restore transaction state when `reg_send_reply_transactional()` is called from the CDP async callback.

2. **Via header routing failure**: The S-CSCF sends the reply to the address in the top Via header (I-CSCF at `172.22.0.19:4060`). If DNS resolution or UDP send fails silently, the reply is lost.

3. **GTP instability cascading effect**: The intermittent GTP signal loss may cause timing disruptions that affect the SIP transaction state across all IMS nodes.

---

## Investigation Methodology

### Step 1: Trace Forward Path (UE → P-CSCF → I-CSCF → S-CSCF)

Verified each node receives and processes the REGISTER:
- **P-CSCF**: Logs show `PCSCF: REGISTER sip:ims.mnc001.mcc001.3gppnetwork.org` with source `192.168.101.10:5060`
- **I-CSCF**: UAR/UAA to HSS succeeds, `I_scscf_select("0")` resolves S-CSCF URI
- **S-CSCF**: Full auth processing (MAR/MAA for challenge, SAR/SAA for registration), 200 OK generated

### Step 2: Trace Reverse Path (S-CSCF → I-CSCF → P-CSCF → UE)

Found the response path broken:
- **S-CSCF**: Claims to send reply (`reg_send_reply_transactional()` logs success)
- **I-CSCF**: `onreply_route[register_reply]` NEVER fires — zero response entries in logs
- **P-CSCF**: No 401/200/408 entries after initial 20 transactions

### Step 3: Verify Network Connectivity

- Direct UDP tests between containers: **works**
- Ping from UE to P-CSCF: **works** (via eth0/172.22.0.50)
- SIP from UE's uesimtun1 IP (192.168.101.10) to P-CSCF: **FAILS** (GTP broken)
- P-CSCF has route to 192.168.101.0/24 via UPF (172.22.0.8): **configured correctly**

### Step 4: Identify Data Plane Break

- Discovered IP routing policy forces IMS traffic through GTP tunnel
- Confirmed GTP tunnel is non-functional (zero packets at UPF)
- Identified gNB "signal lost" as the root cause of tunnel failure

---

## Timeline

| Time | Event |
|------|-------|
| Mar 12 17:58 | First gNB "signal lost" events for UEs |
| Mar 13 11:27 | P-CSCF Kamailio started (current instance) |
| Mar 13 11:27 | UPF sessions created: UE1=192.168.101.10, UE2=192.168.101.9 |
| Mar 13 15:27 | P-CSCF restarted; first successful REGISTER cycle |
| Mar 13 15:27-19:25 | 10 registration cycles succeed (20 transactions total) |
| Mar 13 19:25 | Last REGISTER processed by P-CSCF; SIP processing stops |
| Mar 13 19:25+ | GTP data plane fully broken; no more SIP reaches P-CSCF |
| Mar 16-17 | Continuous gNB signal loss events |
| Mar 17 16:22 | UE1 still retrying REGISTER every ~5 minutes, always 408 |

---

## Resolution

### Immediate Fix

Restart the UERANSIM stack to re-establish RLS links and GTP-U tunnels:
```bash
docker restart nr_gnb e2e_ue1 e2e_ue2
```

### Follow-Up Investigation

1. **gNB RLS stability**: Investigate why UERANSIM's Radio Link Simulation loses signal in the Docker/WSL2 environment. May need tuning of heartbeat intervals or RLS parameters.

2. **S-CSCF response path**: When the data plane is restored, monitor whether the S-CSCF → I-CSCF response path works consistently. If the `index [0] / label [0]` transaction suspension issue persists, investigate the Kamailio `ims_registrar_scscf` module's `save.c` transaction handling.

3. **UE resilience**: Consider whether pjsua should detect tunnel failure (e.g., by monitoring uesimtun1 RX counters or using ICE/STUN keepalives) and fall back or alert.

---

## Key Configurations

| Component | Listen Address | Key Settings |
|-----------|---------------|--------------|
| P-CSCF | `udp:172.22.0.21:5060` | `dns_try_naptr=off`, `use_dns_cache=off` |
| I-CSCF | `udp:172.22.0.19:4060` | `t_set_fr(5000, 5000)` (5s timeout) |
| S-CSCF | `udp:172.22.0.20:6060` | `dns_try_naptr=on`, `disable_tcp=yes`, `REG_AUTH_DEFAULT_ALG=MD5` |
| UPF | `172.22.0.8` | `ogstun2: 192.168.101.1/24` (IMS PDN) |
| UE1 | `192.168.101.10:5060` | IP rule routes IMS traffic via uesimtun1 |

---

## Lessons Learned

1. **Always verify the data plane first.** The SIP-level investigation consumed significant time before discovering that the underlying GTP-U tunnel was broken. In a mobile/IMS environment, the data plane (GTP tunnels, PDU sessions) should be verified before diving into SIP signaling analysis.

2. **IP routing policy can silently redirect traffic.** The UE had direct Docker network access to the P-CSCF via eth0, but Linux policy routing (`ip rule from 192.168.101.10 lookup rt_uesimtun1`) forced all SIP traffic through the GTP tunnel. This is correct behavior but makes troubleshooting non-obvious.

3. **"Interface UP" doesn't mean "tunnel working."** The uesimtun1 TUN interface remained UP with a valid IP even after the GTP tunnel broke. The only clue was the asymmetric TX/RX packet counters.

4. **Kamailio process alive != processing SIP.** The P-CSCF responded to `kamcmd` commands and showed healthy memory stats, but wasn't processing any SIP because no packets were arriving. The `tm.stats` command was the key diagnostic — showing that transaction creation had stopped entirely.

5. **Async Diameter callbacks in Kamailio need careful transaction management.** The S-CSCF's `t_suspend()`/`t_continue()` pattern for MAR/SAR processing is complex and the `index [0] / label [0]` values warrant investigation as a potential bug in transaction resumption.
