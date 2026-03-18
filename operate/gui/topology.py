"""
Live Network Topology — Graph Data Model & Docker Discovery

Provides the NFNode/NFEdge/NetworkTopology dataclasses and a
build_topology() async function that discovers running containers
from Docker, matches them against known NF types, and returns a
complete topology snapshot with live status.

Consumed by server.py (GET /api/topology) and importable by the
AI troubleshooting agent for structural reasoning.
"""

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field, asdict

# -------------------------------------------------------------------------
# Grid row constants
# -------------------------------------------------------------------------
ROW_DATA = 0
ROW_CORE = 1
ROW_IMS = 2
ROW_RAN = 3
ROW_UE = 4

# -------------------------------------------------------------------------
# Dataclasses
# -------------------------------------------------------------------------

@dataclass
class NFNode:
    id: str              # container name, e.g. "amf", "e2e_ue1"
    label: str           # human-readable, e.g. "AMF", "UE1"
    layer: str           # "core" | "ims" | "ran" | "ue" | "data"
    role: str            # specific function, e.g. "authentication"
    ip: str              # static IP from .env
    status: str          # "running" | "exited" | "absent"
    health: str          # "healthy" | "down" | "unknown"
    protocols: list[str] = field(default_factory=list)
    row: int = 0
    slot: int = 0
    sublabel: str = ""   # e.g. "PSA" for UPF


@dataclass
class NFEdge:
    source: str
    target: str
    protocol: str        # "SBI", "NGAP", "PFCP", "GTP-U", "SIP", etc.
    interface: str       # 3GPP interface: "N2", "N4", "Gm", "Cx", etc.
    plane: str           # "control" | "data" | "signaling" | "management"
    label: str           # human-readable, e.g. "N2 (NGAP)"
    active: bool = True  # True if both endpoints are running
    logical: bool = False  # True for N1 NAS logical edges


@dataclass
class NetworkTopology:
    nodes: list[NFNode] = field(default_factory=list)
    edges: list[NFEdge] = field(default_factory=list)
    phase: str = "down"  # "ready" | "partial" | "down"
    timestamp: float = 0.0

    def neighbors(self, node_id: str) -> list[str]:
        """Return all node IDs directly connected to the given node."""
        result = set()
        for e in self.edges:
            if e.source == node_id:
                result.add(e.target)
            elif e.target == node_id:
                result.add(e.source)
        return sorted(result)

    def edges_for(self, node_id: str) -> list[NFEdge]:
        """Return all edges connected to the given node."""
        return [e for e in self.edges
                if e.source == node_id or e.target == node_id]

    def path_between(self, src: str, dst: str) -> list[NFEdge] | None:
        """BFS shortest path between two nodes. Returns edge list or None."""
        if src == dst:
            return []
        adj: dict[str, list[tuple[str, NFEdge]]] = {}
        for e in self.edges:
            adj.setdefault(e.source, []).append((e.target, e))
            adj.setdefault(e.target, []).append((e.source, e))
        visited = {src}
        queue: deque[tuple[str, list[NFEdge]]] = deque([(src, [])])
        while queue:
            current, path = queue.popleft()
            for neighbor, edge in adj.get(current, []):
                if neighbor in visited:
                    continue
                new_path = path + [edge]
                if neighbor == dst:
                    return new_path
                visited.add(neighbor)
                queue.append((neighbor, new_path))
        return None

    def impact_of(self, node_id: str) -> dict:
        """Return affected edges and downstream nodes if this node goes down."""
        affected_edges = self.edges_for(node_id)
        affected_nodes = set()
        for e in affected_edges:
            other = e.target if e.source == node_id else e.source
            affected_nodes.add(other)
        return {
            "node": node_id,
            "broken_edges": [asdict(e) for e in affected_edges],
            "affected_nodes": sorted(affected_nodes),
        }

    def to_dict(self) -> dict:
        """Serialize to JSON-safe dict."""
        return asdict(self)


# -------------------------------------------------------------------------
# Known NF Type Dictionary
# Maps container name → (label, layer, role, ip_env_key, protocols, (row, slot), sublabel)
# -------------------------------------------------------------------------
_KNOWN_NF_TYPES: dict[str, tuple[str, str, str, str, list[str], tuple[int, int], str]] = {
    # Data stores (Row 0)
    "mongo":     ("MongoDB",     "data", "document-store",     "MONGO_IP",     ["MongoDB"],             (ROW_DATA, 1), ""),
    "mysql":     ("MySQL",       "data", "relational-store",   "MYSQL_IP",     ["SQL"],                 (ROW_DATA, 3), ""),
    "dns":       ("DNS",         "data", "name-resolution",    "DNS_IP",       ["DNS"],                 (ROW_DATA, 5), ""),

    # 5G Core (Row 1)
    "nrf":       ("NRF",         "core", "nf-discovery",       "NRF_IP",       ["SBI"],                 (ROW_CORE, 0), ""),
    "scp":       ("SCP",         "core", "service-proxy",      "SCP_IP",       ["SBI"],                 (ROW_CORE, 1), ""),
    "ausf":      ("AUSF",        "core", "authentication",     "AUSF_IP",      ["SBI"],                 (ROW_CORE, 2), ""),
    "udm":       ("UDM",         "core", "data-management",    "UDM_IP",       ["SBI"],                 (ROW_CORE, 3), ""),
    "udr":       ("UDR",         "core", "data-repository",    "UDR_IP",       ["SBI"],                 (ROW_CORE, 4), ""),
    "amf":       ("AMF",         "core", "access-mobility",    "AMF_IP",       ["SBI", "NGAP"],         (ROW_CORE, 5), ""),
    "smf":       ("SMF",         "core", "session-management", "SMF_IP",       ["SBI", "PFCP"],         (ROW_CORE, 6), ""),
    "upf":       ("UPF",         "core", "user-plane-anchor",  "UPF_IP",       ["PFCP", "GTP-U"],       (ROW_CORE, 7), "PSA"),
    "pcf":       ("PCF",         "core", "policy-control",     "PCF_IP",       ["SBI", "Diameter"],     (ROW_CORE, 8), ""),

    # IMS (Row 2)
    "pcscf":     ("P-CSCF",      "ims",  "sip-edge-proxy",    "PCSCF_IP",     ["SIP", "Diameter"],     (ROW_IMS, 2), ""),
    "rtpengine": ("RTPEngine",   "ims",  "media-relay",       "RTPENGINE_IP", ["RTP", "ng"],           (ROW_IMS, 3), ""),
    "icscf":     ("I-CSCF",      "ims",  "sip-interrogating", "ICSCF_IP",     ["SIP", "Diameter"],     (ROW_IMS, 4), ""),
    "scscf":     ("S-CSCF",      "ims",  "sip-serving",       "SCSCF_IP",     ["SIP", "Diameter"],     (ROW_IMS, 5), ""),
    "pyhss":     ("HSS",         "ims",  "subscriber-db",     "PYHSS_IP",     ["Diameter"],            (ROW_IMS, 7), ""),

    # RAN (Row 3)
    "nr_gnb":    ("gNB",         "ran",  "radio-access",      "NR_GNB_IP",    ["NGAP", "GTP-U"],       (ROW_RAN, 5), ""),

    # UEs (Row 4)
    "e2e_ue1":   ("UE1",         "ue",   "subscriber",        "UE1_IP",       ["NAS", "SIP"],          (ROW_UE, 4), ""),
    "e2e_ue2":   ("UE2",         "ue",   "subscriber",        "UE2_IP",       ["NAS", "SIP"],          (ROW_UE, 6), ""),
}

# -------------------------------------------------------------------------
# Static Edge Definitions (40 edges)
# (source, target, protocol, interface, plane, label, logical)
# -------------------------------------------------------------------------
_STATIC_EDGES: list[tuple[str, str, str, str, str, str, bool]] = [
    # RAN / Air Interface (2)
    ("e2e_ue1", "nr_gnb",    "NR-Uu",   "Uu",   "data",       "Air Interface",      False),
    ("e2e_ue2", "nr_gnb",    "NR-Uu",   "Uu",   "data",       "Air Interface",      False),

    # N1 NAS — logical (2)
    ("e2e_ue1", "amf",       "NAS",     "N1",   "control",    "N1 (NAS)",           True),
    ("e2e_ue2", "amf",       "NAS",     "N1",   "control",    "N1 (NAS)",           True),

    # 3GPP Reference Points (3)
    ("nr_gnb",  "amf",       "NGAP",    "N2",   "control",    "N2 (NGAP)",          False),
    ("nr_gnb",  "upf",       "GTP-U",   "N3",   "data",       "N3 (GTP-U)",         False),
    ("smf",     "upf",       "PFCP",    "N4",   "control",    "N4 (PFCP)",          False),

    # 5G Core SBI (12)
    ("amf",     "nrf",       "SBI",     "Nnrf", "control",    "SBI (NRF)",          False),
    ("amf",     "scp",       "SBI",     "",     "control",    "SBI (SCP)",          False),
    ("smf",     "nrf",       "SBI",     "Nnrf", "control",    "SBI (NRF)",          False),
    ("smf",     "scp",       "SBI",     "",     "control",    "SBI (SCP)",          False),
    ("ausf",    "nrf",       "SBI",     "Nnrf", "control",    "SBI (NRF)",          False),
    ("ausf",    "scp",       "SBI",     "",     "control",    "SBI (SCP)",          False),
    ("udm",     "nrf",       "SBI",     "Nnrf", "control",    "SBI (NRF)",          False),
    ("udm",     "scp",       "SBI",     "",     "control",    "SBI (SCP)",          False),
    ("udr",     "nrf",       "SBI",     "Nnrf", "control",    "SBI (NRF)",          False),
    ("udr",     "scp",       "SBI",     "",     "control",    "SBI (SCP)",          False),
    ("pcf",     "nrf",       "SBI",     "Nnrf", "control",    "SBI (NRF)",          False),
    ("pcf",     "scp",       "SBI",     "",     "control",    "SBI (SCP)",          False),

    # IMS Signaling — SIP (5)
    ("e2e_ue1", "pcscf",     "SIP",     "Gm",   "signaling",  "Gm (SIP)",           False),
    ("e2e_ue2", "pcscf",     "SIP",     "Gm",   "signaling",  "Gm (SIP)",           False),
    ("pcscf",   "icscf",     "SIP",     "Mw",   "signaling",  "Mw (SIP)",           False),
    ("pcscf",   "scscf",     "SIP",     "Mw",   "signaling",  "Mw (SIP)",           False),
    ("icscf",   "scscf",     "SIP",     "Mw",   "signaling",  "Mw (SIP)",           False),

    # Diameter (2)
    ("icscf",   "pyhss",     "Diameter", "Cx",  "signaling",  "Cx (Diameter)",      False),
    ("scscf",   "pyhss",     "Diameter", "Cx",  "signaling",  "Cx (Diameter)",      False),

    # Policy / QoS (1)
    ("pcscf",   "pcf",       "Diameter", "Rx",  "control",    "Rx (Diameter)",      False),

    # Media (3)
    ("upf",       "rtpengine", "RTP",     "",    "data",       "RTP Media",          False),
    ("rtpengine", "upf",       "RTP",     "",    "data",       "RTP Media",          False),
    ("pcscf",     "rtpengine", "ng",      "",    "control",    "RTPEngine Control",  False),

    # Data Stores (6)
    ("udr",    "mongo",      "MongoDB",  "",    "management", "MongoDB",            False),
    ("pcf",    "mongo",      "MongoDB",  "",    "management", "MongoDB",            False),
    ("pyhss",  "mysql",      "SQL",      "",    "management", "MySQL",              False),
    ("icscf",  "mysql",      "SQL",      "",    "management", "MySQL",              False),
    ("scscf",  "mysql",      "SQL",      "",    "management", "MySQL",              False),
    ("pcscf",  "mysql",      "SQL",      "",    "management", "MySQL",              False),

    # DNS (4)
    ("pyhss",  "dns",        "DNS",      "",    "management", "DNS",                False),
    ("icscf",  "dns",        "DNS",      "",    "management", "DNS",                False),
    ("scscf",  "dns",        "DNS",      "",    "management", "DNS",                False),
    ("pcscf",  "dns",        "DNS",      "",    "management", "DNS",                False),
]

# SBI bus NFs — used by frontend to render the service bus visualization
SBI_BUS_NFS = ["nrf", "scp", "ausf", "udm", "udr", "amf", "smf", "pcf"]


# -------------------------------------------------------------------------
# Docker Discovery
# -------------------------------------------------------------------------

async def _run_cmd(cmd: str) -> tuple[int, str]:
    """Run a shell command, return (returncode, stdout)."""
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return proc.returncode or 0, stdout.decode(errors="replace").strip()


async def _discover_containers() -> dict[str, str]:
    """Discover all Docker containers (running + stopped).
    Returns {container_name: status}."""
    rc, out = await _run_cmd(
        "docker ps -a --format '{{.Names}}\\t{{.State}}'"
    )
    if rc != 0 or not out:
        return {}
    result = {}
    for line in out.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            name, state = parts
            result[name.strip()] = state.strip()
    return result


def _health_from_status(status: str) -> str:
    """Derive health from container status."""
    if status == "running":
        return "healthy"
    return "down"


async def build_topology(env: dict[str, str]) -> NetworkTopology:
    """Build a complete topology snapshot from Docker state.

    Args:
        env: Merged environment dict (.env + e2e.env) for IP resolution.

    Returns:
        NetworkTopology with discovered nodes, filtered edges, and phase.
    """
    containers = await _discover_containers()

    # Build nodes for containers that match known NF types
    nodes: list[NFNode] = []
    node_ids: set[str] = set()
    node_status: dict[str, str] = {}

    for name, nf_def in _KNOWN_NF_TYPES.items():
        label, layer, role, ip_key, protocols, (row, slot), sublabel = nf_def

        # Check if this container exists (running or stopped)
        if name not in containers:
            continue

        status = containers[name]
        # Normalize docker states to our status values
        if status == "running":
            s = "running"
        elif status in ("exited", "dead", "created"):
            s = "exited"
        else:
            s = "exited"

        ip = env.get(ip_key, "")
        health = _health_from_status(s)

        nodes.append(NFNode(
            id=name,
            label=label,
            layer=layer,
            role=role,
            ip=ip,
            status=s,
            health=health,
            protocols=list(protocols),
            row=row,
            slot=slot,
            sublabel=sublabel,
        ))
        node_ids.add(name)
        node_status[name] = s

    # Filter edges: only include edges where both endpoints exist
    edges: list[NFEdge] = []
    for src, tgt, proto, iface, plane, lbl, logical in _STATIC_EDGES:
        if src in node_ids and tgt in node_ids:
            active = (node_status.get(src) == "running"
                      and node_status.get(tgt) == "running")
            edges.append(NFEdge(
                source=src,
                target=tgt,
                protocol=proto,
                interface=iface,
                plane=plane,
                label=lbl,
                active=active,
                logical=logical,
            ))

    # Determine phase
    core_nfs = {"nrf", "scp", "ausf", "udr", "udm", "amf", "smf", "upf", "pcf",
                "dns", "mysql", "mongo", "pyhss", "icscf", "scscf", "pcscf", "rtpengine"}
    core_up = all(node_status.get(c) == "running" for c in core_nfs if c in node_ids)
    gnb_up = node_status.get("nr_gnb") == "running"
    ues_up = all(node_status.get(c) == "running"
                 for c in ("e2e_ue1", "e2e_ue2") if c in node_ids)

    if core_up and gnb_up and ues_up:
        phase = "ready"
    elif core_up:
        phase = "partial"
    else:
        phase = "down"

    return NetworkTopology(
        nodes=nodes,
        edges=edges,
        phase=phase,
        timestamp=time.time(),
    )
