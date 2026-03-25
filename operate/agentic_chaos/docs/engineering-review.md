❯ /plan-eng-review

● Let me audit the current state of Phase 1A + 1B before reviewing.

● Searched for 1 pattern, read 1 file (ctrl+o to expand)

● Bash(git log --oneline -5)
  ⎿  b5dd9b8 added major capabilities to the operational dashboard and backend: integration of key metrics for every container in the dashboard, enhancement to the network topology view, and addition of s
     ubscriber count metrics to both Core and IMS
     d6810af had Claude perform an RCA on an IMS registration failure and capture the RCA, and reflections. Important takeawys for an agentic system design captured as well
     … +5 lines (ctrl+o to expand)

● Now let me read the key implementation files to review.

● Explore(Deep review of chaos code)
  ⎿  Done (30 tool uses · 79.2k tokens · 1m 30s)
  (ctrl+o to expand)

● Good, I have a thorough code review. Let me now deliver the structured plan review.

  ---
  STEP 0: Scope Challenge

  What exists already?

  ┌───────────────────────┬──────────────────────────────────────────────────────────┬───────────────────────────────────────┐
  │      Sub-problem      │                      Existing code                       │                Reused?                │
  ├───────────────────────┼──────────────────────────────────────────────────────────┼───────────────────────────────────────┤
  │ Shell execution       │ _shell() in agentic_ops/tools.py                         │ Copied (not imported) — DRY violation │
  ├───────────────────────┼──────────────────────────────────────────────────────────┼───────────────────────────────────────┤
  │ Metrics collection    │ MetricsCollector in gui/metrics.py                       │ Reused via lazy import                │
  ├───────────────────────┼──────────────────────────────────────────────────────────┼───────────────────────────────────────┤
  │ Topology/blast radius │ topology.impact_of()                                     │ Reused via lazy import                │
  ├───────────────────────┼──────────────────────────────────────────────────────────┼───────────────────────────────────────┤
  │ Container list        │ Hardcoded in topology.py, tools.py, observation_tools.py │ Duplicated 3+ times                   │
  └───────────────────────┴──────────────────────────────────────────────────────────┴───────────────────────────────────────┘

  What's the minimum set of changes?

  Phase 1A + 1B as built is already the minimum for a working chaos platform. The 3,602 lines across 27 files is justified — it includes models, 4 tool modules, 5 agents, an orchestrator, a recorder, and 7
  test files.

  Complexity check

  27 files is above the 8-file smell threshold, but this is a greenfield subsystem with clear separation of concerns. No file exceeds 325 lines. The architecture is sound.

  The review should focus on: DRY violations, security hardening, test gaps, and a few edge cases that can cause real problems.

  Given the scope (Phase 1A+1B already implemented, 84 tests passing), this is a BIG CHANGE review. The code is substantial, working, but has specific issues worth addressing before committing.

● User answered Claude's questions:
  ⎿  · Phase 1A+1B is 3,602 lines across 27 files with 84 passing tests. The code review found 8 substantive issues (1 DRY violation, 2 security gaps, 2 edge cases, 3 test gaps) plus several minor items. Which
      review depth do you want? → BIG CHANGE (Recommended)

● BIG CHANGE mode it is. Let me work through each section.

  ---
  Section 1: Architecture Review

  The overall architecture is solid — clean layering (models → tools → agents → orchestrator), good reuse of existing infrastructure (MetricsCollector, topology), and the Triple Lock safety model is
  well-designed. I found two architecture-level issues worth discussing:

● User answered Claude's questions:
  ⎿  · Issue 1: Shell injection surface. Container names and IP addresses are interpolated into shell commands without sanitization (e.g., `f"docker kill {container}"`, `f"iptables -A OUTPUT -d {target_ip} -j
     DROP"`). Currently safe because inputs come from developer-authored Scenarios, but if the GUI 'Break This' button (Phase 2) or LLM-generated scenarios (Phase 1D) ever pass user/LLM input to these tools,
     it becomes a privilege escalation vector via sudo nsenter. How should we harden this? → 1A: Validate + quote now (Recommended)

● User answered Claude's questions:
  ⎿  · Issue 2: No timeout on async operations inside agents. `snapshot_metrics()` calls `MetricsCollector.collect()` which makes HTTP calls to Prometheus, kamcmd via docker exec, and PyHSS API — any of these
     can hang indefinitely if the target is unreachable (especially during chaos!). The SymptomPoller loop and BaselineCollector have no timeout protection. If Prometheus hangs, the entire episode stalls
     forever. How should we add timeout protection? → 2A: Wrap key calls with asyncio.wait_for (Recommended)

● Architecture section complete. No other architecture issues — the layering, data flow, and ADK agent hierarchy are all well-designed.

  ---
  Section 2: Code Quality Review

● User answered Claude's questions:
  ⎿  · Issue 3: `_shell()` is copy-pasted across 4 files (docker_tools.py, network_tools.py, verification_tools.py, observation_tools.py) — identical 8-line async function in each. If we need to add timeout
     handling (from Issue 2), we'd have to patch 4 files. This is the clearest DRY violation in the codebase. Where should the shared helper live? → 3A: tools/_common.py (Recommended)

● User answered Claude's questions:
  ⎿  · Issue 4: The hardcoded container list appears 3 times — `observation_tools.py:snapshot_container_status()` (line 104), `observation_tools.py:determine_phase()` core set (line 136), and
     `agents/symptom_observer.py:_LOG_CONTAINERS` (line 33). Plus `topology.py:_KNOWN_NF_TYPES` and `agentic_ops/models.py:all_containers` have their own copies. If a new container is added (e.g., a second
     UPF), 5 places need updating. How should we consolidate? → 4A: Single constant in models.py (Recommended)

● User answered Claude's questions:
  ⎿  · Issue 5: In `fault_injector.py:244`, the network fault verification does an inline import and reaches into private functions: `from ..tools.network_tools import _shell, _nsenter`. This was a quick fix
     for the PID-reuse race condition during testing, but importing private functions (`_`-prefixed) from a sibling module is fragile and unclear. How should we clean this up? → 5A: Add verify_tc_with_pid() to
      verification_tools (Recommended)

● Code quality section complete. No other code quality issues worth a question — the remaining items (inconsistent logging levels, _run_live_impl stubs) are minor and I'll fix them as part of the
  implementation.

  ---
  Section 3: Test Review

  Here's the test coverage diagram for all new codepaths:

  NEW CODEPATHS & TEST COVERAGE
  ═══════════════════════════════════════════════════════════════════

  MODELS (models.py)
    FaultSpec construction ────────────────────── ✅ test_models.py
    Fault construction + defaults ─────────────── ✅ test_models.py
    Scenario construction (single + compound) ─── ✅ test_models.py
    Episode full assembly + JSON roundtrip ────── ✅ test_models.py
    Escalation schedule monotonicity ──────────── ✅ test_models.py
    Enum values ───────────────────────────────── ✅ test_models.py
    FaultSpec param validation ────────────────── ❌ NO TEST (invalid delay_ms, missing params)
    FaultSpec target validation ───────────────── ❌ NO TEST (unknown container names)

  FAULT REGISTRY (fault_registry.py)
    Initialize + table creation ───────────────── ✅ test_fault_registry.py
    Register / get / heal / verify / fail ─────── ✅ test_fault_registry.py
    Duplicate ID rejection ────────────────────── ✅ test_fault_registry.py
    TTL expiry detection ──────────────────────── ✅ test_fault_registry.py
    heal_all (active / empty / already healed) ── ✅ test_fault_registry.py
    Params + timestamp SQLite roundtrip ───────── ✅ test_fault_registry.py
    Emergency sync heal ──────────────────────── ✅ test_fault_registry.py
    Missing DB file handling ──────────────────── ✅ test_fault_registry.py
    TTL reaper background task ────────────────── ❌ NO TEST (reaper loop behavior)
    Heal command failure during heal_all ──────── ❌ NO TEST (what if heal cmd fails?)
    Concurrent register + heal race ───────────── ❌ NO TEST

  DOCKER TOOLS (tools/docker_tools.py)
    inspect running / absent ──────────────────── ✅ test_functional.py
    get_pid running / absent ──────────────────── ✅ test_functional.py
    pause + unpause cycle ─────────────────────── ✅ test_functional.py
    kill already-dead container ───────────────── ❌ NO TEST
    pause already-paused container ────────────── ❌ NO TEST

  NETWORK TOOLS (tools/network_tools.py)
    inject_latency + heal ─────────────────────── ✅ test_functional.py
    inject_packet_loss + heal ─────────────────── ✅ test_functional.py
    show_tc_rules ─────────────────────────────── ✅ test_functional.py
    clear on clean interface ──────────────────── ✅ test_functional.py
    inject_corruption ─────────────────────────── ❌ NO TEST
    inject_bandwidth_limit ────────────────────── ❌ NO TEST
    inject_partition ──────────────────────────── ❌ NO TEST

  VERIFICATION TOOLS (tools/verification_tools.py)
    verify_container_status (match + mismatch) ── ✅ test_functional.py
    verify_reachable ──────────────────────────── ✅ test_functional.py
    verify_latency with injection ─────────────── ✅ test_functional.py
    verify_tc_active ──────────────────────────── ✅ test_functional.py
    _parse_ping_rtt (7 variants) ──────────────── ✅ test_verification_tools.py
    verify_unreachable ────────────────────────── ❌ NO TEST (used by partition)
    verify_tc_with_pid (new, from Issue 5) ────── ❌ NEEDS TEST

  OBSERVATION TOOLS (tools/observation_tools.py)
    snapshot_metrics ──────────────────────────── ✅ test_functional.py
    snapshot_container_status ─────────────────── ✅ test_functional.py
    determine_phase (4 variants) ──────────────── ✅ test_observation_tools.py
    snapshot_logs ─────────────────────────────── ✅ test_functional.py
    compute_metrics_delta (8 variants) ────────── ✅ test_observation_tools.py
    compute_blast_radius (valid + unknown) ────── ✅ test_functional.py

  AGENTS (agents/*.py)
    BaselineCollector e2e ─────────────────────── ✅ test_agents_functional.py
    FaultInjector e2e (container + network) ───── ✅ test_agents_functional.py
    SymptomObserver e2e ───────────────────────── ✅ test_agents_functional.py
    Healer e2e ────────────────────────────────── ✅ test_agents_functional.py
    EpisodeRecorder e2e + file write ──────────── ✅ test_agents_functional.py
    Multi-fault scenario ──────────────────────── ✅ test_agents_functional.py
    _filter_notable_logs ──────────────────────── ❌ NO UNIT TEST
    FaultInjector._dispatch_inject error paths ── ❌ NO UNIT TEST
    Healer recovery time edge cases ───────────── ❌ NO UNIT TEST

  ORCHESTRATOR (orchestrator.py)
    Full episode e2e ──────────────────────────── ✅ test_agents_functional.py
    run_scenario with invalid scenario ────────── ❌ NO TEST
    run_scenario with down stack ──────────────── ❌ NO TEST

  Section 4: Performance Review

● User answered Claude's questions:
  ⎿  · Issue 8: `snapshot_metrics()` in observation_tools.py force-resets the MetricsCollector cache (`collector._cache_ts = 0.0`) to get fresh data every call. But MetricsCollector.collect() does 7 parallel
     async operations (Prometheus HTTP, 3x kamcmd docker exec, rtpengine docker exec, PyHSS HTTP, MongoDB docker exec). During a chaos episode with 6 observation iterations, that's 42 docker exec calls + 12
     HTTP calls just for metrics. This works fine now (6-second episodes) but will slow down with longer observation windows. Should we optimize? → 8A: Keep force-refresh, add timeout (Recommended)

● Performance section complete. No other performance concerns — the SQLite WAL mode handles concurrent reads well, and the asyncio.gather parallelism in MetricsCollector is already the right pattern.

  ---
  All four review sections are done. Here's the summary of decisions made and the work to do:

  Decisions Summary

  ┌─────┬─────────────────────────┬────────────────────────────────────────────────────────────────────────┬────────────────────┐
  │  #  │          Issue          │                                Decision                                │       Effort       │
  ├─────┼─────────────────────────┼────────────────────────────────────────────────────────────────────────┼────────────────────┤
  │ 1   │ Shell injection surface │ 1A: Validate + quote (IP validation, container allowlist, shlex.quote) │ 30 min             │
  ├─────┼─────────────────────────┼────────────────────────────────────────────────────────────────────────┼────────────────────┤
  │ 2   │ Missing timeouts        │ 2A: Wrap key calls with asyncio.wait_for                               │ 20 min             │
  ├─────┼─────────────────────────┼────────────────────────────────────────────────────────────────────────┼────────────────────┤
  │ 3   │ _shell() DRY violation  │ 3A: Extract to tools/_common.py                                        │ 15 min             │
  ├─────┼─────────────────────────┼────────────────────────────────────────────────────────────────────────┼────────────────────┤
  │ 4   │ Container list DRY      │ 4A: Constants in models.py, import everywhere                          │ 15 min             │
  ├─────┼─────────────────────────┼────────────────────────────────────────────────────────────────────────┼────────────────────┤
  │ 5   │ Private import hack     │ 5A: New verify_tc_with_pid() in verification_tools                     │ 10 min             │
  ├─────┼─────────────────────────┼────────────────────────────────────────────────────────────────────────┼────────────────────┤
  │ 6   │ Untested network tools  │ 6A: Test corruption, bandwidth, partition                              │ 20 min             │
  ├─────┼─────────────────────────┼────────────────────────────────────────────────────────────────────────┼────────────────────┤
  │ 7   │ Untested log filter     │ 7A: Unit tests for _filter_notable_logs()                              │ 15 min             │
  ├─────┼─────────────────────────┼────────────────────────────────────────────────────────────────────────┼────────────────────┤
  │ 8   │ Metrics refresh perf    │ 8A: Keep force-refresh, add timeout (covered by Issue 2)               │ 0 min (part of #2) │
  └─────┴─────────────────────────┴────────────────────────────────────────────────────────────────────────┴────────────────────┘

  NOT in scope

  - Database encryption (overkill for a dev/lab tool)
  - Concurrent fault mutual exclusion (complex, rare in pre-built scenarios)
  - TypedDict return types for tools (nice but not blocking)
  - Reaper loop unit tests (complex to mock, low risk)
  - _run_live_impl stub removal (need to verify ADK requires it)

  What already exists

  - MetricsCollector — reused via lazy import (good)
  - topology.impact_of() — reused via lazy import (good)
  - _shell() in agentic_ops/tools.py — NOT reused (copied) → fixing with Issue 3

● 107 passed, 0 failed in 21.36s.

  Here's what was done across all 7 fixes:

  ┌─────────────────┬─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┬─────────────────────────────────────────────────────────────┐
  │       Fix       │                                                      What changed                                                       │                        Files touched                        │
  ├─────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
  │ 1: Shell        │ Added validate_container() (allowlist), validate_ip() (ipaddress module), shlex.quote() on all shell-interpolated       │ _common.py (new), docker_tools.py, network_tools.py         │
  │ injection       │ values, param range validation (delay_ms, loss_pct, etc.)                                                               │                                                             │
  ├─────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
  │ 2: Timeouts     │ shell() now has a 30s default timeout with asyncio.wait_for. snapshot_metrics() has 15s timeout. BaselineCollector has  │ _common.py, observation_tools.py, baseline.py,              │
  │                 │ 20s timeout on status. SymptomPoller has 15s timeout on both metrics and logs.                                          │ symptom_observer.py                                         │
  ├─────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
  │ 3: DRY _shell() │ Extracted to tools/_common.py. All 4 tool files now import from ._common import shell.                                  │ _common.py (new), docker_tools.py, network_tools.py,        │
  │                 │                                                                                                                         │ verification_tools.py, observation_tools.py                 │
  ├─────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
  │ 4: DRY          │ ALL_CONTAINERS, CORE_CONTAINERS, LOG_CONTAINERS constants in _common.py. Imported by observation_tools.py and           │ _common.py, observation_tools.py, symptom_observer.py       │
  │ containers      │ symptom_observer.py.                                                                                                    │                                                             │
  ├─────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
  │ 5: Private      │ New public verify_tc_with_pid(pid) in verification_tools.py. fault_injector.py imports and calls it instead of reaching │ verification_tools.py, fault_injector.py                    │
  │ import          │  into _shell/_nsenter. Also fixed the active vs verified key mismatch bug the review exposed.                           │                                                             │
  ├─────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
  │ 6: Network tool │ Added 6 new functional tests: corruption, bandwidth, partition (inject+heal), verify_tc_with_pid, invalid container,    │ test_functional.py                                          │
  │  tests          │ invalid IP, invalid delay.                                                                                              │                                                             │
  ├─────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
  │ 7: Log filter   │ 16 new unit tests for _filter_notable_logs: error keywords, SIP codes, false positive exclusions, edge cases, case      │ test_symptom_filter.py (new)                                │
  │ tests           │ sensitivity.                                                                                                            │                                                             │
  └─────────────────┴─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┴─────────────────────────────────────────────────────────────┘

  Bonus bug found and fixed during review: _dispatch_verify returned {"active": True} from verify_tc_with_pid but _inject_one checked for {"verified": True}. This caused every network latency fault to be
  reported as unverified and immediately healed. The review caught a real bug.



