# UPF GTP Packet Counter Fix

**Date:** 2026-03-24
**Status:** Implementing Option A (re-enable at build time)

---

## The Problem

The UPF's Prometheus metrics `fivegs_ep_n3_gtp_indatapktn3upf` and `fivegs_ep_n3_gtp_outdatapktn3upf` always report `0`, even during active VoNR calls with real RTP traffic flowing through the GTP tunnels.

This was discovered during a live call test where raw interface counters on `ogstun2` showed ~46 packets/sec in each direction, but the Prometheus metrics stayed at zero.

### Impact

1. **Agents are misled.** Every troubleshooting agent (v1, v2, v3) sees GTP=0 in triage and concludes the data plane is broken. This is a permanent red herring that has derailed every investigation run to date — the agents fixate on a "dead data plane" that is actually healthy.

2. **Evaluation plan blocked.** Scenario 2.3 (Data Plane Degradation — 20% packet loss on UPF GTP interface) cannot work because the baseline metric is always 0. We can't measure degradation from zero.

3. **Operational blind spot.** Any real data plane failure would be invisible in Prometheus — you'd see 0 whether 50 packets/sec or 0 packets/sec are flowing.

---

## Root Cause

In Open5GS source (`src/upf/gtp-path.c`, commit `782a97ef`), the counter increments are wrapped in `#if 0` preprocessor blocks:

**Block 1 — Outgoing packets (line ~242, in `_gtpv1_tun_recv_common_cb`):**
```c
#if 0
    upf_metrics_inst_global_inc(UPF_METR_GLOB_CTR_GTP_OUTDATAPKTN3UPF);
    upf_metrics_inst_by_qfi_add(pdr->qer->qfi,
        UPF_METR_CTR_GTP_OUTDATAVOLUMEQOSLEVELN3UPF, recvbuf->len);
#endif
```

**Block 2 — Incoming packets (line ~483, in `_gtpv1_u_recv_cb`):**
```c
#if 0
        upf_metrics_inst_global_inc(UPF_METR_GLOB_CTR_GTP_INDATAPKTN3UPF);
        upf_metrics_inst_by_qfi_add(header_desc.qos_flow_identifier,
                UPF_METR_CTR_GTP_INDATAVOLUMEQOSLEVELN3UPF, pkbuf->len);
#endif
```

Both blocks reference GitHub Issue #2210, Discussion #2208/#2209. The Prometheus client library uses `malloc/free` on every counter increment. In high-throughput production environments (multi-Gbps), this causes 700 Mbps–1 Gbps throughput loss due to memory allocation contention.

The Open5GS maintainer disabled the counters in PR #2219 (April 2023) and considers this a permanent trade-off for production deployments.

---

## Options Considered

### Option A: Re-enable counters at build time (SELECTED)

Patch `gtp-path.c` during Docker build to change `#if 0` to `#if 1`.

- **Pros:** One-line sed, uses Open5GS's own counter infrastructure, zero code risk.
- **Cons:** Requires image rebuild. Not suitable for production multi-Gbps UPFs.
- **Performance impact in our environment:** Negligible. Our lab traffic is ~50 packets/sec during a VoNR call. The malloc contention that caused the upstream issue only manifests at millions of packets/sec.

### Option B: Atomic counters with periodic Prometheus flush

Replace per-packet Prometheus calls with `atomic_fetch_add` and flush to Prometheus on a timer (every 5s).

- **Pros:** Solves the upstream performance issue properly. Could be contributed back.
- **Cons:** More code to write and maintain. Needs timer callback integration with Open5GS event loop.
- **Verdict:** Good future upstream contribution, overkill for our lab.

### Option C: Sidecar metrics exporter reading /proc/net/dev

Separate container that scrapes TUN interface byte/packet counters and exposes them as Prometheus metrics.

- **Pros:** No image rebuild needed.
- **Cons:** Measures TUN packets, not GTP-U packets specifically. Adds container complexity. Doesn't fix the actual metric.
- **Verdict:** Workaround, not a fix.

---

## Decision: Option A

We re-enable the counters by patching the source during the Docker build. The `sed` command changes `#if 0` to `#if 1` in both locations in `src/upf/gtp-path.c` before compilation.

### Change Made

In `base/Dockerfile`, the Open5GS build step is modified to include the patch:

```dockerfile
RUN git clone --recursive https://github.com/open5gs/open5gs && cd open5gs && \
    git checkout 782a97efe9e3acb1251e318bd3738ced4044dac8 && \
    sed -i '/Metrics reduce data plane performance/,/^#endif/{s/^#if 0/#if 1/}' src/upf/gtp-path.c && \
    meson build --prefix=`pwd`/install && \
    ninja -C build && cd build && ninja install && \
    mkdir -p /open5gs/install/include
```

The `sed` command targets only the two `#if 0` blocks that contain the "Metrics reduce data plane performance" comment, changing them to `#if 1`. All other `#if 0` blocks in the file (if any) are unaffected.

### Verification

After rebuilding and redeploying, during an active VoNR call:
- `fivegs_ep_n3_gtp_indatapktn3upf` should increment (~50/sec)
- `fivegs_ep_n3_gtp_outdatapktn3upf` should increment (~50/sec)
- These should match the raw `ogstun2` packet counters from `/proc/net/dev`

### Upstream Reference

- **Issue:** https://github.com/open5gs/open5gs/issues/2210
- **Discussions:** #2208, #2209
- **Disabling PR:** https://github.com/open5gs/open5gs/pull/2219
- **Commit pinned in our build:** `782a97efe9e3acb1251e318bd3738ced4044dac8`
