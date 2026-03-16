# Authentication in the 5G + IMS Stack

## Two Domains, Two Databases

A subscriber in this stack is authenticated **twice**, by two completely independent systems, each with its own database and protocol:

| | 5G Core (Open5GS) | IMS (Kamailio + PyHSS) |
|---|---|---|
| **Database** | MongoDB | MySQL |
| **Protocol** | NAS / NGAP (5G-AKA via Milenage) | SIP / Diameter Cx (IMS-AKA or MD5 Digest) |
| **Triggered by** | UE attaching to the radio network | UE sending SIP REGISTER |
| **Queried by** | AUSF, UDM, UDR | I-CSCF, S-CSCF |
| **What it authorizes** | Radio attach, PDU session establishment | SIP registration, voice/video call routing |
| **Credentials stored** | IMSI, Ki, OPc, AMF, subscriber profile, APN/slice config | IMSI, Ki, OPc, AMF, SQN, MSISDN, S-CSCF assignment, iFC |

The same subscriber identity (IMSI) and the same cryptographic credentials (Ki, OPc) are provisioned in **both** databases. This is not redundancy — each database serves a different authentication domain at a different layer of the protocol stack.

## Why Two Separate Databases?

In a real operator network, these would typically be a single unified HSS, or a 5G UDM that also speaks Diameter Cx to the IMS. But in this open-source stack, Open5GS and Kamailio are separate projects developed independently, each with its own subscriber storage. The result is that provisioning must happen twice.

This is why `provision.sh` has two steps:

- **Step 1** writes to MongoDB (Open5GS) — so the UE can attach to the 5G core and establish PDU sessions
- **Step 2** writes to PyHSS (MySQL, via REST API) — so the UE can register with the IMS and make voice calls

## Authentication Flow

### Step 1: 5G Core Authentication (Radio Attach)

When a UE powers on and attaches to the network:

```
UE → gNB → AMF → AUSF → UDM → UDR (MongoDB)
                    │
                    └── 5G-AKA challenge/response using Ki + OPc (Milenage)
```

- The UDR retrieves the subscriber's Ki and OPc from MongoDB
- The AUSF generates an authentication vector and challenges the UE
- The UE proves it holds the correct Ki by computing the expected response
- On success: the UE is attached, and can establish PDU sessions (e.g., `internet` and `ims` APNs)

At this point the UE has IP connectivity through the core, but is **not yet registered for voice**.

### Step 2: IMS Authentication (SIP Registration)

Once the UE has an IMS PDU session (with an IP on the IMS APN, e.g., `192.168.101.x`), the SIP client registers with the IMS:

```
pjsua → P-CSCF → I-CSCF → PyHSS (Diameter UAR)
                     │
                     └── "Which S-CSCF should handle this subscriber?"

pjsua → P-CSCF → S-CSCF → PyHSS (Diameter MAR)
                     │
                     └── "Give me this subscriber's auth credentials"
                     └── S-CSCF challenges UE with Digest auth (MD5 in our test setup)

pjsua → P-CSCF → S-CSCF → PyHSS (Diameter SAR)
                     │
                     └── "Subscriber authenticated, store S-CSCF assignment"
```

- **I-CSCF** queries PyHSS via Diameter Cx (UAR — User Authorization Request) to locate the correct S-CSCF
- **S-CSCF** queries PyHSS via Diameter Cx (MAR — Multimedia Auth Request) to get credentials and generate a SIP Digest challenge
- The UE responds to the challenge, S-CSCF verifies, and sends SAR (Server Assignment Request) to record the registration
- On success: the UE is registered in the IMS and can make/receive voice and video calls

### The Full Picture

Both authentications must succeed for a VoNR call to work:

```
[5G Core Auth]                          [IMS Auth]
UE attaches to radio ──────────────►  UE gets IMS APN IP ──────────────►  SIP REGISTER
Ki/OPc checked by AUSF (MongoDB)       Ki/OPc checked by S-CSCF (PyHSS)
Result: PDU sessions up                 Result: SIP registered, can make calls
```

If Open5GS doesn't have the subscriber → the UE can't attach at all (no radio connectivity).
If PyHSS doesn't have the subscriber → the UE attaches and gets an IP, but SIP REGISTER is rejected (no voice).

## E2E Test Modification: MD5 Digest Instead of IMS-AKA

In production IMS, the S-CSCF uses **IMS-AKA** (a Milenage-based challenge derived from Ki/OPc) to authenticate SIP REGISTER. However, pjsua (our SIP test client) only supports standard **SIP Digest auth (MD5)**.

To work around this, the e2e test modifies two Kamailio configs:

| Config | Change | Why |
|--------|--------|-----|
| `pcscf.cfg` | `WITH_IPSEC` commented out | pjsua can't negotiate IPsec SAs with the P-CSCF |
| `scscf.cfg` | `REG_AUTH_DEFAULT_ALG` set to `"MD5"` | Downgrades auth from IMS-AKA to SIP Digest |

With MD5 Digest, the S-CSCF still queries PyHSS for the subscriber's credentials, but uses a simpler challenge mechanism that pjsua can respond to. The SIP password in this mode is set explicitly (via `SIP_PASSWORD` env var) rather than derived from Ki/OPc.
