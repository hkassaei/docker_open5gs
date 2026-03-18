# Plan: Subscriber Count Metrics

## Context
The topology view shows metrics badges on NFs (AMF: "2 UE", SMF: "4 PDU", etc.) but has no subscriber count metrics for the data layer (MongoDB, MySQL) or subscriber-management NFs (UDR, PyHSS). The user wants to see provisioned subscriber counts for both the 5G core and IMS sides.

---

## Option A: Query Databases Directly (MongoDB + MySQL)

### 5G Core — MongoDB
- **Command**: `docker exec mongo mongosh --quiet --eval "db.subscribers.countDocuments()" open5gs`
- **Verified**: Returns `2` (the two provisioned UEs)
- **Implementation**: `docker exec` from MetricsCollector, same pattern as Kamailio kamcmd
- **What it measures**: Total provisioned subscriber profiles (IMSI, keys, APNs, slices)

### IMS — MySQL
- **Command**: `docker exec mysql mysql -u root -ppassword -N -e "SELECT COUNT(*) FROM ims_hss_db.ims_subscriber;"`
- **Verified**: Returns `2`
- **Implementation**: `docker exec` from MetricsCollector
- **What it measures**: Total provisioned IMS subscriber profiles

### Pros
- **Ground truth** — counts what's actually stored, no indirection
- **Always available** — databases are always running if the stack is up
- **Fast** — simple count queries, ~50ms each
- **No dependency on NF health** — even if UDR or PyHSS crashes, the DB still answers

### Cons
- **Bypasses the NF layer** — you're reading storage directly, not going through the 3GPP architecture
- **Doesn't tell you NF health** — 2 subscribers in the DB doesn't mean 2 subscribers are actually *usable* (PyHSS or UDR could be broken)
- **Couples to schema** — if the DB schema changes, the query breaks

---

## Option B: Query Network Functions (UDR for 5G, PyHSS REST API for IMS)

### 5G Core — UDR/UDM
- **Prometheus at :9091**: Neither UDR nor UDM expose a metrics port. Port 9091 is not open on either container.
- **SBI API (HTTP/2 on :7777)**: UDM responds — e.g., `GET /nudm-sdm/v2/imsi-001011234567891/am-data` returns that subscriber's access & mobility data. **However**, the 3GPP SBI spec is strictly per-IMSI. There is no "list all" or "count" endpoint. You must already know the IMSI to query. UDR's `/nudr-dr/v1/subscription-data` is the same.
- **Conclusion**: UDR/UDM cannot provide subscriber counts. This is a 3GPP spec limitation, not an Open5GS limitation.

### IMS — PyHSS REST API
- **Endpoint**: `GET http://172.22.0.18:8080/ims_subscriber/list`
- **Verified**: Returns JSON array of 2 subscriber objects with full IMS profile data (IMSI, MSISDN, assigned S-CSCF, iFC, etc.)
- **Implementation**: HTTP GET from MetricsCollector (aiohttp), same pattern already partially implemented in `_collect_pyhss()`
- **Current bug**: The existing code queries `/auc/` (wrong endpoint) with the wrong IP (`172.22.0.34` hardcoded default instead of `172.22.0.18` from .env)

### Pros
- **Architecturally correct** — queries the NF that *owns* the data, through its intended API
- **Richer data** — PyHSS response includes registration state (which S-CSCF is assigned), not just count
- **NF health signal** — if PyHSS responds, you know it's healthy

### Cons
- **UDR has no usable API for this** — the 3GPP SBI spec doesn't support "list all subscribers". Dead end for the 5G core side.
- **PyHSS API returns full objects** — to count subscribers, you fetch all subscriber records and count them. Fine for 2 subscribers, wasteful for thousands.
- **Single point of failure** — if PyHSS is down, you get no IMS subscriber count

---

## Recommendation: Hybrid (DB for 5G core, PyHSS API for IMS)

Since UDR/UDM expose no subscriber count interface, the 5G core side **must** use MongoDB. For the IMS side, PyHSS REST API is the better choice — it's already partially wired up, gives richer data, and validates NF health.

### Changes to `operate/gui/metrics.py`:

1. **Add `_collect_mongo()`** — new method using `docker exec mongo mongosh` to count subscribers. Badge on MongoDB node: `"2 subs"`.

2. **Fix `_collect_pyhss()`** — change endpoint from `/auc/` to `/ims_subscriber/list`, fix the default PYHSS_IP to match .env (`172.22.0.18`). Badge on PyHSS node: `"2 subs"`.

3. **Wire into `collect()`** — add mongo result to merged dict.

### Files to modify:
- `operate/gui/metrics.py` — add `_collect_mongo()`, fix `_collect_pyhss()`

### Verification:
- Run the MetricsCollector test script to confirm both return subscriber counts
- Restart server, check topology badges on MongoDB and HSS nodes
