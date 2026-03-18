# Live Network Topology View — Implementation Plan

## Overview

Add a live, interactive network topology view to the VoNR Learning Tool GUI.
The view is backed by a graph data model (nodes + edges) that reflects the
real-time state of every Network Function in the stack: what's running, its
health, and how it connects to other NFs.

---

## 1. Data Model Design

### Location

New file: **`operate/gui/topology.py`** — adjacent to `server.py` (its sole
consumer). Uses Python **dataclasses** (not Pydantic) to keep the dependency
footprint small. Serializes to JSON via `dataclasses.asdict()`.

### NFNode

```python
@dataclass
class NFNode:
    id: str              # container name, e.g. "amf", "e2e_ue1"
    label: str           # human-readable, e.g. "AMF", "UE1"
    layer: str           # "core" | "ims" | "ran" | "ue" | "data"
    role: str            # specific function, e.g. "authentication", "session-management"
    ip: str              # static IP from .env, e.g. "172.22.0.10"
    status: str          # "running" | "exited" | "absent" — filled at query time
    health: str          # "healthy" | "degraded" | "down" | "unknown" — derived
    protocols: list[str] # ["SBI", "NGAP"], for tooltip/info
```

### NFEdge

```python
@dataclass
class NFEdge:
    source: str          # node id
    target: str          # node id
    protocol: str        # "SBI", "NGAP", "PFCP", "GTP-U", "SIP", "Diameter", etc.
    interface: str       # 3GPP interface name: "N2", "N4", "Gm", "Cx", etc.
    plane: str           # "control" | "data" | "signaling" | "management"
    label: str           # human-readable, e.g. "N2 (NGAP)"
    active: bool         # True if both endpoints are running
```

### NetworkTopology

```python
@dataclass
class NetworkTopology:
    nodes: list[NFNode]
    edges: list[NFEdge]
    phase: str           # "ready" | "partial" | "down" — reuse existing logic
    timestamp: float     # time.time() of snapshot

    def neighbors(self, node_id: str) -> list[str]:
        """Return all node IDs directly connected to the given node."""

    def edges_for(self, node_id: str) -> list[NFEdge]:
        """Return all edges connected to the given node."""

    def path_between(self, src: str, dst: str) -> list[NFEdge] | None:
        """BFS shortest path between two nodes. Returns edge list or None."""

    def impact_of(self, node_id: str) -> dict:
        """Return affected edges and downstream nodes if this node goes down.
        Useful for AI agent impact analysis."""
```

> **Design for agent integration:** The `NetworkTopology` class exposes graph
> query methods (`neighbors`, `edges_for`, `path_between`, `impact_of`) so
> the AI troubleshooting agent can import `topology.py` and reason about the
> network structurally — e.g., "SMF is down → N4 (PFCP) to UPF is broken →
> no PDU sessions can be established." These methods are part of the v1 data
> model; the agent tool that consumes them is a v2 deliverable.

### Health Derivation

For v1, health maps directly from container status:

| Container Status | Health    |
|------------------|-----------|
| running          | healthy   |
| exited           | down      |
| absent           | down      |

Future enrichment (out of scope for v1):

- **gNB**: grep logs for "NG Setup procedure is successful"
- **UEs**: grep logs for "registration success" → "registered" vs "attaching"
- **AMF**: check NGAP association state
- **IMS NFs**: check Diameter peer status

---

## 2. Topology Definition: Dynamic Nodes, Static Edges

### Node Discovery

Nodes are **discovered at query time** from Docker, not hardcoded. This
supports multiple use cases (VoNR, VoLTE, future scenarios) without code
changes — the topology automatically reflects whatever containers are running.

The approach:

1. **Known NF Type dictionary** — maps container name patterns to NF metadata.
   This is the registry of every NF the system knows how to render:

   ```python
   _KNOWN_NF_TYPES = {
       # pattern     → (label, layer, role, ip_env_key, protocols, grid_pos)
       "amf":        ("AMF", "core", "access-mobility", "AMF_IP", ["SBI","NGAP"], (ROW_CORE, 5)),
       "smf":        ("SMF", "core", "session-management", "SMF_IP", ["SBI","PFCP"], (ROW_CORE, 6)),
       "upf":        ("UPF (PSA)", "core", "user-plane-anchor", "UPF_IP", ["PFCP","GTP-U"], (ROW_CORE, 7)),
       "pcscf":      ("P-CSCF", "ims", "sip-edge-proxy", "PCSCF_IP", ["SIP","Diameter"], (ROW_IMS, 2)),
       "nr_gnb":     ("gNB", "ran", "radio-access", "GNB_IP", ["NGAP","GTP-U"], (ROW_RAN, 5)),
       "e2e_ue1":    ("UE1", "ue", "subscriber", "UE1_IP", ["NAS","SIP"], (ROW_UE, 4)),
       "e2e_ue2":    ("UE2", "ue", "subscriber", "UE2_IP", ["NAS","SIP"], (ROW_UE, 6)),
       # ... all known NF types
   }
   ```

2. **Discovery at query time** — `build_topology()` runs `docker ps` to get
   the list of running containers, matches each name against `_KNOWN_NF_TYPES`,
   and builds `NFNode` instances only for containers that are present. Unknown
   containers are silently ignored.

3. **Edge filtering** — after discovering nodes, the static edge list is
   filtered to only include edges where **both endpoints exist** in the
   discovered node set. This means if you're running a VoLTE stack without
   UERANSIM containers, the gNB/UE edges and N2/N3 edges disappear
   automatically.

4. **Grid position fallback** — if a discovered container matches a known type
   but has an unexpected name variant (e.g., `volte_ue1` instead of `e2e_ue1`),
   it uses the grid position from the matching NF type. If an NF type appears
   multiple times (e.g., two UPFs), additional instances are placed in adjacent
   slots.

### Static Edges

Edges are **hardcoded** in `topology.py` as a constant list. Rationale:

- `depends_on` in compose captures startup order, not protocol relationships
- 3GPP interfaces are domain knowledge that doesn't change unless NFs are added
- Hardcoding is greppable, debuggable, and self-documenting
- A config file adds indirection for something that changes extremely rarely

### Complete Edge Inventory (40 edges)

#### RAN / Air Interface

| Source   | Target | Protocol | Interface | Plane   | Label              |
|----------|--------|----------|-----------|---------|--------------------|
| e2e_ue1  | nr_gnb | NR-Uu    | Uu        | data    | Air Interface      |
| e2e_ue2  | nr_gnb | NR-Uu    | Uu        | data    | Air Interface      |

#### N1 NAS (Logical Interface)

| Source   | Target | Protocol | Interface | Plane   | Label              |
|----------|--------|----------|-----------|---------|--------------------|
| e2e_ue1  | amf    | NAS      | N1        | control | N1 (NAS)           |
| e2e_ue2  | amf    | NAS      | N1        | control | N1 (NAS)           |

> **Note:** N1 is a *logical* interface — NAS signaling between UE and AMF is
> physically carried inside NGAP over the N2 interface through the gNB. The gNB
> is transparent to NAS messages; it encapsulates/decapsulates them without
> interpreting the content. This edge is rendered as a faint curved dashed line
> to visually distinguish it from physical connections. For learners, this is
> one of the most important concepts to grasp: the UE and AMF have a direct
> logical relationship even though every message transits the gNB.

#### 3GPP Reference Points

| Source | Target | Protocol | Interface | Plane   | Label              |
|--------|--------|----------|-----------|---------|--------------------|
| nr_gnb | amf    | NGAP     | N2        | control | N2 (NGAP)          |
| nr_gnb | upf    | GTP-U    | N3        | data    | N3 (GTP-U)         |
| smf    | upf    | PFCP     | N4        | control | N4 (PFCP)          |

#### 5G Core SBI (Service Bus)

In 3GPP's Service-Based Architecture, all core NFs communicate via the SBI
through the NRF (discovery) and SCP (routing proxy). Rather than drawing 12
individual edges (one per NF to NRF and one per NF to SCP), the visualization
uses a **Service Bus** pattern: a single horizontal line representing the SBI,
with short vertical stubs connecting each core NF to the bus. NRF and SCP sit
on the bus itself as the infrastructure nodes.

This matches the standard 3GPP SBA diagram style and avoids visual spaghetti.

**NFs connected to the SBI bus:**

| NF   | SBI Services                                        |
|------|-----------------------------------------------------|
| AMF  | Namf (registration, mobility, N1/N2 termination)    |
| SMF  | Nsmf (session management, N4 control)               |
| AUSF | Nausf (authentication)                              |
| UDM  | Nudm (subscriber data management)                   |
| UDR  | Nudr (data repository)                              |
| PCF  | Npcf (policy and charging)                          |
| NRF  | Nnrf (discovery, registration) — bus infrastructure |
| SCP  | Service Communication Proxy — bus infrastructure    |

The underlying edges still exist in the data model for graph queries:

| Source | Target | Protocol | Interface | Plane   | Label              |
|--------|--------|----------|-----------|---------|--------------------|
| amf    | nrf    | SBI      | Nnrf     | control | SBI (NRF)          |
| amf    | scp    | SBI      | —        | control | SBI (SCP)          |
| smf    | nrf    | SBI      | Nnrf     | control | SBI (NRF)          |
| smf    | scp    | SBI      | —        | control | SBI (SCP)          |
| ausf   | nrf    | SBI      | Nnrf     | control | SBI (NRF)          |
| ausf   | scp    | SBI      | —        | control | SBI (SCP)          |
| udm    | nrf    | SBI      | Nnrf     | control | SBI (NRF)          |
| udm    | scp    | SBI      | —        | control | SBI (SCP)          |
| udr    | nrf    | SBI      | Nnrf     | control | SBI (NRF)          |
| udr    | scp    | SBI      | —        | control | SBI (SCP)          |
| pcf    | nrf    | SBI      | Nnrf     | control | SBI (NRF)          |
| pcf    | scp    | SBI      | —        | control | SBI (SCP)          |

#### IMS Signaling (SIP)

| Source   | Target | Protocol | Interface | Plane     | Label              |
|----------|--------|----------|-----------|-----------|--------------------|
| e2e_ue1  | pcscf  | SIP      | Gm        | signaling | Gm (SIP)           |
| e2e_ue2  | pcscf  | SIP      | Gm        | signaling | Gm (SIP)           |
| pcscf    | icscf  | SIP      | Mw        | signaling | Mw (SIP)           |
| pcscf    | scscf  | SIP      | Mw        | signaling | Mw (SIP)           |
| icscf    | scscf  | SIP      | Mw        | signaling | Mw (SIP)           |

#### Diameter

| Source | Target | Protocol  | Interface | Plane     | Label              |
|--------|--------|-----------|-----------|-----------|--------------------|
| icscf  | pyhss  | Diameter  | Cx        | signaling | Cx (Diameter)      |
| scscf  | pyhss  | Diameter  | Cx        | signaling | Cx (Diameter)      |

#### Policy / QoS

| Source | Target | Protocol | Interface | Plane   | Label              |
|--------|--------|----------|-----------|---------|--------------------|
| pcscf  | pcf    | Diameter | Rx        | control | Rx (Diameter)      |

> **Note on Rx vs N5:** The P-CSCF supports two paths to the PCF for QoS/policy:
> **Diameter Rx** (legacy, enabled in our e2e config via `WITH_RX`) and **N5
> HTTP/2** (5G-native, disabled via `WITH_N5`). When Rx is used, the P-CSCF
> connects to the PCF acting in its combined PCRF/PCF role via Diameter on
> `PCRF_BIND_PORT`. When N5 is enabled instead, the P-CSCF registers as an
> Application Function (AF) with the NRF via SCP using HTTP/2 and communicates
> with the PCF over the SBI. In commercial 5G SA networks, the N5 path is the
> target architecture; Rx is the 4G/EPC-era interface retained for
> interworking.

#### Media

| Source    | Target    | Protocol | Interface | Plane   | Label              |
|-----------|-----------|----------|-----------|---------|---------------------|
| upf       | rtpengine | RTP      | —         | data    | RTP Media           |
| rtpengine | upf       | RTP      | —         | data    | RTP Media           |
| pcscf     | rtpengine | ng       | —         | control | RTPEngine Control   |

The full media path for a VoNR call is:

```
UE1 → gNB → UPF → RTPEngine → UPF → gNB → UE2
         (N3/GTP-U)    (RTP)      (RTP)    (N3/GTP-U)
```

UPF is the data plane anchor for the IMS PDU session. After GTP-U
decapsulation, it forwards RTP packets to RTPEngine on the Docker network.
RTPEngine relays the media back through UPF (re-encapsulated via GTP-U)
to reach the other UE. The two directional edges (upf→rtpengine and
rtpengine→upf) represent the originated and terminated media legs.

> **Note on the ng control protocol:** The `ng` protocol between P-CSCF and
> RTPEngine is a UDP-based text protocol (port 2223) specific to RTPEngine. It
> carries SDP manipulation commands (`offer`, `answer`, `delete`) that tell
> RTPEngine to allocate relay ports and rewrite SDP so media flows through it.
> This is **not a 3GPP standard**. In commercial IMS deployments (Nokia,
> Ericsson, etc.), the P-CSCF and media relay are typically integrated into a
> single SBC (Session Border Controller) product — no external control protocol
> is needed. When the media plane is on a separate node, the standard protocol
> is **H.248/MEGACO** (ITU-T Rec. H.248 / IETF RFC 3525), used on the 3GPP Mn
> interface (MRFC→MRFP, MGCF→IMS-MGW). H.248 is a transaction-based protocol
> for managing media gateway contexts and terminations — conceptually similar to
> what ng does, but standardized and designed for carrier-grade reliability.
> RTPEngine's ng protocol is a pragmatic open-source substitute.

#### Data Stores

| Source | Target | Protocol | Interface | Plane      | Label              |
|--------|--------|----------|-----------|------------|--------------------|
| udr    | mongo  | MongoDB  | —         | management | MongoDB            |
| pcf    | mongo  | MongoDB  | —         | management | MongoDB            |
| pyhss  | mysql  | SQL      | —         | management | MySQL              |
| icscf  | mysql  | SQL      | —         | management | MySQL              |
| scscf  | mysql  | SQL      | —         | management | MySQL              |
| pcscf  | mysql  | SQL      | —         | management | MySQL              |

#### DNS

| Source | Target | Protocol | Interface | Plane      | Label              |
|--------|--------|----------|-----------|------------|--------------------|
| pyhss  | dns    | DNS      | —         | management | DNS                |
| icscf  | dns    | DNS      | —         | management | DNS                |
| scscf  | dns    | DNS      | —         | management | DNS                |
| pcscf  | dns    | DNS      | —         | management | DNS                |

### Data Structure

```python
_STATIC_EDGES = [
    # (source, target, protocol, interface, plane, label)
    ("e2e_ue1", "nr_gnb", "NR-Uu", "Uu",   "data",      "Air Interface"),
    ("e2e_ue2", "nr_gnb", "NR-Uu", "Uu",   "data",      "Air Interface"),
    ("nr_gnb",  "amf",    "NGAP",  "N2",   "control",   "N2 (NGAP)"),
    ("nr_gnb",  "upf",    "GTP-U", "N3",   "data",      "N3 (GTP-U)"),
    ("smf",     "upf",    "PFCP",  "N4",   "control",   "N4 (PFCP)"),
    # ... all 40 edges (including 2 logical N1 NAS edges)
]
```

---

## 3. Backend API

### New Endpoint: `GET /api/topology`

Added to `server.py`. Returns `NetworkTopology` as JSON.

Flow:
1. Run `docker ps -a --format '{{.Names}}'` to discover all containers
   (running + stopped/exited). This captures containers that were deployed
   but crashed — they need to show up dimmed, not disappear.
2. Match each container name against `_KNOWN_NF_TYPES`. Unknown containers
   (prometheus, grafana, etc.) are silently ignored.
3. For each matched container, query status via `docker inspect`. Build
   `NFNode` with live status/health.
4. NF types that exist in `_KNOWN_NF_TYPES` but have **no matching container**
   (running or stopped) are **excluded entirely** — they are not relevant to
   the current deployment. This means a VoNR stack shows VoNR nodes; a VoLTE
   stack shows VoLTE nodes; no confusing placeholders for NFs from other use
   cases.
5. Filter `_STATIC_EDGES` to only include edges where both endpoints exist in
   the discovered node set. Set `active = True` when both are running.
6. Compute `phase` using existing logic.
7. Return via `dataclasses.asdict()`.

**Summary of node visibility rules:**

| Container State                        | In Topology? | Appearance          |
|----------------------------------------|-------------|---------------------|
| Running                                | Yes         | Full color, healthy |
| Stopped / exited (was deployed)        | Yes         | Dimmed, status=down |
| Never deployed (no container exists)   | No          | Not shown           |
| Exists but not in `_KNOWN_NF_TYPES`    | No          | Not shown           |

### Polling vs WebSocket

**Use polling** (not WebSocket). Rationale:
- Container status changes slowly (seconds to minutes)
- Existing pattern uses `setInterval(pollStatus, 5000)` — proven and simple
- Topology payload is ~2-3 KB — no performance concern
- WebSocket adds reconnection/heartbeat complexity for minimal gain in a learning tool

### IP Address Resolution

Node IPs come from the `_env` dict already loaded in `server.py` (merges `.env`
and `e2e.env`). The topology builder receives `_env` and extracts IPs by the
existing naming convention (`AMF_IP`, `NRF_IP`, `UE1_IP`, etc.).

### Relationship to Existing `/api/status`

`/api/topology` returns a superset of `/api/status` (phase + per-container
status + graph structure). Both endpoints coexist; the existing status polling
continues unchanged. Migration to a single endpoint is a future cleanup.

---

## 4. Frontend Visualization

### Rendering: SVG

Use **SVG** (not Canvas). Rationale:
- SVG elements are DOM nodes — CSS styling, hover events, tooltips, and
  transitions work for free
- 20 nodes / 40 edges is trivially small — no performance concern
- Integrates with existing CSS custom properties (`--green`, `--red`, etc.)
- Canvas would require a custom event system and hit testing — overkill

### Layout: Grid Coordinate System

Use **predefined positions** (not force-directed). Rationale:
- The VoNR stack has a natural layered hierarchy
- Consistency aids learning — AMF is always in the same place
- Force-directed layouts produce unpredictable results for hierarchical networks
- No physics library needed — zero-dependency vanilla JS maintained

Positions use a **row/slot grid system** rather than raw percentages. The
renderer computes pixel positions from `(row, slot)` coordinates based on
the SVG viewBox dimensions. This makes the layout readable, maintainable,
and easy to adjust when adding or moving nodes.

```python
# Row definitions (top to bottom)
ROW_DATA = 0    # Data stores
ROW_CORE = 1    # 5G Core NFs + SBI bus
ROW_IMS  = 2    # IMS NFs
ROW_RAN  = 3    # gNB
ROW_UE   = 4    # UEs

# Node positions: (row, slot) — slot is the horizontal position within the row
_NODE_POSITIONS = {
    # Row 0: Data
    "mongo":     (ROW_DATA, 1),
    "mysql":     (ROW_DATA, 3),
    "dns":       (ROW_DATA, 5),

    # Row 1: 5G Core (SBI bus runs horizontally through this row)
    "nrf":       (ROW_CORE, 0),
    "scp":       (ROW_CORE, 1),
    "ausf":      (ROW_CORE, 2),
    "udm":       (ROW_CORE, 3),
    "udr":       (ROW_CORE, 4),
    "amf":       (ROW_CORE, 5),
    "smf":       (ROW_CORE, 6),
    "upf":       (ROW_CORE, 7),
    "pcf":       (ROW_CORE, 8),

    # Row 2: IMS
    "pcscf":     (ROW_IMS, 2),
    "icscf":     (ROW_IMS, 4),
    "scscf":     (ROW_IMS, 5),
    "pyhss":     (ROW_IMS, 7),
    "rtpengine": (ROW_IMS, 3),

    # Row 3: RAN
    "nr_gnb":    (ROW_RAN, 5),

    # Row 4: UEs
    "e2e_ue1":   (ROW_UE, 4),
    "e2e_ue2":   (ROW_UE, 6),
}
```

The renderer converts `(row, slot)` to SVG coordinates:
```javascript
function gridToSvg(row, slot, viewBox) {
  const rowCount = 5, slotCount = 9;
  const x = (slot + 0.5) / slotCount * viewBox.width;
  const y = (row + 0.5) / rowCount * viewBox.height;
  return { x, y };
}
```

### Node Rendering

Each node is an SVG `<g>` group:
- `<rect>` with rounded corners (rx=8) — fill based on status, border based on layer
- `<text>` label (e.g. "AMF")
- `<text>` sublabel for nodes with dual roles (e.g. UPF shows "PSA" — PDU
  Session Anchor — to clarify its role as the data plane anchor where GTP-U
  terminates and traffic enters the IMS/internet)
- `<circle>` status indicator dot

**Layer colors** (using existing CSS properties):

| Layer | Border Color          |
|-------|-----------------------|
| Core  | `--accent` (#4f8ff7)  |
| IMS   | `--cyan` (#26c6da)    |
| RAN   | `--purple` (#ab47bc)  |
| UE    | `--green` (#4caf50)   |
| Data  | `--text-dim` (#8b90a5)|

**Status indicator**:

| Health  | Color                 |
|---------|-----------------------|
| healthy | `--green` (#4caf50)   |
| down    | `--red` (#ef5350)     |
| degraded| `--orange` (#ff9800)  |

**Node fill**: `--surface2` when running, `--surface` with reduced opacity when down.

### Edge Rendering

Each edge is an SVG `<path>` (curved to avoid overlap).

**Edge styling by plane**:

| Plane      | Style     | Color                 |
|------------|-----------|-----------------------|
| control    | solid     | `--accent` (#4f8ff7)  |
| data       | dashed    | `--green` (#4caf50)   |
| signaling  | dotted    | `--cyan` (#26c6da)    |
| management | thin solid| `--text-dim` (#8b90a5)|

**Edge opacity**: 100% when `active == true`, 30% when inactive (one or both
endpoints down).

### Interactivity

- **Hover node**: highlight all connected edges, show tooltip with container
  name, IP, status, health, protocols
- **Hover edge**: show tooltip with protocol, interface name, plane type
- **Click node**: open log viewer for that container (reuses existing
  `/ws/logs/{container}` WebSocket)
- **Status transitions**: 0.5s CSS transition on fill/stroke for smooth updates

### Frontend Layout

Expand the main grid from 2 rows to 3:

```
grid-template-columns: 1fr 1fr;
grid-template-rows: auto auto 1fr;
```

| Row | Content                                  |
|-----|------------------------------------------|
| 1   | Stack controls (existing, full width)    |
| 2   | Topology view (new, full width, ~400px)  |
| 3   | UE1 panel (left) + UE2 panel (right)     |

The topology panel is collapsible with a toggle button. Default: expanded.

### Legend and Plane Filters

The legend doubles as a **plane filter control**. Each plane type is a
clickable toggle that shows/hides edges of that type. This lets users
isolate specific views — e.g., show only SIP signaling to trace a call
flow, or only data plane to understand the media path.

Implementation: edges are grouped by plane using `data-plane` attributes
on SVG `<g>` groups. Toggling a filter adds/removes a CSS class that sets
`display: none` on the group. All planes are visible by default.

```
Legend / Filters:
  [✓] Control    (solid blue)    — NGAP, SBI, PFCP, N5/Rx, ng
  [✓] Data       (dashed green)  — GTP-U, RTP, Uu
  [✓] Signaling  (dotted cyan)   — SIP, Diameter
  [✓] Management (thin gray)     — DNS, MongoDB, MySQL
  ●  Healthy   ●  Down   ●  Degraded
```

---

## 5. Implementation Sequence

| Step | What                                                              | Est. |
|------|-------------------------------------------------------------------|------|
| 1    | `topology.py` — dataclasses (with graph query methods), Known NF Type dictionary, Docker discovery logic, edge defs (incl. N1 logical + SBI bus flag), grid positions, `build_topology()` | ~3h |
| 2    | `server.py` — add `GET /api/topology` endpoint                   | ~30m |
| 3    | `index.html` — SVG panel HTML/CSS, `renderTopology()` JS with SBI bus rendering, grid-to-SVG layout, PSA sublabel on UPF, N1 as faint dashed curve | ~3.5h |
| 4    | Polling integration + smooth CSS transitions                      | ~1h  |
| 5    | Plane filter toggles (legend as control), hover/click interactivity, tooltips | ~2.5h |

---

## 6. Integration with Existing Flows

### Deploy / Teardown

The topology view reflects changes automatically via the 5-second poll.
The existing `pollStatus()` call after deploy/teardown completion also
triggers a topology refresh. No special integration needed.

### Log Viewing

Clicking a node opens a log viewer for any container (not just UEs). The
backend already has `/ws/logs/{container}` that works for any container name.
The topology click handler opens a lightweight modal reusing the existing
log-streaming WebSocket pattern.

---

## 7. Out of Scope (Future Enhancements)

- **Log-based health enrichment** — gNB NGAP state, IMS registration per UE,
  Diameter peer status
- **Procedure Gallery** — selectable 3GPP procedures (Registration, VoNR Call
  Setup, PDU Session Establishment) that highlight the specific sequence of
  edges involved, with step-by-step animation. Requires modeling the exact
  message flow for each procedure. High educational value but significant scope.
- **Call flow animation** — highlight the SIP signaling path during an active
  VoNR call with animated dots
- **Click-to-restart** — right-click a node to restart the container
- **Per-edge traffic indicators** — animate edges when traffic is flowing
- **Export topology as PNG/SVG** — for documentation
- **Agent topology tool** — add a `read_topology` tool to the AI agent that
  calls `topology.impact_of()` and `topology.path_between()` for structural
  reasoning during investigations (the data model and query methods are built
  in v1; the agent tool wrapper is v2)

## 8. Gemini Review Disposition

| # | Suggestion | Verdict | Notes |
|---|-----------|---------|-------|
| 1.1 | SBI Service Bus | **Accepted** | Bus visualization for SBI; individual edges kept in data model for graph queries |
| 1.2 | Dynamic Node Discovery | **Accepted** | Nodes discovered from Docker at query time; edges filtered to match discovered nodes; supports VoLTE and future use cases |
| 1.3 | N1 NAS Logical Link | **Accepted** | Added 2 logical edges; rendered as faint dashed curve |
| 1.4 | PSA Label on UPF | **Accepted** | UPF node shows "PSA" sublabel |
| 1.5 | Plane-Based Filtering | **Accepted** | Legend toggles show/hide edges by plane via CSS classes |
| 1.6 | Grid Coordinates | **Accepted** | Row/slot system replaces raw percentages |
| 1.7 | Procedure Gallery | **Deferred to v2** | High value but significant scope; listed in future enhancements |
| 1.8 | AI Agent Integration | **Accepted as design constraint** | Graph query methods in v1 data model; agent tool wrapper in v2 |

