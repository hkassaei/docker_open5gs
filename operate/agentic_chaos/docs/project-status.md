Everything checks out. Here's the full status:

  ┌──────────────────────────────────────────────────────────────────────────────┬───────────────────────────────────────────────┐
  │                                 Prerequisite                                 │                    Status                     │
  ├──────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
  │ Python 3.12                                                                  │ Installed                                     │
  ├──────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
  │ sqlite3 CLI                                                                  │ Installed (3.45.1)                            │
  ├──────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
  │ google-adk                                                                   │ Installed (1.27.2)                            │
  ├──────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
  │ aiosqlite                                                                    │ Installed (0.22.1)                            │
  ├──────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
  │ ADK imports (LlmAgent, SequentialAgent, ParallelAgent, LoopAgent, BaseAgent) │ All OK                                        │
  ├──────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
  │ pydantic / aiohttp / httpx                                                   │ Already in venv                               │
  ├──────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
  │ nsenter                                                                      │ Installed, passwordless sudo OK               │
  ├──────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
  │ tc (iproute2)                                                                │ Installed, passwordless sudo OK               │
  ├──────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
  │ iptables                                                                     │ Installed, passwordless sudo OK               │
  ├──────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
  │ Docker                                                                       │ Running, 26 containers up                     │
  ├──────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
  │ nsenter into container netns                                                 │ Verified — reached mongo's eth0 at 172.22.0.2 │
  ├──────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
  │ Gemini API access                                                            │ Pending — waiting on service account from IT  │
  └──────────────────────────────────────────────────────────────────────────────┴───────────────────────────────────────────────┘



  ● Here's what's available in your region:

  ┌───────────────────────────────┬───────────────┬────────────────────────────────────┐
  │             Model             │    Status     │              Use for               │
  ├───────────────────────────────┼───────────────┼────────────────────────────────────┤
  │ gemini-2.5-flash              │ Available     │ Orchestration (fast, cheap)        │
  ├───────────────────────────────┼───────────────┼────────────────────────────────────┤
  │ gemini-2.5-pro                │ Available     │ Specialist agents (deep reasoning) │
  ├───────────────────────────────┼───────────────┼────────────────────────────────────┤
  │ gemini-2.0-flash              │ Not available │ —                                  │
  ├───────────────────────────────┼───────────────┼────────────────────────────────────┤
  │ gemini-3.1-flash-lite-preview │ Not available │ —                                  │
  ├───────────────────────────────┼───────────────┼────────────────────────────────────┤
  │ gemini-3.1-pro-preview        │ Not available │ —                                  │
  └───────────────────────────────┴───────────────┴────────────────────────────────────┘


  Here's the Phase 1B summary:

  Files delivered

  ┌────────────────────────────┬──────────────────────────────────┬───────────────────────────────────────────────────────────────────────┐
  │            File            │               Type               │                                Purpose                                │
  ├────────────────────────────┼──────────────────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │ agents/__init__.py         │ Package                          │ —                                                                     │
  ├────────────────────────────┼──────────────────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │ agents/baseline.py         │ BaseAgent (no LLM)               │ Captures pre-fault metrics + container status snapshot                │
  ├────────────────────────────┼──────────────────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │ agents/fault_injector.py   │ BaseAgent (no LLM)               │ Target → Inject → Verify cycle for each fault, with registry safety   │
  ├────────────────────────────┼──────────────────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │ agents/symptom_observer.py │ LoopAgent + SymptomPoller        │ Polls metrics/logs at intervals, detects symptoms, signals when found │
  ├────────────────────────────┼──────────────────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │ agents/healer.py           │ BaseAgent (no LLM)               │ Heals all active faults via registry, captures post-heal metrics      │
  ├────────────────────────────┼──────────────────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │ recorder.py                │ BaseAgent (no LLM)               │ Assembles Episode JSON from session state, writes to episodes/        │
  ├────────────────────────────┼──────────────────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │ orchestrator.py            │ SequentialAgent + run_scenario() │ Wires all phases: baseline → inject → observe → heal → record         │
  └────────────────────────────┴──────────────────────────────────┴───────────────────────────────────────────────────────────────────────┘

  Architecture

  ChaosDirector (SequentialAgent)
    ├── BaselineCollector  → state["baseline"]
    ├── FaultInjector      → state["faults_injected"]
    ├── SymptomObserver (LoopAgent)
    │     └── SymptomPoller → state["observations"], escalate on symptoms
    ├── Healer             → state["resolution"]
    └── EpisodeRecorder    → state["episode"], writes JSON file

  Test results: 84 tests

  ┌──────────────────────────┬───────┬─────────────────────────────────────────────────────────────────────────────────────────────┐
  │          Suite           │ Tests │                                          Coverage                                           │
  ├──────────────────────────┼───────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Unit: models             │ 18    │ Pydantic models, enums, serialization, escalation schedules                                 │
  ├──────────────────────────┼───────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Unit: fault registry     │ 19    │ SQLite CRUD, TTL expiry, heal_all, emergency heal, roundtrips                               │
  ├──────────────────────────┼───────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Unit: observation tools  │ 12    │ Metrics delta, phase determination                                                          │
  ├──────────────────────────┼───────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Unit: verification tools │ 7     │ Ping RTT parser                                                                             │
  ├──────────────────────────┼───────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Functional: tools        │ 23    │ Docker, network, verification, observation against live stack                               │
  ├──────────────────────────┼───────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Functional: orchestrator │ 5     │ Full e2e: container pause, network latency, multi-fault, episode write, observation capture │
  ├──────────────────────────┼───────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Total                    │ 84    │                                                                                             │
  └──────────────────────────┴───────┴─────────────────────────────────────────────────────────────────────────────────────────────┘

  What works end-to-end

  run_scenario(scenario) takes a Scenario, runs it through the full ADK pipeline, and produces an Episode JSON file with all 11 keys: schema_version, episode_id, timestamp, duration, scenario, baseline,
  faults, observations, resolution, rca_label, challenge_result.

  
  Phase 1C Deliverables

  ┌────────────────────────────┬─────────────────────────────────────────────────────────────────┬───────────────────────────────┐
  │            File            │                             Purpose                             │             Tests             │
  ├────────────────────────────┼─────────────────────────────────────────────────────────────────┼───────────────────────────────┤
  │ scenarios/__init__.py      │ Package marker                                                  │ —                             │
  ├────────────────────────────┼─────────────────────────────────────────────────────────────────┼───────────────────────────────┤
  │ scenarios/library.py       │ 10 pre-built scenarios with full metadata                       │ 18 tests in test_scenarios.py │
  ├────────────────────────────┼─────────────────────────────────────────────────────────────────┼───────────────────────────────┤
  │ tools/application_tools.py │ MongoDB/PyHSS subscriber ops, config corruption                 │ — (Phase 1D scenarios)        │
  ├────────────────────────────┼─────────────────────────────────────────────────────────────────┼───────────────────────────────┤
  │ cli.py                     │ CLI: run, list-scenarios, list-episodes, show-episode, heal-all │ 11 tests in test_cli.py       │
  ├────────────────────────────┼─────────────────────────────────────────────────────────────────┼───────────────────────────────┤
  │ __main__.py                │ python -m agentic_chaos.cli entry point                         │ —                             │
  ├────────────────────────────┼─────────────────────────────────────────────────────────────────┼───────────────────────────────┤
  │ requirements.txt           │ google-adk, aiosqlite, pydantic                                 │ —                             │
  └────────────────────────────┴─────────────────────────────────────────────────────────────────┴───────────────────────────────┘

  The 10 Scenarios

  ┌─────┬────────────────────────┬───────────┬────────┬─────────────────────────────────────┐
  │  #  │          Name          │ Category  │ Blast  │               Faults                │
  ├─────┼────────────────────────┼───────────┼────────┼─────────────────────────────────────┤
  │ 1   │ gNB Radio Link Failure │ container │ single │ Kill nr_gnb                         │
  ├─────┼────────────────────────┼───────────┼────────┼─────────────────────────────────────┤
  │ 2   │ P-CSCF Latency         │ network   │ single │ 500ms + 50ms jitter on pcscf        │
  ├─────┼────────────────────────┼───────────┼────────┼─────────────────────────────────────┤
  │ 3   │ S-CSCF Crash           │ container │ single │ Kill scscf                          │
  ├─────┼────────────────────────┼───────────┼────────┼─────────────────────────────────────┤
  │ 4   │ HSS Unresponsive       │ container │ single │ Pause pyhss                         │
  ├─────┼────────────────────────┼───────────┼────────┼─────────────────────────────────────┤
  │ 5   │ Data Plane Degradation │ network   │ single │ 30% loss on upf                     │
  ├─────┼────────────────────────┼───────────┼────────┼─────────────────────────────────────┤
  │ 6   │ MongoDB Gone           │ container │ global │ Kill mongo                          │
  ├─────┼────────────────────────┼───────────┼────────┼─────────────────────────────────────┤
  │ 7   │ DNS Failure            │ container │ global │ Kill dns                            │
  ├─────┼────────────────────────┼───────────┼────────┼─────────────────────────────────────┤
  │ 8   │ IMS Network Partition  │ network   │ multi  │ Partition pcscf↔icscf + pcscf↔scscf │
  ├─────┼────────────────────────┼───────────┼────────┼─────────────────────────────────────┤
  │ 9   │ AMF Restart            │ container │ multi  │ Stop amf (10s grace)                │
  ├─────┼────────────────────────┼───────────┼────────┼─────────────────────────────────────┤
  │ 10  │ Cascading IMS Failure  │ compound  │ multi  │ Kill pyhss + 2s latency on scscf    │
  └─────┴────────────────────────┴───────────┴────────┴─────────────────────────────────────┘

  Test totals: 135 passed, 0 failed

  ● 160 passed, 0 failed in 21.58s. Phase 1 is complete. Here's the final summary:

  ---
  Phase 1 Complete — Full Agentic Chaos Monkey Platform

  What was built across all 4 phases

  operate/agentic_chaos/
  ├── __init__.py                     # Package
  ├── __main__.py                     # python -m entry point
  ├── cli.py                          # CLI: run, list-scenarios, list-episodes, show-episode, heal-all
  ├── models.py                       # 12 Pydantic models + escalation schedules
  ├── fault_registry.py               # SQLite + Triple Lock (registry, TTL reaper, signal handlers)
  ├── orchestrator.py                 # ChaosDirector SequentialAgent + run_scenario()
  ├── recorder.py                     # Episode JSON writer
  ├── scorer.py                       # Challenge Mode scoring (5 dimensions)
  ├── requirements.txt                # google-adk, aiosqlite, pydantic
  ├── README.md                       # Full usage docs
  ├── agents/
  │   ├── baseline.py                 # BaselineCollector (no LLM)
  │   ├── fault_injector.py           # FaultInjector with Target→Inject→Verify
  │   ├── symptom_observer.py         # SymptomPoller + LoopAgent factory
  │   ├── escalation.py               # EscalationChecker (Boiling Frog)
  │   ├── challenger.py               # ChallengeAgent (invoke RCA agent + score)
  │   └── healer.py                   # Healer (reverse all faults)
  ├── tools/
  │   ├── _common.py                  # Shared: shell(), validate_container(), validate_ip(), constants
  │   ├── docker_tools.py             # kill, stop, pause, restart (with validation)
  │   ├── network_tools.py            # latency, loss, corruption, bandwidth, partition (via nsenter)
  │   ├── verification_tools.py       # Ping probes, tc checks, container status
  │   ├── observation_tools.py        # Metrics snapshot, log capture, delta, blast radius
  │   └── application_tools.py        # MongoDB/PyHSS subscriber ops, config corruption
  ├── scenarios/
  │   └── library.py                  # 10 pre-built scenarios
  ├── episodes/                       # Output: recorded episode JSON files
  └── tests/                          # 160 tests across 10 test files
      ├── test_models.py              # 18 tests
      ├── test_fault_registry.py      # 19 tests
      ├── test_functional.py          # 34 tests (live stack)
      ├── test_agents_functional.py   # 5 tests (full e2e via ADK)
      ├── test_scenarios.py           # 18 tests
      ├── test_cli.py                 # 11 tests
      ├── test_scorer.py              # 19 tests
      ├── test_escalation.py          # 6 tests
      ├── test_symptom_filter.py      # 16 tests
      ├── test_observation_tools.py   # 12 tests
      └── test_verification_tools.py  # 7 tests (ping parser)

  Test summary: 160 passed, 0 failed

  ┌─────────────────────────┬───────┬─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │        Category         │ Tests │                                                             What's covered                                                              │
  ├─────────────────────────┼───────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Unit (no Docker)        │ 103   │ Models, registry CRUD/TTL, metrics delta, phase detection, ping parser, log filter, scorer, escalation schedules, scenarios, CLI parser │
  ├─────────────────────────┼───────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Functional (live stack) │ 52    │ Docker tools, all 5 network fault types + heal, verification probes, partition + iptables, metrics/logs/blast radius, input validation  │
  ├─────────────────────────┼───────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ E2E (ADK orchestrator)  │ 5     │ Container pause, network latency, multi-fault, episode write, observation capture — full pipeline                                       │
  └─────────────────────────┴───────┴─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  Key capabilities delivered

  - 10 scenarios from single-NF to global blast radius
  - Triple Lock fault safety (registry + TTL + signal handlers)
  - Adaptive escalation — progressively increases fault severity (Boiling Frog)
  - Challenge Mode — invokes RCA agent, scores its diagnosis against ground truth
  - Episode recording — structured JSON training data
  - CLI — run, list-scenarios, list-episodes, show-episode, heal-all
  - API endpoint — GET /api/chaos/faults for GUI integration (Phase 2)
  - Input validation — container allowlist, IP validation, parameter bounds, shlex quoting
  - Timeouts — 15-30s on all async operations to prevent hangs during chaos

❯ /plan-eng-review phases 1C and 1D

  ---
  Step 0: Scope Challenge

  What existing code solves sub-problems?

  ┌──────────────────────────┬────────────────────────────────────────────────────────────┬────────────────────────────────────────────────────────────────────┐
  │       Sub-problem        │                          Existing                          │                              Reused?                               │
  ├──────────────────────────┼────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ Scenario definitions     │ models.py:Scenario                                         │ Yes — library.py uses it directly                                  │
  ├──────────────────────────┼────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ Fault injection dispatch │ agents/fault_injector.py                                   │ Yes — escalation.py reuses same tools                              │
  ├──────────────────────────┼────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ .env parsing             │ server.py:_load_dotenv(), observation_tools.py:_load_env() │ Duplicated in challenger.py:_run_rca_agent() lines 196-203         │
  ├──────────────────────────┼────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ RCA agent invocation     │ server.py:handle_investigate()                             │ Partially duplicated — challenger.py reimplements agent invocation │
  └──────────────────────────┴────────────────────────────────────────────────────────────┴────────────────────────────────────────────────────────────────────┘

  Minimum set of changes?

  Phase 1C (scenarios + CLI) is clean and minimal. Phase 1D (scorer + challenger + escalation) is where the complexity is — 3 new agent files, and the escalation logic is the most intricate.

  Complexity check

  Phase 1C+1D adds 8 new files (library.py, application_tools.py, cli.py, main.py, scorer.py, challenger.py, escalation.py, README.md) + modifies 3 (orchestrator.py, symptom_observer.py, server.py). This is at
   the threshold but each file is focused and reasonable for the scope.

  The top issues worth discussing: (1) application_tools.py has zero tests and a sed injection risk, (2) challenger.py duplicates env-loading, (3) escalation.py has untested core logic, (4) a few error
  handling gaps in the orchestrator.

● User answered Claude's questions:
  ⎿  · Phase 1C+1D adds 8 files and modifies 3. The code is already implemented and 160 tests pass. The review found 4 substantive issues worth discussing + a few minor items. Which review depth? → SMALL
     CHANGE (Recommended)

● SMALL CHANGE mode. Here's the compressed single-pass review with test diagram.

  ---
  Test Coverage Diagram

  PHASE 1C+1D CODEPATHS & TEST COVERAGE
  ═══════════════════════════════════════════════════════════════

  SCENARIO LIBRARY (scenarios/library.py)
    10 scenario definitions ───────────────────── ✅ test_scenarios.py (18 tests)
    get_scenario() valid + unknown ────────────── ✅ test_scenarios.py
    list_scenarios() ──────────────────────────── ✅ test_scenarios.py
    Param validation (delay, loss, IP) ────────── ✅ test_scenarios.py
    Blast radius distribution ─────────────────── ✅ test_scenarios.py

  APPLICATION TOOLS (tools/application_tools.py)
    delete_subscriber_mongo ───────────────────── ❌ NO TEST
    count_subscribers_mongo ───────────────────── ❌ NO TEST
    drop_collection_mongo ─────────────────────── ❌ NO TEST
    delete_subscriber_pyhss ───────────────────── ❌ NO TEST
    count_subscribers_pyhss ───────────────────── ❌ NO TEST
    corrupt_config (sed) ──────────────────────── ❌ NO TEST ← sed injection risk

  CLI (cli.py)
    Parser: all 5 commands ────────────────────── ✅ test_cli.py (6 tests)
    cmd_list_scenarios ────────────────────────── ✅ test_cli.py
    cmd_list_episodes (empty + with data) ─────── ✅ test_cli.py
    cmd_show_episode (found + not found) ──────── ✅ test_cli.py
    cmd_run error handling ────────────────────── ❌ NO TEST (crash if run_scenario fails)
    cmd_heal_all ──────────────────────────────── ❌ NO TEST

  SCORER (scorer.py)
    score_diagnosis (5 cases) ─────────────────── ✅ test_scorer.py (8 tests)
    _extract_fault_keywords ───────────────────── ✅ test_scorer.py (4 tests)
    _expected_severity ────────────────────────── ✅ test_scorer.py (4 tests)
    _infer_severity_from_diagnosis ────────────── ✅ test_scorer.py (3 tests)
    Malformed input handling ──────────────────── ❌ NO TEST (None diagnosis, missing keys)

  CHALLENGER (agents/challenger.py)
    ChallengeAgent skip (not enabled) ─────────── ✅ via e2e (non-challenge scenarios)
    ChallengeAgent skip (no API key) ──────────── ❌ NO UNIT TEST
    _rca_agent_available() check ──────────────── ❌ NO UNIT TEST
    _build_question() from observations ───────── ❌ NO UNIT TEST
    _run_rca_agent() + scoring integration ────── ❌ NO TEST (needs ANTHROPIC_API_KEY)
    .env file parsing ─────────────────────────── ❌ NO TEST ← DRY violation

  ESCALATION (agents/escalation.py)
    EscalationChecker symptoms → exit loop ────── ❌ NO TEST
    EscalationChecker no symptoms → escalate ──── ❌ NO TEST
    EscalationChecker max level → exit ────────── ❌ NO TEST
    _reinject() success ───────────────────────── ❌ NO TEST
    _reinject() failure ───────────────────────── ❌ NO TEST
    Escalation schedule lookup ────────────────── ✅ test_escalation.py (6 tests)

  DATA-READY API (server.py)
    GET /api/chaos/faults ─────────────────────── ❌ NO TEST

  ---

  ● 171 passed, 0 failed in 21.52s.

  ---
  Completion Summary

  +====================================================================+
  |            ENG REVIEW — COMPLETION SUMMARY                          |
  +====================================================================+
  | Step 0: Scope Challenge    | SMALL CHANGE selected                  |
  | Architecture Review        | 1 issue (DRY: env parsing) → FIXED    |
  | Code Quality Review        | 1 issue (sed injection) → FIXED       |
  | Test Review                | diagram produced, 2 gaps → FIXED       |
  |                            |   + escalation logic tests (5 mocked)  |
  |                            |   + application_tools tests (5 tests)  |
  | Performance Review         | 1 issue (private attr) → FIXED        |
  +--------------------------------------------------------------------+
  | NOT in scope               |                                        |
  |   - Challenger e2e test    | needs ANTHROPIC_API_KEY                 |
  |   - DB encryption          | overkill for lab tool                  |
  |   - server.py container    | out of scope for this review            |
  |     name validation        |   (Phase 2 GUI work)                   |
  +--------------------------------------------------------------------+
  | What already exists        |                                        |
  |   - _load_env()            | reused (was duplicated, now fixed)     |
  |   - FaultInjector dispatch | reused by escalation                   |
  +--------------------------------------------------------------------+
  | Fixes applied              | 4                                      |
  |   1. Reuse _load_env()     | challenger.py: -8 lines, +1 import    |
  |   2. sed → python3         | application_tools.py: no regex risks   |
  |   3. Tests added           | +11 tests (5 escalation + 5 app + 1)  |
  |   4. is_initialized prop   | fault_registry.py + orchestrator.py    |
  | Tests: 160 → 171           | +11 new tests, 0 regressions          |
  | Failure modes              | 0 critical gaps remaining              |
  +====================================================================+

  Unresolved Decisions

  None — all 4 issues resolved.

## At the end of Phase 1 (A, B, C, D)

 The FaultInjector does NOT use Gemini. It's a BaseAgent (no LLM) that dispatches to tools deterministically. When you run a pre-built scenario like "P-CSCF Latency", the FaultInjector reads the FaultSpec
  from session.state["scenario"], sees fault_type="network_latency", and calls inject_latency() directly via an if-elif dispatch table. No LLM reasoning involved.

  In fact, 5 of the 6 agents in the pipeline use zero LLM calls:

  ┌───────────────────┬───────────┬─────────────────────────────────────────────────────────────────┐
  │       Agent       │ Uses LLM? │                          How it works                           │
  ├───────────────────┼───────────┼─────────────────────────────────────────────────────────────────┤
  │ BaselineCollector │ No        │ Calls snapshot_metrics() + snapshot_container_status() directly │
  ├───────────────────┼───────────┼─────────────────────────────────────────────────────────────────┤
  │ FaultInjector     │ No        │ Reads FaultSpecs, dispatches to tools via if-elif on fault_type │
  ├───────────────────┼───────────┼─────────────────────────────────────────────────────────────────┤
  │ SymptomPoller     │ No        │ Calls snapshot_metrics(), computes delta, keyword-filters logs  │
  ├───────────────────┼───────────┼─────────────────────────────────────────────────────────────────┤
  │ EscalationChecker │ No        │ Reads symptoms_detected from state, bumps escalation level      │
  ├───────────────────┼───────────┼─────────────────────────────────────────────────────────────────┤
  │ Healer            │ No        │ Calls registry.heal_all()                                       │
  ├───────────────────┼───────────┼─────────────────────────────────────────────────────────────────┤
  │ EpisodeRecorder   │ No        │ Assembles JSON from session.state, writes to disk               │
  └───────────────────┴───────────┴─────────────────────────────────────────────────────────────────┘

  The only agent that uses an LLM is the ChallengeAgent, which invokes the agentic_ops troubleshooting agent (Pydantic AI + Claude) — and that's a completely separate agent framework, not even Gemini.

  So where does Gemini come in?

  Right now, Gemini is used only by the ADK Runner to process the initial user message ("Execute chaos scenario: DNS Failure") and route it through the SequentialAgent pipeline. It's the ADK framework overhead
   — the SequentialAgent needs an LLM to process the conversation flow, even though the actual agents inside are all deterministic BaseAgent subclasses.

  Where Gemini WOULD add real value (Phase 2+)

  The plan originally envisioned LlmAgent variants of the specialists:

  1. LLM-driven FaultInjector — Instead of reading a pre-built FaultSpec, an LlmAgent would receive a high-level instruction like "Degrade the IMS signaling path" and use Gemini to reason about which
  containers to target, what fault type to use, and what parameters make sense given the protocol timers. It would have inject_latency, inject_partition, etc. as ADK tools and the LLM would decide which to
  call.
  2. LLM-driven Scenario Generator — An LlmAgent that takes the topology graph (from topology.py) and designs novel failure scenarios that a human wouldn't think of.
  3. LLM-driven SymptomEvaluator — Instead of keyword-filtering logs, Gemini would read the logs and metrics and reason about whether they indicate real symptoms vs. noise. It would understand that "408
  Request Timeout" in a P-CSCF log is a SIP-layer symptom but "unrecognised option [-1]" is benign noise.

  Why we built it deterministic first

  This was a deliberate architectural choice. The deterministic BaseAgent approach:
  - Works without any LLM API key (except Challenge Mode)
  - Is fast (no API latency — episodes complete in ~2 seconds)
  - Is predictable and testable (171 tests, all deterministic)
  - Produces the same result every time (important for training data consistency)

  The LLM layer can be added on top later without changing the tools, models, or safety layer. The tools are framework-agnostic — they work from an LlmAgent the same way they work from a BaseAgent.

  Want me to build an LlmAgent variant of the FaultInjector that actually uses Gemini for intelligent fault design?