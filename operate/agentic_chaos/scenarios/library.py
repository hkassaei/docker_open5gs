"""
Scenario Library — 10 curated failure scenarios for the 5G SA + IMS stack.

Each scenario is a Scenario object ready to pass to run_scenario().
Scenarios are organized by blast radius: single NF → multi-NF → global.

Usage:
    from agentic_chaos.scenarios.library import SCENARIOS, get_scenario

    scenario = get_scenario("P-CSCF Latency")
    episode = await run_scenario(scenario)

IPs are from .env — hardcoded here because the scenario library is a
static definition. If IPs change, update these constants.
"""

from __future__ import annotations

from ..models import BlastRadius, FaultCategory, FaultSpec, Scenario

# -------------------------------------------------------------------------
# IPs from .env (used by network partition scenarios)
# -------------------------------------------------------------------------
_ICSCF_IP = "172.22.0.19"
_SCSCF_IP = "172.22.0.20"
_PCSCF_IP = "172.22.0.21"
_MYSQL_IP = "172.22.0.17"

# -------------------------------------------------------------------------
# Single-NF scenarios
# -------------------------------------------------------------------------

gnb_radio_link_failure = Scenario(
    name="gNB Radio Link Failure",
    description=(
        "Kill the gNB to simulate a radio link failure. All UEs lose 5G "
        "registration, PDU sessions drop, and IMS SIP unregisters."
    ),
    category=FaultCategory.CONTAINER,
    blast_radius=BlastRadius.SINGLE_NF,
    faults=[
        FaultSpec(fault_type="container_kill", target="nr_gnb", ttl_seconds=300),
    ],
    expected_symptoms=[
        "UEs lose RAN connection",
        "PDU sessions dropped",
        "SIP REGISTER expires without renewal",
        "gNB disappears from AMF",
    ],
    observation_window_seconds=30,
    ttl_seconds=300,
)

pcscf_latency = Scenario(
    name="P-CSCF Latency",
    description=(
        "Inject 500ms latency on the P-CSCF (SIP edge proxy). SIP T1 timer "
        "is 500ms, so REGISTER transactions will start timing out. Tests "
        "IMS resilience to WAN-like latency on the signaling path."
    ),
    category=FaultCategory.NETWORK,
    blast_radius=BlastRadius.SINGLE_NF,
    faults=[
        FaultSpec(
            fault_type="network_latency",
            target="pcscf",
            params={"delay_ms": 500, "jitter_ms": 50},
            ttl_seconds=300,
        ),
    ],
    expected_symptoms=[
        "SIP REGISTER 408 Request Timeout",
        "Kamailio tm transaction timeouts",
        "IMS registration failures at UEs",
    ],
    escalation=True,
    observation_window_seconds=30,
    ttl_seconds=300,
)

scscf_crash = Scenario(
    name="S-CSCF Crash",
    description=(
        "Kill the S-CSCF (Serving-CSCF). This is the core SIP registrar and "
        "call controller. All IMS authentication stops, new registrations "
        "are impossible, and active calls will eventually drop."
    ),
    category=FaultCategory.CONTAINER,
    blast_radius=BlastRadius.SINGLE_NF,
    faults=[
        FaultSpec(fault_type="container_kill", target="scscf", ttl_seconds=300),
    ],
    expected_symptoms=[
        "IMS authentication fails (no MAR/MAA)",
        "New SIP REGISTER rejected or times out",
        "Active SIP dialogs expire",
        "I-CSCF cannot route to S-CSCF",
    ],
    observation_window_seconds=30,
    ttl_seconds=300,
)

hss_unresponsive = Scenario(
    name="HSS Unresponsive",
    description=(
        "Pause PyHSS (freeze all processes). The HSS is still 'running' from "
        "Docker's perspective but cannot process Diameter requests. Tests "
        "how the I-CSCF and S-CSCF handle a hung Diameter peer."
    ),
    category=FaultCategory.CONTAINER,
    blast_radius=BlastRadius.SINGLE_NF,
    faults=[
        FaultSpec(fault_type="container_pause", target="pyhss", ttl_seconds=300),
    ],
    expected_symptoms=[
        "Diameter UAR/UAA timeout at I-CSCF",
        "Diameter MAR/MAA timeout at S-CSCF",
        "SIP REGISTER stalls (waiting for Diameter)",
        "CDP peer state changes",
    ],
    observation_window_seconds=30,
    ttl_seconds=300,
)

data_plane_degradation = Scenario(
    name="Data Plane Degradation",
    description=(
        "Inject 30% packet loss on the UPF. RTP media streams will degrade, "
        "voice quality drops. Tests whether the stack detects and reports "
        "data plane quality issues."
    ),
    category=FaultCategory.NETWORK,
    blast_radius=BlastRadius.SINGLE_NF,
    faults=[
        FaultSpec(
            fault_type="network_loss",
            target="upf",
            params={"loss_pct": 30},
            ttl_seconds=300,
        ),
    ],
    expected_symptoms=[
        "RTP packet loss on voice calls",
        "GTP-U packet counters anomaly",
        "Potential call quality degradation",
    ],
    observation_window_seconds=30,
    ttl_seconds=300,
)


# -------------------------------------------------------------------------
# Global scenarios
# -------------------------------------------------------------------------

mongodb_gone = Scenario(
    name="MongoDB Gone",
    description=(
        "Kill MongoDB — the 5G core subscriber data store. UDR loses its "
        "backend, new PDU sessions cannot be created, and subscriber "
        "queries fail. Existing sessions may survive briefly."
    ),
    category=FaultCategory.CONTAINER,
    blast_radius=BlastRadius.GLOBAL,
    faults=[
        FaultSpec(fault_type="container_kill", target="mongo", ttl_seconds=300),
    ],
    expected_symptoms=[
        "UDR connection errors to MongoDB",
        "New PDU session creation fails",
        "5G subscriber queries fail",
        "AMF registration may still work (cached)",
    ],
    observation_window_seconds=30,
    ttl_seconds=300,
)

dns_failure = Scenario(
    name="DNS Failure",
    description=(
        "Kill the DNS server. IMS domain resolution breaks — SIP routing "
        "depends on DNS NAPTR/SRV records for the IMS domain. All new "
        "SIP transactions that require DNS resolution will fail."
    ),
    category=FaultCategory.CONTAINER,
    blast_radius=BlastRadius.GLOBAL,
    faults=[
        FaultSpec(fault_type="container_kill", target="dns", ttl_seconds=300),
    ],
    expected_symptoms=[
        "IMS domain unresolvable",
        "SIP routing failures",
        "Kamailio DNS lookup errors",
        "New registrations fail",
    ],
    observation_window_seconds=30,
    ttl_seconds=300,
)


# -------------------------------------------------------------------------
# Multi-NF scenarios
# -------------------------------------------------------------------------

ims_network_partition = Scenario(
    name="IMS Network Partition",
    description=(
        "Partition the P-CSCF from both the I-CSCF and S-CSCF using iptables "
        "DROP rules. SIP signaling between the edge proxy and the core IMS "
        "is completely severed. Tests IMS behavior under a network split."
    ),
    category=FaultCategory.NETWORK,
    blast_radius=BlastRadius.MULTI_NF,
    faults=[
        FaultSpec(
            fault_type="network_partition",
            target="pcscf",
            params={"target_ip": _ICSCF_IP},
            ttl_seconds=300,
        ),
        FaultSpec(
            fault_type="network_partition",
            target="pcscf",
            params={"target_ip": _SCSCF_IP},
            ttl_seconds=300,
        ),
    ],
    expected_symptoms=[
        "SIP signaling severed (P-CSCF → I/S-CSCF)",
        "New REGISTER and INVITE fail",
        "Kamailio tm transaction timeouts",
        "Active calls may survive briefly (RTP via UPF, not CSCFs)",
    ],
    observation_window_seconds=30,
    ttl_seconds=300,
)

amf_restart = Scenario(
    name="AMF Restart (Upgrade Simulation)",
    description=(
        "Stop the AMF for 10 seconds, then restart it. Simulates a rolling "
        "upgrade of the access and mobility management function. UEs will "
        "temporarily lose their 5G NAS connection and must re-attach."
    ),
    category=FaultCategory.CONTAINER,
    blast_radius=BlastRadius.MULTI_NF,
    faults=[
        FaultSpec(
            fault_type="container_stop",
            target="amf",
            params={"timeout": 10},
            ttl_seconds=300,
        ),
    ],
    expected_symptoms=[
        "UEs lose NAS connection",
        "NGAP association dropped at gNB",
        "UEs must re-register after AMF recovers",
        "Temporary PDU session disruption",
    ],
    observation_window_seconds=45,
    ttl_seconds=300,
)

cascading_ims_failure = Scenario(
    name="Cascading IMS Failure",
    description=(
        "Kill PyHSS AND add 2-second latency to the S-CSCF. This simulates "
        "a cascading failure: the HSS is gone (no Diameter auth) AND the "
        "S-CSCF is degraded (slow SIP processing). Total IMS outage."
    ),
    category=FaultCategory.COMPOUND,
    blast_radius=BlastRadius.MULTI_NF,
    faults=[
        FaultSpec(fault_type="container_kill", target="pyhss", ttl_seconds=300),
        FaultSpec(
            fault_type="network_latency",
            target="scscf",
            params={"delay_ms": 2000},
            ttl_seconds=300,
        ),
    ],
    expected_symptoms=[
        "Diameter completely down (HSS killed)",
        "SIP transactions extremely slow (2s latency on S-CSCF)",
        "Total IMS registration failure",
        "No voice calls possible",
    ],
    challenge_mode=True,
    observation_window_seconds=30,
    ttl_seconds=300,
)


# -------------------------------------------------------------------------
# Registry
# -------------------------------------------------------------------------

SCENARIOS: dict[str, Scenario] = {
    s.name: s
    for s in [
        gnb_radio_link_failure,
        pcscf_latency,
        scscf_crash,
        hss_unresponsive,
        data_plane_degradation,
        mongodb_gone,
        dns_failure,
        ims_network_partition,
        amf_restart,
        cascading_ims_failure,
    ]
}


def get_scenario(name: str) -> Scenario:
    """Look up a scenario by name. Raises KeyError if not found."""
    if name not in SCENARIOS:
        available = "\n  ".join(sorted(SCENARIOS.keys()))
        raise KeyError(f"Unknown scenario '{name}'. Available:\n  {available}")
    return SCENARIOS[name]


def list_scenarios() -> list[dict]:
    """Return a summary list of all scenarios."""
    return [
        {
            "name": s.name,
            "category": s.category.value,
            "blast_radius": s.blast_radius.value,
            "faults": len(s.faults),
            "description": s.description[:80] + "..." if len(s.description) > 80 else s.description,
        }
        for s in SCENARIOS.values()
    ]
