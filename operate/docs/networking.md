# Network Architecture — 5G SA + IMS Stack

How the containers, subnets, tunnels, and routing fit together.

---

## Three Network Layers

The stack has three distinct network layers that traffic passes through. Understanding which layer you're on is critical for troubleshooting — a failure on the Docker bridge (Layer 1) looks very different from a failure inside a GTP tunnel (Layer 2).

```
┌──────────────────────────────────────────────────────────────────────┐
│ LAYER 1: Docker Bridge (172.22.0.0/24)                               │
│   All containers. NF-to-NF signaling: SBI, NGAP, PFCP, Diameter,    │
│   SIP between Kamailio nodes.                                        │
│                                                                       │
│ LAYER 2: GTP User Plane (192.168.100.0/24 + 192.168.101.0/24)       │
│   UE data plane. Exists inside GTP-U tunnels between UEs and UPF.    │
│   Two subnets: "internet" APN and "ims" APN.                        │
│                                                                       │
│ LAYER 3: UE Policy Routing                                            │
│   Inside each UE container. Routes traffic from the correct source   │
│   IP through the correct tunnel interface.                            │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Layer 1: Docker Bridge — `172.22.0.0/24`

Every container gets a fixed IP on a single Docker bridge network (`docker_open5gs_default`). All NF-to-NF communication runs here — SBI, Diameter, SIP between Kamailio nodes, PFCP, NGAP, and management traffic.

```
172.22.0.0/24 — Docker bridge network
│
├── Data Stores
│   ├── .2   mongo          (5G core subscriber store)
│   ├── .15  dns            (BIND9, IMS NAPTR/SRV records)
│   ├── .17  mysql          (IMS subscriber store)
│   └── .36  metrics        (Prometheus, scrapes NFs every 5s)
│
├── 5G Core (SBI on HTTP/2)
│   ├── .10  amf            (Access & Mobility Management)
│   ├── .7   smf            (Session Management)
│   ├── .8   upf            (User Plane Function — bridges to GTP)
│   ├── .12  nrf            (NF Repository / service discovery)
│   ├── .35  scp            (Service Communication Proxy)
│   ├── .11  ausf           (Authentication Server)
│   ├── .13  udm            (Unified Data Management)
│   ├── .14  udr            (Unified Data Repository)
│   └── .27  pcf            (Policy Control)
│
├── IMS (SIP + Diameter)
│   ├── .21  pcscf          (P-CSCF — SIP edge proxy, port 5060)
│   ├── .19  icscf          (I-CSCF — interrogating, port 4060)
│   ├── .20  scscf          (S-CSCF — serving/registrar, port 6060)
│   ├── .18  pyhss          (HSS — Diameter Cx, port 3868)
│   └── .16  rtpengine      (RTP media relay)
│
├── RAN
│   └── .23  nr_gnb         (UERANSIM gNB)
│
└── UEs (have BOTH Docker bridge AND tunnel IPs)
    ├── .50  e2e_ue1        (UERANSIM + pjsua)
    └── .51  e2e_ue2        (UERANSIM + pjsua)
```

### What runs on this subnet

| Protocol | Between | Port | Purpose |
|---|---|---|---|
| SBI (HTTP/2) | All core NFs ↔ NRF/SCP | 7777 | 5G service-based interface |
| NGAP | gNB ↔ AMF | 38412 | RAN control plane |
| PFCP | SMF ↔ UPF | 8805 | User plane session management |
| GTP-U | gNB ↔ UPF | 2152 | User data tunneling |
| SIP | P-CSCF ↔ I-CSCF ↔ S-CSCF | 4060/5060/6060 | IMS call signaling |
| Diameter | I-CSCF/S-CSCF ↔ PyHSS | 3868 | IMS subscriber queries (Cx) |
| Diameter | P-CSCF ↔ PCF | Rx | IMS QoS policy (N5) |
| HTTP | P-CSCF ↔ PCF | 7777 | N5 QoS via SBI |
| MongoDB | UDR/PCF ↔ mongo | 27017 | 5G subscriber data |
| MySQL | PyHSS/CSCFs ↔ mysql | 3306 | IMS subscriber data |
| DNS | CSCFs/PyHSS ↔ dns | 53 | IMS domain resolution |

All containers can reach each other directly on this subnet. No NAT, no firewalls.

---

## Layer 2: GTP User Plane — `192.168.100.0/24` and `192.168.101.0/24`

These subnets **do not exist on the Docker bridge**. They exist inside GTP-U tunnels between the UEs and the UPF. Each UE establishes two PDU sessions (one per APN), each getting its own tunnel interface and IP address.

### Two APNs, Two Subnets

```
"internet" APN — 192.168.100.0/24
  Purpose: General internet data (not used for voice)
  UPF interface: ogstun  (192.168.100.1)
  UE1 tunnel:    uesimtun1 (192.168.100.7)
  UE2 tunnel:    uesimtun1 (192.168.100.5)

"ims" APN — 192.168.101.0/24
  Purpose: IMS voice/video signaling and media (SIP + RTP)
  UPF interface: ogstun2 (192.168.101.1)
  UE1 tunnel:    uesimtun0 (192.168.101.7)
  UE2 tunnel:    uesimtun0 (192.168.101.5)
```

pjsua (the SIP client on each UE) binds to the **IMS APN** IP:
- UE1 pjsua: `192.168.101.7:5060` (UDP)
- UE2 pjsua: `192.168.101.5:5060` (UDP)

### How GTP tunnels work

The 192.168.x.x addresses are not directly routable on the Docker bridge. Traffic to/from these IPs must pass through GTP-U tunnels:

```
UE app writes to 192.168.101.7
         │
         ▼
    uesimtun0 (TUN device inside UE container)
         │
         ▼
    UERANSIM nr-ue process
         │ encapsulates in GTP-U header
         │ (src: 172.22.0.50, dst: 172.22.0.23, UDP port 2152)
         ▼
    Docker bridge (172.22.0.0/24)
         │
         ▼
    gNB (172.22.0.23)
         │ re-encapsulates GTP-U
         │ (src: 172.22.0.23, dst: 172.22.0.8, UDP port 2152)
         ▼
    Docker bridge
         │
         ▼
    UPF (172.22.0.8)
         │ decapsulates GTP-U
         │ inner packet: src=192.168.101.7, dst=172.22.0.21
         ▼
    ogstun2 interface (192.168.101.1/24)
         │ IP routing: dst 172.22.0.21 → via eth0
         ▼
    P-CSCF (172.22.0.21:5060)
```

The reverse path (P-CSCF → UE) works because the P-CSCF has static routes through the UPF:

```
P-CSCF routing table:
  172.22.0.0/24    → eth0 (direct, Docker bridge)
  192.168.100.0/24 → via 172.22.0.8 dev eth0    ← through UPF
  192.168.101.0/24 → via 172.22.0.8 dev eth0    ← through UPF
```

So when the P-CSCF sends a SIP INVITE to `192.168.101.5:5060` (UE2), the packet goes:

```
P-CSCF (172.22.0.21) → Docker bridge → UPF (172.22.0.8)
  → ogstun2 → GTP-U tunnel → gNB (172.22.0.23)
  → GTP-U tunnel → UE2 nr-ue → uesimtun0 → pjsua (192.168.101.5:5060)
```

### The UPF is the bridge between worlds

The UPF is the only container that has interfaces on **both** the Docker bridge and the tunnel subnets:

```
UPF network interfaces:
  eth0     172.22.0.8/24     ← Docker bridge (control + transport)
  ogstun   192.168.100.1/24  ← internet APN tunnel endpoint
  ogstun2  192.168.101.1/24  ← IMS APN tunnel endpoint
```

All traffic between 172.22.0.0/24 and 192.168.x.x passes through the UPF. If the UPF is down, no UE data plane traffic flows — even though the Docker bridge is fine.

---

## Layer 3: UE Policy Routing

Each UE container has three interfaces:
- `eth0` at `172.22.0.50` (Docker bridge — used by UERANSIM for NGAP/GTP signaling)
- `uesimtun0` at `192.168.101.x` (IMS APN — used by pjsua for SIP)
- `uesimtun1` at `192.168.100.x` (internet APN)

The challenge: when pjsua sends a SIP packet from `192.168.101.7`, it must go through `uesimtun0` (the IMS GTP tunnel), not through `eth0` (the Docker bridge). Linux policy routing handles this:

```
UE1 ip rule:
  from 192.168.101.7 → lookup table rt_uesimtun0 → default dev uesimtun0
  from 192.168.100.7 → lookup table rt_uesimtun1 → default dev uesimtun1
  from all           → lookup table main          → default via 172.22.0.1
```

This means:
- Traffic from `192.168.101.7` (IMS) always goes through the IMS GTP tunnel
- Traffic from `192.168.100.7` (internet) always goes through the internet GTP tunnel
- Traffic from `172.22.0.50` (Docker IP) goes directly on the Docker bridge

pjsua binds to `192.168.101.7:5060`, so all SIP traffic automatically takes the GTP tunnel path.

---

## The Complete Traffic Flow: UE1 Calls UE2

Here's every network hop when UE1 makes a VoNR call to UE2:

```
ORIGINATING SIDE (UE1 → IMS)
══════════════════════════════════════════════════════════

1. pjsua (192.168.101.7:5060) sends SIP INVITE
   │ src: 192.168.101.7  dst: 172.22.0.21 (P-CSCF)
   │ policy route: from 192.168.101.7 → uesimtun0
   ▼
2. uesimtun0 → UERANSIM nr-ue process
   │ encapsulate in GTP-U
   │ outer: src=172.22.0.50 dst=172.22.0.23 UDP:2152
   │ inner: src=192.168.101.7 dst=172.22.0.21 UDP:5060
   ▼
3. Docker bridge → gNB (172.22.0.23)
   │ forward GTP-U
   │ outer: src=172.22.0.23 dst=172.22.0.8 UDP:2152
   ▼
4. Docker bridge → UPF (172.22.0.8)
   │ decapsulate GTP-U on ogstun2
   │ route: dst 172.22.0.21 → via eth0
   ▼
5. Docker bridge → P-CSCF (172.22.0.21:5060)
   │ SIP INVITE enters IMS signaling plane
   │ From here, all SIP hops are on 172.22.0.0/24
   ▼

IMS SIGNALING (all on Docker bridge 172.22.0.0/24)
══════════════════════════════════════════════════════════

6. P-CSCF (172.22.0.21) → S-CSCF (172.22.0.20:6060)
   │ originating call processing, iFC evaluation
   ▼
7. S-CSCF → I-CSCF (172.22.0.19:4060)
   │ Diameter LIR to PyHSS: "which S-CSCF serves UE2?"
   ▼
8. I-CSCF → PyHSS (172.22.0.18:3868) [Diameter]
   │ LIR/LIA: returns S-CSCF address for UE2
   ▼
9. I-CSCF → S-CSCF (172.22.0.20:6060) [terminating]
   │ usrloc lookup: finds UE2 contact 192.168.101.5:5060
   ▼
10. S-CSCF → P-CSCF (172.22.0.21)
    │ forwards INVITE toward UE2's registered contact
    ▼

TERMINATING SIDE (IMS → UE2)
══════════════════════════════════════════════════════════

11. P-CSCF (172.22.0.21) sends INVITE to 192.168.101.5:5060
    │ route: 192.168.101.0/24 → via 172.22.0.8 (UPF)
    ▼
12. Docker bridge → UPF (172.22.0.8)
    │ receives on eth0, routes to ogstun2
    │ encapsulate in GTP-U toward UE2
    │ outer: src=172.22.0.8 dst=172.22.0.23 UDP:2152
    ▼
13. Docker bridge → gNB (172.22.0.23)
    │ forward GTP-U to UE2
    │ outer: src=172.22.0.23 dst=172.22.0.51 UDP:2152
    ▼
14. Docker bridge → UE2 container (172.22.0.51)
    │ UERANSIM nr-ue decapsulates GTP-U
    │ delivers to uesimtun0
    ▼
15. uesimtun0 → pjsua (192.168.101.5:5060)
    │ SIP INVITE received!
    │ UE2 rings, answers, RTP media flows
    ▼
    ☎️  Call connected
```

### Key insight

Steps 1-5 and 11-15 traverse the GTP tunnel (Layer 2). Steps 6-10 run entirely on the Docker bridge (Layer 1). The **first and last hops** (P-CSCF ↔ UE) are the only places where SIP traffic crosses between the two layers. This is why the `udp_mtu_try_proto` issue only affects UE delivery — it's the only leg where the P-CSCF sends SIP directly to a UE's tunnel IP.

---

## Where Things Break: Network Layer Failure Modes

| Failure | Layer | Symptom | How to check |
|---|---|---|---|
| Container down | 1 | NF unreachable, SIP/Diameter timeouts | `docker ps`, `get_network_status` |
| Docker bridge issue | 1 | All inter-NF communication fails | `docker exec pcscf ping 172.22.0.20` |
| GTP tunnel broken | 2 | UEs can't reach P-CSCF or vice versa, data plane dead | `docker exec pcscf ping 192.168.101.7`, Prometheus GTP counters = 0 |
| UPF down | 1+2 | Control plane OK but no user traffic | GTP packet counters = 0, sessions exist but no data |
| gNB signal lost | 2 | UE tunnel interfaces drop | UE logs: "signal lost", uesimtun TX/RX asymmetry |
| Transport mismatch | 2 | SIP sent via TCP, UE listens UDP only | `read_running_config(pcscf, "udp_mtu")`, `check_process_listeners(ue)` |
| Policy routing broken | 3 | UE sends SIP on eth0 instead of tunnel | `ip rule show` inside UE, check source IP of outgoing SIP |
| Static route missing | 1→2 | P-CSCF can't reach 192.168.x.x | `ip route show` inside pcscf, check for `via 172.22.0.8` |

---

## Configuration Reference

### .env subnet definitions

```bash
# Docker bridge (used by docker-compose)
TEST_NETWORK=172.22.0.0/24

# UE data plane subnets (assigned by SMF, terminated at UPF)
UE_IPV4_INTERNET=192.168.100.0/24    # "internet" APN → ogstun
UE_IPV4_IMS=192.168.101.0/24         # "ims" APN → ogstun2
```

### SMF session configuration (smf.yaml)

```yaml
session:
  - subnet: 192.168.100.0/24
    gateway: 192.168.100.1
    dnn: internet
  - subnet: 192.168.101.0/24
    gateway: 192.168.101.1
    dnn: ims
```

### UPF TUN interfaces (upf.yaml)

```yaml
upf:
  pfcp:
    - addr: 172.22.0.8       # PFCP on Docker bridge
  gtpu:
    - addr: 172.22.0.8       # GTP-U on Docker bridge
  session:
    - subnet: 192.168.100.0/24
      dev: ogstun              # internet APN
    - subnet: 192.168.101.0/24
      dev: ogstun2             # IMS APN
```

### P-CSCF static routes

These are configured in the P-CSCF container's init script to enable it to reach UEs through the UPF:

```
ip route add 192.168.100.0/24 via 172.22.0.8 dev eth0
ip route add 192.168.101.0/24 via 172.22.0.8 dev eth0
```

Without these routes, the P-CSCF would try to reach `192.168.101.x` via the default gateway (`172.22.0.1`), which doesn't know about the GTP subnets. The routes force traffic through the UPF, which can encapsulate it in GTP-U and deliver it to the UE.
