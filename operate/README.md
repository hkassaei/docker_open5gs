# E2E VoNR Voice Test

End-to-end voice call testing using UERANSIM (5G UE + gNB) with pjsua (PJSIP) for SIP/voice, and Kamailio IMS authentication relaxed from IMS-AKA to SIP Digest auth.

## Directory Structure

```
operate/
├── README.md                        # This file
├── e2e.env                          # Test subscriber credentials (UE1, UE2)
├── e2e-vonr.yaml                    # Docker Compose for two UERANSIM UEs with pjsua
├── ueransim/
│   ├── Dockerfile                   # Extends docker_ueransim with pjsua
│   ├── pjsua_entrypoint.sh         # pjsua startup: waits for IMS TUN, registers with P-CSCF
│   ├── ueransim_image_init.sh      # Container entrypoint dispatcher
│   ├── ueransim-ue1.yaml           # UE1 config (dual APN: internet + ims)
│   ├── ueransim-ue2.yaml           # UE2 config (dual APN: internet + ims)
│   ├── ueransim-ue1_init.sh        # UE1 init: starts nr-ue, waits for IMS bearer, starts pjsua
│   └── ueransim-ue2_init.sh        # UE2 init: same for UE2
├── kamailio/
│   ├── pcscf/pcscf.cfg            # P-CSCF config with IPsec DISABLED
│   └── scscf/scscf.cfg            # S-CSCF config with MD5 auth (not IMS-AKA)
└── scripts/
    ├── build.sh                    # Build docker_ueransim_pjsua image
    ├── provision.sh                # Provision test subscribers (Open5GS + PyHSS)
    ├── run-e2e-vonr.sh             # Full VoNR test orchestrator
    └── teardown.sh                 # Clean up and restore original configs
```

## Quick Start

```bash
# 0. Build base images (one-time, takes a while)
docker build -t docker_open5gs ./base
docker build -t docker_kamailio ./ims_base
docker build -t docker_ueransim ./ueransim

# 1. Start the 5G core + IMS stack
docker compose -f sa-vonr-deploy.yaml up -d

# 2. Build the pjsua-enabled UERANSIM image
./operate/scripts/build.sh

# 3. Run the full e2e test (provisions, configures, deploys)
./operate/scripts/run-e2e-vonr.sh

# 4. Make a call from UE1 to UE2
docker attach e2e_ue1
# In pjsua CLI, type: m
# Then enter: sip:0100002222@ims.mnc001.mcc001.3gppnetwork.org

# 5. Tear down (restores original Kamailio configs)
./operate/scripts/teardown.sh
```

## What the Test Runner Does

`run-e2e-vonr.sh` automates the full flow:

1. Verifies 5G core + IMS containers are running
2. Copies modified Kamailio configs into P-CSCF and S-CSCF (disables IPsec, switches to MD5 auth)
3. Restarts P-CSCF and S-CSCF
4. Provisions two subscribers in both Open5GS (MongoDB) and PyHSS (REST API)
5. Starts the gNB if not running
6. Deploys two UERANSIM UE containers with pjsua

Each UE container:
- Starts UERANSIM `nr-ue` which attaches to the 5G core and establishes two PDU sessions (internet + ims)
- Waits for the IMS APN TUN interface to come up (192.168.101.x)
- Starts pjsua bound to the IMS TUN interface
- pjsua registers with the P-CSCF through the full core network data plane

## Data Path

All SIP and RTP traffic traverses the complete 5G stack:

```
pjsua → uesimtun1 (IMS APN) → UERANSIM nr-ue → gNB → AMF/UPF → P-CSCF → IMS
```

Nothing bypasses the core network.

## What's Modified vs. Original

Only two Kamailio config files are changed (as copies — originals are never touched):

| File | Change | Why |
|------|--------|-----|
| `pcscf.cfg` | `WITH_IPSEC` commented out | pjsua doesn't support IPsec SA negotiation |
| `scscf.cfg` | `REG_AUTH_DEFAULT_ALG` set to `"MD5"` | pjsua uses SIP Digest auth, not IMS-AKA/Milenage |

The teardown script restores the originals automatically.

## Test Subscribers

Defined in `e2e.env`:

| | UE1 (Caller) | UE2 (Callee) |
|---|---|---|
| IMSI | 001011234567891 | 001011234567892 |
| MSISDN | 0100001111 | 0100002222 |
| Container IP | 172.22.0.50 | 172.22.0.51 |
