# Docker Open5GS Deployment Options

This document provides a comprehensive overview of the available deployment configurations for the `docker_open5gs` project. It covers the various Docker Compose stacks, their 3GPP functional roles, and common deployment scenarios.

## 1. Quick Start: Deployment Files Overview

The project provides several Docker Compose files tailored for specific network architectures. Choose the stack that matches your use case:

| Compose File | Network Architecture | Description |
| :--- | :--- | :--- |
| `sa-deploy.yaml` | **5G SA** | Standard 5G Standalone (5GC) Core Network (Data only). |
| `sa-vonr-deploy.yaml` | **5G SA + IMS** | 5G Core with Kamailio IMS for Voice over New Radio (VoNR). |
| `4g-volte-deploy.yaml` | **4G EPC + IMS** | 4G Core with Kamailio IMS for Voice over LTE (VoLTE). |
| `4g-volte-vowifi-deploy.yaml` | **4G + VoLTE + VoWiFi** | Includes ePDG (Osmocom + Strongswan) for Wi-Fi calling. |
| `4g-volte-ocs-deploy.yaml` | **4G + IMS + OCS** | Includes Sigscale Online Charging System (OCS). |
| `4g-volte-opensips-ims-deploy.yaml`| **4G + OpenSIPS** | 4G Core with OpenSIPS as the IMS alternative. |
| `4g-external-ims-deploy.yaml` | **4G + Ext IMS** | EPC with PyHSS and OCS (no internal IMS components). |
| `sa-vonr-ibcf-deploy.yaml` | **5G + IMS + IBCF** | 5G Core + Kamailio IMS + Interconnection Border Control Function. |
| `sa-vonr-opensips-ims-deploy.yaml` | **5G + OpenSIPS** | Experimental 5G IMS using OpenSIPS. |
| `deploy-all.yaml` | **Full Stack** | Deploys 4G + 5G + IMS simultaneously. |

## 2. Radio Access Network (RAN) Options

Depending on whether you have hardware (SDR) or want to simulate the air interface:

| Category | Files | Description |
| :--- | :--- | :--- |
| **Real Hardware** | `srsenb.yaml` / `srsgnb.yaml` | Connect real SDRs (USRP B210, LimeSDR, etc.). |
| **Simulated (ZMQ)** | `*_zmq.yaml` variants | RF simulation over ZMQ (no hardware needed). |
| **Simulated (UE/gNB)** | `nr-gnb.yaml` / `nr-ue.yaml` | UERANSIM 5G gNB and UE simulators. |
| **VoWiFi Client** | `swu_client.yaml` | SWu-IKEv2 client for ePDG testing. |

## 3. 3GPP Mapping & Functional Entities

Understanding what each component does in a standard telecom architecture:

### 4G Evolved Packet Core (EPC)
*   **MME**: Mobility Management (Signaling).
*   **HSS**: Subscriber Database.
*   **SGW-C / SGW-U**: Serving Gateway (Control/User Plane).
*   **PGW-C / PGW-U**: PDN Gateway (Anchor to Internet).
*   **PCRF**: Policy and Charging Rules.

### 5G Core (5GC)
*   **AMF**: Access & Mobility Management.
*   **SMF**: Session Management.
*   **UPF**: User Plane Function (Gateway).
*   **AUSF / UDM / UDR**: Authentication and Subscriber Data management.
*   **NRF**: Network Repository (Service Discovery).
*   **PCF**: Policy Control.

### IMS (IP Multimedia Subsystem)
*   **P-CSCF**: Proxy CSCF (The entry point/SBC).
*   **I-CSCF**: Interrogating CSCF (SIP Proxy).
*   **S-CSCF**: Serving CSCF (Registrar/Call Control).
*   **RTPEngine**: Media Plane Gateway (Handles voice/video streams).

## 4. Deployment Scenarios

### Single Host Deployment
In this mode, all components (Core + RAN) are deployed on the same physical machine. 
*   **Configuration**: Edit `.env` to set `DOCKER_HOST_IP` to your machine's IP.
*   **Networking**: Uses the default Docker bridge network (`172.22.0.0/24`).

### Multi-Host Deployment
For distributed labs where the Core runs on one server and the RAN runs on another (or a separate PC with SDRs).
*   **Core Host**: Uncomment SCTP/UDP ports in the respective `*-deploy.yaml` files (e.g., 36412 for MME, 38412 for AMF, 2152 for UPF).
*   **RAN Host**: Use `network_mode: host` in the RAN compose files and point `MME_IP` or `AMF_IP` to the Core Host's address.

## 5. Custom & Advanced Deployments
The `custom_deployments/` directory contains specialized configurations for:
*   **Network Slicing**: Located in `./custom_deployments/slicing/`.
*   **eUPF Integration**: Using an eBPF-based UPF instead of the default Open5GS UPF.
*   **HSS Cx Interface**: Specialized HSS configurations for Cx/Dx protocols.
