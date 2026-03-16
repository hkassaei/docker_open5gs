# docker_open5gs - Project Overview

A fully containerized 4G/5G mobile core network built on [Open5GS](https://open5gs.org/), with IMS (IP Multimedia Subsystem) for voice calls, SMS, and video — all orchestrated with Docker Compose. It lets you deploy a complete cellular network on commodity hardware, either with real SDR radios or purely in software simulation.

---

## What It Does

The repo provides ready-to-deploy Docker Compose stacks for:

- **4G LTE (EPC)** — full Evolved Packet Core with VoLTE voice calls
- **5G SA (Standalone)** — full 5G Core with VoNR (Voice over New Radio)
- **IMS** — SIP-based voice/video calling via Kamailio or OpenSIPS
- **VoWiFi** — Wi-Fi calling via an ePDG (Osmocom + Strongswan)
- **RAN simulation** — connect real SDR hardware (LimeSDR, USRP) or simulate the air interface with ZMQ

---

## Main Components

| Layer | Components | Purpose |
|-------|-----------|---------|
| **5G Core** | AMF, SMF, UPF, NRF, SCP, AUSF, UDM, UDR, PCF, BSF, NSSF | Service-based 5G architecture |
| **4G EPC** | MME, SGWC, SGWU, SMF, UPF, HSS, PCRF | Traditional 4G core |
| **IMS** | P-CSCF, I-CSCF, S-CSCF (Kamailio or OpenSIPS), RTPEngine, PyHSS, SMSC | Voice/video/SMS |
| **RAN** | srsRAN_4G (eNB+UE), srsRAN_Project (gNB), UERANSIM (5G simulator) | Radio access |
| **Support** | MongoDB, MySQL, DNS (BIND9), Metrics (Prometheus), Grafana | Data, naming, observability |
| **Extras** | eUPF (alt UPF), OCS (charging), ePDG (VoWiFi), SWu client | Specialized functions |

---

## Docker Compose Deployment Files

Pick the stack you need:

| File | What You Get |
|------|-------------|
| `sa-deploy.yaml` | 5G Standalone core (data only) |
| `sa-vonr-deploy.yaml` | 5G + IMS for VoNR calls |
| `4g-volte-deploy.yaml` | 4G EPC + Kamailio IMS for VoLTE |
| `4g-volte-opensips-ims-deploy.yaml` | 4G EPC + OpenSIPS IMS |
| `4g-external-ims-deploy.yaml` | 4G EPC + PyHSS (external IMS) |
| `4g-volte-ocs-deploy.yaml` | 4G EPC + Sigscale OCS charging |
| `4g-volte-vowifi-deploy.yaml` | 4G + VoLTE + VoWiFi (ePDG) |
| `sa-vonr-ibcf-deploy.yaml` | 5G + Kamailio IMS + IBCF |
| `sa-vonr-opensips-ims-deploy.yaml` | 5G + OpenSIPS IMS (experimental) |
| `deploy-all.yaml` | Everything at once (4G + 5G + IMS) |
| `srsenb.yaml` / `srsgnb.yaml` | RAN with real SDR hardware |
| `*_zmq.yaml` variants | RAN simulation (no hardware needed) |
| `nr-gnb.yaml` / `nr-ue.yaml` | UERANSIM 5G simulator |
| `swu_client.yaml` | SWu-IKEv2 ePDG client |

---

## Architecture at a Glance

```
┌──────────────────────────────────────────────────────────┐
│                Docker Network (172.22.0.0/24)            │
│                                                          │
│  ┌──────────┐    ┌──────────┐    ┌──────────────────┐    │
│  │  5G Core │    │  4G EPC  │    │       IMS        │    │
│  │ NRF→SCP  │    │ HSS→MME  │    │ ICSCF→SCSCF      │    │
│  │ AMF,SMF  │    │ SGWC     │    │ PCSCF→RTPEngine  │    │
│  │ UPF,AUSF │    │ PCRF     │    │ PyHSS, DNS, SMSC │    │
│  │ UDM,UDR  │    │          │    │                  │    │
│  └────┬─────┘    └────┬─────┘    └────────┬─────────┘    │
│       │               │                   │              │
│       └───────┬───────┘                   │              │
│               ▼                           ▼              │
│          ┌────────┐               ┌──────────────┐       │
│          │MongoDB │               │    MySQL     │       │
│          └────────┘               └──────────────┘       │
│                                                          │
│  ┌─────────────────────────────────────────────────┐     │
│  │              RAN Simulators                     │     │
│  │  srsRAN_4G  │  srsRAN_Project  │  UERANSIM      │     │
│  └─────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────┘
```

All services get **fixed IPs** on a single Docker bridge network. Configuration is driven by a central `.env` file (MCC, MNC, IPs, subnets), and each component has an `*_init.sh` script that templates its config at startup.

---

## Key Technologies & Versions

| Component | Technology | Version / Commit |
|-----------|-----------|------------------|
| Core Network | Open5GS | 2025.01.10 (782a97ef) |
| IMS | Kamailio | 5.8 (6fc2102ca7) |
| Alt IMS | OpenSIPS | Latest (experimental) |
| RAN 4G | srsRAN_4G | Latest (ec29b0c1) |
| RAN 5G | srsRAN_Project | Forked (11c9bbabb6) |
| RAN Sim | UERANSIM | Latest |
| Alt UPF | eUPF | Latest |
| Database | MongoDB 6.0, MySQL / MariaDB | — |
| DNS | BIND9 | 9.18 (Ubuntu jammy) |
| Media | RTPEngine | DFX.at LTS |
| Monitoring | Prometheus | Via docker_metrics |
| Visualization | Grafana | 11.3.0 |
| Charging | Sigscale OCS | Latest |
| ePDG | Osmo-ePDG + Strongswan | Latest |
| VoWiFi IKEv2 | SWu-IKEv2 | Latest |

---

## Base Docker Images

The project builds several base images that individual components extend:

- **`base/`** — Open5GS core (Ubuntu 22.04, multi-stage meson/ninja build). Contains all 4G/5G NFs, WebUI, and MongoDB support.
- **`ims_base/`** — Kamailio IMS (Ubuntu 22.04, v5.8). Custom module selection for SIP/Diameter/IMS.
- **`opensips_ims_base/`** — OpenSIPS IMS (experimental alternative to Kamailio).
- **`srslte/`** — srsRAN_4G (Ubuntu 22.04). Includes SoapySDR, Limesuite, BladeRF, UHD (USRP) for real SDR hardware plus ZMQ for simulation.
- **`srsran/`** — srsRAN_Project (Ubuntu 22.04). 5G gNB with UHD and ZMQ support.
- **`dns/`** — BIND9 DNS server for EPC/IMS 3GPP domain resolution.
- **`rtpengine/`** — RTP/media stream handling for IMS voice/video (Debian bookworm, port range 49000-50000).

---

## Configuration & Networking

### Central `.env` File

All parameters live in a single `.env` file at the repo root:

- **PLMN identity** — MCC, MNC, TAC
- **Docker network** — `TEST_NETWORK = 172.22.0.0/24`
- **Static IPs** — every component has a fixed address (e.g., AMF = 172.22.0.10, UPF = 172.22.0.8)
- **APN subnets** — internet (`192.168.100.0/24`), ims (`192.168.101.0/24`)
- **UPF TUN interfaces** — configurable names (ogstun, ogstun2)

### Startup Flow

1. Docker Compose reads `.env` for all environment variables
2. Each container runs a component-specific `*_init.sh` script
3. Init scripts substitute env vars into YAML/cfg templates via `sed`
4. Diameter components (HSS, PCRF, MME, SMF) generate TLS certificates via `make_certs.sh`
5. DNS generates zone files with dynamically computed 3GPP domain names
6. Components start their daemons and establish Diameter/SIP/HTTP peering

### Exposed Ports

| Service | Port |
|---------|------|
| WebUI | 9999 |
| Grafana | 3000 |
| Prometheus Metrics | 9090 |
| PyHSS API | 8080 |
| OCS Management | 8083 |

### Multi-Host Support

Compose files include commented-out options for distributing components across hosts, with `ADVERTISE_IP` overrides and `network_mode: host` for RAN containers using real RF hardware.

---

## Volume Mounts & Persistence

### Configuration (read-write, per component)

Each component directory (e.g., `./hss/`, `./mme/`, `./amf/`) is mounted into its container at `/mnt/<component>`.

### Persistent Data

| Volume | Purpose |
|--------|---------|
| `mongodbdata` | MongoDB subscriber data |
| `dbdata` | MySQL IMS databases |
| `grafana_data` | Grafana dashboards and settings |

### Shared Logs

All Open5GS components write to `./log/` on the host, mounted at `/open5gs/install/var/log/open5gs`.

---

## Custom Deployments

The `custom_deployments/` directory contains specialized configurations:

- **`open5gs_hss_cx`** — Custom HSS implementation with Cx interface
- **`slicing`** — Network slicing configuration examples
- **`with_eupf`** — Alternative UPF deployment using eUPF instead of Open5GS UPF

---

## Key Design Decisions

- **Single `.env` for all parameters** — change your PLMN, IPs, or APN subnets in one place
- **Template-based config** — YAML/cfg files use `sed` substitution from env vars at container start
- **Modular compose files** — pick only the components you need; mix 4G/5G/IMS freely
- **Multiple IMS options** — Kamailio (mature) or OpenSIPS (experimental)
- **SDR + simulation** — same containers work with real hardware or ZMQ virtual radios
- **Monitoring built-in** — Prometheus metrics + Grafana dashboards for core network KPIs

---

## Typical Use Cases

1. **Telecom R&D** — test 4G/5G features without carrier infrastructure
2. **VoLTE/VoNR development** — end-to-end voice call testing with IMS
3. **Academic/lab environments** — teach mobile networking with a real stack
4. **Private LTE/5G networks** — deploy on-premises cellular with SDR radios
5. **Protocol testing** — validate SIP, Diameter, NGAP, PFCP behavior
6. **Network slicing experiments** — via custom deployment configs

---

## Key File Paths

| Category | Path |
|----------|------|
| **Configuration templates** | `mme/mme.yaml`, `amf/amf.yaml`, `smf/smf.yaml`, `upf/upf.yaml` |
| **IMS configs** | `pcscf/kamailio_pcscf.cfg`, `scscf/kamailio_scscf.cfg`, `icscf/kamailio_icscf.cfg` |
| **DNS config** | `dns/named.conf` |
| **Init scripts** | `base/open5gs_init.sh`, `ims_base/kamailio_init.sh`, `mme/mme_init.sh`, etc. |
| **Utilities** | `smf/ip_utils.py`, `upf/tun_if.py` |
| **Environment** | `.env` |
