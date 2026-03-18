"""
Metrics Collector — Prometheus + IMS Stats

Queries Prometheus HTTP API for Open5GS NF metrics (AMF, SMF, UPF, PCF)
and collects IMS component stats via docker exec (Kamailio kamcmd,
RTPEngine rtpengine-ctl) and PyHSS REST API.

Results are cached with a 5-second TTL matching the Prometheus scrape
interval.  A rolling history window is kept for sparkline rendering.

Consumed by server.py (GET /api/metrics, GET /api/metrics/history/{node}).
"""

import asyncio
import logging
import time

import aiohttp

log = logging.getLogger("vonr-metrics")

CACHE_TTL = 5        # seconds — matches Prometheus scrape_interval
HISTORY_LEN = 60     # snapshots  (60 × 5 s = 5 min)


class MetricsCollector:
    """Collects and caches metrics from Prometheus and IMS containers."""

    def __init__(self, env: dict[str, str]):
        self._env = env
        self._prom = f"http://{env.get('METRICS_IP', '172.22.0.36')}:9090"
        self._pyhss = f"http://{env.get('PYHSS_IP', '172.22.0.18')}:8080"
        self._cache: dict[str, dict] = {}
        self._cache_ts: float = 0.0
        self._history: dict[str, list[dict]] = {}

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    async def collect(self) -> dict[str, dict]:
        """Return per-node metrics dict, using cache if still fresh."""
        now = time.time()
        if now - self._cache_ts < CACHE_TTL and self._cache:
            return self._cache

        results = await asyncio.gather(
            self._collect_prometheus(),
            self._collect_kamailio("pcscf"),
            self._collect_kamailio("icscf"),
            self._collect_kamailio("scscf"),
            self._collect_rtpengine(),
            self._collect_pyhss(),
            self._collect_mongo(),
            return_exceptions=True,
        )

        merged: dict[str, dict] = {}

        # Prometheus (returns dict of node_id → data)
        if isinstance(results[0], dict):
            merged.update(results[0])

        # Kamailio CSCFs
        for i, name in enumerate(["pcscf", "icscf", "scscf"], 1):
            if isinstance(results[i], dict) and results[i].get("metrics"):
                merged[name] = results[i]

        # RTPEngine
        if isinstance(results[4], dict) and results[4].get("metrics"):
            merged["rtpengine"] = results[4]

        # PyHSS
        if isinstance(results[5], dict) and results[5].get("metrics"):
            merged["pyhss"] = results[5]

        # MongoDB
        if isinstance(results[6], dict) and results[6].get("metrics"):
            merged["mongo"] = results[6]

        # Append to history
        for nid, data in merged.items():
            hist = self._history.setdefault(nid, [])
            hist.append({**data.get("metrics", {}), "_t": now})
            if len(hist) > HISTORY_LEN:
                del hist[:-HISTORY_LEN]

        self._cache = merged
        self._cache_ts = now
        return merged

    def history(self, node_id: str) -> list[dict]:
        """Return metrics history for a node (for sparklines)."""
        return self._history.get(node_id, [])

    # -----------------------------------------------------------------
    # Prometheus
    # -----------------------------------------------------------------

    async def _prom_query(
        self, session: aiohttp.ClientSession, query: str
    ) -> float | None:
        """Execute a single PromQL instant query; return scalar or None."""
        try:
            async with session.get(
                f"{self._prom}/api/v1/query",
                params={"query": query},
                timeout=aiohttp.ClientTimeout(total=3),
            ) as resp:
                body = await resp.json()
                res = body.get("data", {}).get("result", [])
                if res:
                    return float(res[0]["value"][1])
        except Exception:
            pass
        return None

    async def _collect_prometheus(self) -> dict[str, dict]:
        """Query Prometheus for all Open5GS NF metrics in parallel."""
        queries = [
            # AMF
            "amf_session", "ran_ue", "gnb",
            # SMF
            "fivegs_smffunction_sm_sessionnbr",
            "ues_active", "bearers_active", "pfcp_sessions_active",
            # UPF
            "fivegs_upffunction_upf_sessionnbr",
            "fivegs_ep_n3_gtp_indatapktn3upf",
            "fivegs_ep_n3_gtp_outdatapktn3upf",
            # PCF
            "fivegs_pcffunction_pa_sessionnbr",
        ]

        out: dict[str, dict] = {}
        try:
            async with aiohttp.ClientSession() as s:
                values = await asyncio.gather(
                    *(self._prom_query(s, q) for q in queries)
                )
                r = dict(zip(queries, values))

                # ---- AMF ----
                amf_m = {k: v for k, v in r.items()
                         if k in ("amf_session", "ran_ue", "gnb") and v is not None}
                if amf_m:
                    ues = amf_m.get("ran_ue", amf_m.get("amf_session", 0))
                    out["amf"] = {
                        "metrics": amf_m,
                        "badge": f"{int(ues)} UE" if ues else "",
                        "source": "prometheus",
                    }

                # ---- SMF ----
                smf_keys = ["fivegs_smffunction_sm_sessionnbr",
                            "ues_active", "bearers_active", "pfcp_sessions_active"]
                smf_m = {k: v for k in smf_keys
                         if (v := r.get(k)) is not None}
                if smf_m:
                    sess = smf_m.get("fivegs_smffunction_sm_sessionnbr",
                                     smf_m.get("ues_active", 0))
                    out["smf"] = {
                        "metrics": smf_m,
                        "badge": f"{int(sess)} PDU" if sess else "",
                        "source": "prometheus",
                    }

                # ---- UPF ----
                upf_keys = [
                    "fivegs_upffunction_upf_sessionnbr",
                    "fivegs_ep_n3_gtp_indatapktn3upf",
                    "fivegs_ep_n3_gtp_outdatapktn3upf",
                ]
                upf_m = {k: v for k in upf_keys
                         if (v := r[k]) is not None}
                if upf_m:
                    sess = upf_m.get("fivegs_upffunction_upf_sessionnbr", 0)
                    pkts = (upf_m.get("fivegs_ep_n3_gtp_indatapktn3upf", 0)
                            + upf_m.get("fivegs_ep_n3_gtp_outdatapktn3upf", 0))
                    badge = f"{int(sess)} sess" if sess else ""
                    if not badge and pkts:
                        badge = f"{int(pkts)} pkt"
                    out["upf"] = {
                        "metrics": upf_m,
                        "badge": badge,
                        "source": "prometheus",
                    }

                # ---- PCF ----
                v = r.get("fivegs_pcffunction_pa_sessionnbr")
                if v is not None:
                    out["pcf"] = {
                        "metrics": {"pa_sessions": v},
                        "badge": f"{int(v)} PA" if v else "",
                        "source": "prometheus",
                    }

        except Exception as e:
            log.warning("Prometheus collection failed: %s", e)

        return out

    # -----------------------------------------------------------------
    # Kamailio (via docker exec kamcmd)
    # -----------------------------------------------------------------

    # Stats worth showing per Kamailio container (prefix match on raw key)
    _KAM_INTERESTING = {
        "pcscf": [
            "dialog_ng:", "ims_usrloc_pcscf:", "registrar:",
            "core:rcv_requests_register", "core:rcv_requests_invite",
            "core:rcv_requests_bye", "core:rcv_requests_options",
            "script:register_", "tmx:active_transactions",
            "sl:1xx_replies", "sl:200_replies", "sl:4xx_replies",
            "sl:5xx_replies", "httpclient:conn",
        ],
        "icscf": [
            "ims_icscf:", "core:rcv_requests_register",
            "core:rcv_requests_invite", "cdp:",
            "tmx:active_transactions",
        ],
        "scscf": [
            "dialog_ng:", "ims_registrar_scscf:", "ims_usrloc_scscf:",
            "ims_auth:", "core:rcv_requests_register",
            "core:rcv_requests_invite", "cdp:",
            "tmx:active_transactions",
        ],
    }

    async def _collect_kamailio(self, container: str) -> dict:
        """Collect Kamailio stats via kamcmd stats.get_statistics."""
        raw: dict[str, float] = {}
        badge = ""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "exec", container,
                "kamcmd", "stats.get_statistics", "all",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)

            for line in stdout.decode(errors="replace").splitlines():
                line = line.strip()
                if " = " not in line:
                    continue
                key, _, val = line.partition(" = ")
                key = key.strip()
                try:
                    raw[key] = float(val.strip())
                except ValueError:
                    pass

            # Filter to interesting stats only
            prefixes = self._KAM_INTERESTING.get(container, [])
            m = {k: v for k, v in raw.items()
                 if any(k.startswith(p) for p in prefixes)}

            # Build badge using real key names
            if container == "pcscf":
                contacts = raw.get("ims_usrloc_pcscf:registered_contacts", 0)
                dlg = raw.get("dialog_ng:active", 0)
                badge = (f"{int(contacts)} reg" if contacts
                         else f"{int(dlg)} dlg" if dlg else "")
            elif container == "scscf":
                contacts = raw.get("ims_usrloc_scscf:active_contacts", 0)
                regs = raw.get("ims_registrar_scscf:accepted_regs", 0)
                badge = (f"{int(contacts)} reg" if contacts
                         else f"{int(regs)} regs" if regs else "")
            elif container == "icscf":
                reqs = raw.get("core:rcv_requests_register", 0)
                badge = f"{int(reqs)} req" if reqs else ""

        except asyncio.TimeoutError:
            log.debug("kamcmd timeout for %s", container)
        except Exception as e:
            log.debug("kamcmd %s: %s", container, e)

        return {"metrics": m, "badge": badge, "source": "kamcmd"}

    # -----------------------------------------------------------------
    # RTPEngine (via docker exec rtpengine-ctl)
    # -----------------------------------------------------------------

    async def _collect_rtpengine(self) -> dict:
        """Collect RTPEngine session stats."""
        m: dict[str, float] = {}
        badge = ""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "exec", "rtpengine",
                "rtpengine-ctl", "list", "totals",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)

            for line in stdout.decode(errors="replace").splitlines():
                if ":" not in line:
                    continue
                key, _, val = line.rpartition(":")
                key = key.strip().lower().replace(" ", "_").replace("-", "_")
                try:
                    m[key] = float(val.strip())
                except ValueError:
                    pass

            calls = m.get("current_sessions_own",
                          m.get("current_sessions_total", 0))
            if calls:
                badge = f"{int(calls)} call{'s' if calls != 1 else ''}"

        except asyncio.TimeoutError:
            log.debug("rtpengine-ctl timeout")
        except Exception as e:
            log.debug("rtpengine-ctl: %s", e)

        return {"metrics": m, "badge": badge, "source": "rtpengine-ctl"}

    # -----------------------------------------------------------------
    # PyHSS (REST API)
    # -----------------------------------------------------------------

    async def _collect_pyhss(self) -> dict:
        """Query PyHSS REST API for IMS subscriber count."""
        m: dict[str, float] = {}
        badge = ""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._pyhss}/ims_subscriber/list",
                    timeout=aiohttp.ClientTimeout(total=3),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if isinstance(data, list):
                            m["ims_subscribers"] = len(data)
                            n = len(data)
                            badge = f"{n} sub{'s' if n != 1 else ''}"
        except Exception as e:
            log.debug("PyHSS: %s", e)

        return {"metrics": m, "badge": badge, "source": "api"}

    # -----------------------------------------------------------------
    # MongoDB (via docker exec mongosh)
    # -----------------------------------------------------------------

    async def _collect_mongo(self) -> dict:
        """Count provisioned 5G subscribers in MongoDB."""
        m: dict[str, float] = {}
        badge = ""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "exec", "mongo",
                "mongosh", "--quiet", "--eval",
                "db.subscribers.countDocuments()", "open5gs",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)

            line = stdout.decode(errors="replace").strip()
            if line.isdigit():
                n = int(line)
                m["subscribers"] = n
                badge = f"{n} sub{'s' if n != 1 else ''}"

        except asyncio.TimeoutError:
            log.debug("mongosh timeout")
        except Exception as e:
            log.debug("mongosh: %s", e)

        return {"metrics": m, "badge": badge, "source": "mongosh"}
