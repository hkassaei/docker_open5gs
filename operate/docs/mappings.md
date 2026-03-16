# Mapping of docker_open5gs to 3GPP Standard & Industry/Commercial Telecom Offerngs

This document maps the open-source components found in this project to their official **3GPP Functional Entities** and corresponding **Commercial/Industry Terms**.

### 1. 4G Core Network (EPC - Evolved Packet Core)

| Project Component | 3GPP Functional Entity | Commercial / Industry Term |
| :--- | :--- | :--- |
| **mme** | **MME** (Mobility Management Entity) | Core Signaling Node |
| **hss** | **HSS** (Home Subscriber Server) | Central Subscriber Database |
| **sgwc** | **SGW-C** (Serving Gateway - Control) | Mobility Anchor (Control Plane) |
| **sgwu** | **SGW-U** (Serving Gateway - User) | Mobility Anchor (User Plane) |
| **smf** (as PGW-C) | **PGW-C** (PDN Gateway - Control) | IP Anchor / Session Manager |
| **upf** (as PGW-U) | **PGW-U** (PDN Gateway - User) | Internet Gateway / Firewall |
| **pcrf** | **PCRF** (Policy & Charging Rules) | Policy Engine (QoS Control) |

### 2. 5G Core Network (5GC)

| Project Component | 3GPP Functional Entity | Commercial / Industry Term |
| :--- | :--- | :--- |
| **amf** | **AMF** (Access & Mobility Management) | Access Controller |
| **smf** | **SMF** (Session Management Function) | Session Controller |
| **upf** / **eupf** | **UPF** (User Plane Function) | User Plane Gateway |
| **ausf** | **AUSF** (Authentication Server) | Auth Server |
| **udm** | **UDM** (Unified Data Management) | Subscriber Data Manager |
| **udr** | **UDR** (Unified Data Repository) | Database Backend |
| **nrf** | **NRF** (Network Repository Function) | NF Directory / Service Registry |
| **pcf** | **PCF** (Policy Control Function) | 5G Policy Engine |
| **nssf** | **NSSF** (Network Slice Selection) | Slicing Manager |
| **scp** | **SCP** (Service Communication Proxy) | Signaling Mesh / Bus |

### 3. IMS (IP Multimedia Subsystem) & Voice

| Project Component | 3GPP Functional Entity | Commercial / Industry Term |
| :--- | :--- | :--- |
| **kamailio** / **opensips** | **P-CSCF** (Proxy CSCF) | **SBC** (Session Border Controller) |
| **kamailio** (icscf) | **I-CSCF** (Interrogating CSCF) | SIP Proxy / Entry Point |
| **kamailio** (scscf) | **S-CSCF** (Serving CSCF) | Registrar / Call Controller |
| **rtpengine** | **IMS-AGW** / **TrGW** | **SBC Media Plane** / Gateway |
| **ibcf** (Asterisk/Kamailio)| **IBCF** (Interconnection Border) | Network Interconnect Gateway |
| **pyhss** | **HSS-IMS** / **SLF** | IMS Subscriber Database |

### 4. Charging & WiFi Access (Non-3GPP)

| Project Component | 3GPP Functional Entity | Commercial / Industry Term |
| :--- | :--- | :--- |
| **ocs** (Sigscale) | **CHF** (Charging Function) | **OCS** (Online Charging System) |
| **osmoepdg** | **ePDG** (evolved Packet Data Gateway) | VoWiFi Gateway |
| **strongswan** | **AAA Server** / **IKEv2 Proxy** | Security Gateway (SecGW) |
| **swu_client** | **UE** (VoWiFi Client) | WiFi Calling App / Client |

### 5. RAN (Radio Access Network) & Simulation

| Project Component | 3GPP Functional Entity | Commercial / Industry Term |
| :--- | :--- | :--- |
| **srsenb** / **oaienb** | **eNodeB** (Evolved NodeB) | 4G Base Station |
| **srsgnb** / **oaignb** | **gNodeB** (Next Gen NodeB) | 5G Base Station |
| **nr-gnb** (UERANSIM) | **gNodeB** (Simulated) | RAN Simulator |
| **srsue** / **nr-ue** | **UE** (User Equipment) | Phone / Modem / SIM |

### 6. Support & Management

| Project Component | Industry Term | Role in Lab |
| :--- | :--- | :--- |
| **dns** (BIND9) | **DNS / ENUM Server** | Resolving 3GPP FQDNs |
| **mysql** / **mongodb** | **Database Tier** | Backend for HSS, UDR, and PCRF |
| **metrics** (Prometheus) | **EMS / NMS** | Element Management / Performance Monitoring |
| **grafana** | **Dashboard** | Visualization of throughput, latencies, and UE count |
