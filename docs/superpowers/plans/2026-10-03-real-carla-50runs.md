# Split Real-CARLA 50-Run Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add validation-only observation and lifecycle automation, then execute and report 50 fixed-condition real-CARLA Split runs.

**Architecture:** The production scenario receives an opt-in recorder hook; pure validation code serializes direct in-memory platoon/actor state and evaluates fixed invariants. A separate runner exclusively owns a fresh CARLA server, bridge, and scenario process for each measured run and aggregates preserved evidence.

**Tech Stack:** Python 3.7 scenario/CARLA client, Python 3.10 orchestration and pytest, CARLA 0.9.13, stdlib JSON/CSV/subprocess/HTTP.

**Spec:** `docs/superpowers/specs/2026-10-03-real-carla-50runs-design.md`

## Global Constraints

- Run the unchanged production state machine; validation hooks are inactive without the validation CLI flag.
- Fixed thresholds: gap 15.0 m for 10 ticks; final settle 2.0 simulation seconds; independent displacement at least 0.5 m.
- `DONE` alone is never sufficient.
- OpenClaw is `Not tested`; measured physical runs use `--no-openclaw`.
- Each measured run uses a runner-owned fresh off-screen CARLA server and must leave port 2000 free.
- Existing 21/21 regression results are separate from real-CARLA counts.
- Preserve all failures and never tune thresholds, timeouts, spawns, or PASS criteria after observing results.

## Review Focus

- Partial/corrupt evidence writes must not be read as success; test atomic JSON and missing evidence.
- An occupied port 2000 must abort before spawning a second server; test foreign-listener refusal.
- State `DONE` with wrong membership or lane must fail; evaluator tests cover each invariant independently.
- A failed run must not stop later runs; runner aggregation test covers mixed results.
- Scenario crash/timeout must still create a failed `result.json` and cleanup owned processes.

---

### Task 1: Pure snapshot and result evaluator

**Files:**
- Create: `validation/real_carla_50runs/tools/split_validation.py`
- Create: `tests/unit/test_real_carla_split_validation.py`

**Interfaces:**
- Produces: `atomic_write_json(path, value)`, `actor_snapshot(vehicle, cmap)`, `platoon_snapshot(coord, sim, names)`, `evaluate_split(initial, events, final) -> dict`, and `summarize_results(results) -> dict`.
- Consumes: plain dict snapshots; CARLA objects only in serializer functions.

- [ ] **Step 1: Write failing evaluator and atomic-write tests** asserting every fixed invariant, independent-driving displacement, missing/corrupt evidence behavior, percentile calculation, and failure preservation.
- [ ] **Step 2: Run `python3 -m pytest tests/unit/test_real_carla_split_validation.py -q` and verify failure because the module is absent.**
- [ ] **Step 3: Implement the minimal pure serializer/evaluator module.**
- [ ] **Step 4: Run the focused test and full `python3 -m pytest -q`; expect all tests green.**
- [ ] **Step 5: Commit `test(validation): add Split evidence evaluator`.**

### Task 2: Opt-in production-scenario recorder

**Files:**
- Create: `validation/real_carla_50runs/tools/scenario_recorder.py`
- Modify: `scenario/examples/single_platoon_branch_scenario.py`
- Modify: `tests/unit/test_real_carla_split_validation.py`

**Interfaces:**
- Consumes: Task 1 serializers/evaluator.
- Produces: `ScenarioRecorder`; CLI flags `--validation-evidence-dir`, `--validation-ready-s`, and `--validation-settle-s`; direct JSON artifacts and collision events.

- [ ] **Step 1: Add failing stub-CARLA tests proving the normal CLI/coordinator path is unchanged, one trigger is counted, logical detach is captured before gap readiness, transitions are ordered, collisions fail, and finalization waits exactly the fixed settle interval.**
- [ ] **Step 2: Run the focused tests and verify the expected missing-hook failures.**
- [ ] **Step 3: Implement the recorder and smallest scenario hook, including sensor cleanup in `finally`.**
- [ ] **Step 4: Run focused tests and the full suite; expect 21 inherited tests plus new tests to pass.**
- [ ] **Step 5: Commit `feat(validation): instrument production Split scenario`.**

### Task 3: Exclusive CARLA lifecycle runner and report generation

**Files:**
- Create: `validation/real_carla_50runs/tools/run_split_validation.py`
- Create: `tests/unit/test_real_carla_split_runner.py`
- Create/update: `validation/real_carla_50runs/environment.json`, `limitations.md`

**Interfaces:**
- Consumes: scenario artifacts and Task 1 summarizer.
- Produces: CLI `--runs`, `--smoke`, `--allow-existing-carla-for-smoke`, lifecycle refusal on foreign port ownership, per-run evidence, `runs_summary.csv`, `timing_summary.csv`, `failures.csv`, `run.log`, and deterministic report rendering.

- [ ] **Step 1: Write failing lifecycle tests for foreign-port refusal, owned-process cleanup, failure continuation, crash/timeout result synthesis, and 50-row aggregation.**
- [ ] **Step 2: Run the focused runner tests and verify missing-runner failures.**
- [ ] **Step 3: Implement process-group lifecycle, readiness probes, one HTTP trigger, cleanup verification, aggregation, and environment capture.**
- [ ] **Step 4: Run focused tests and full suite; expect all green.**
- [ ] **Step 5: Commit `feat(validation): automate isolated Split CARLA runs`.**

### Task 4: Smoke, defect gate, 50-run measurement, and report

**Files:**
- Create: `validation/real_carla_50runs/evidence/run001` through `run050`
- Create/update: `validation/real_carla_50runs/validation_report.md`, CSV summaries, `environment.json`, `limitations.md`, `run.log`
- If and only if confirmed: minimal production fix plus a regression test and `evidence/before_fix/`.

**Interfaces:**
- Consumes: Task 3 runner.
- Produces: measured artifacts and local branch commit.

- [ ] **Step 1: Run one smoke run, inspect every artifact and compare direct logical and CARLA physical data.**
- [ ] **Step 2: If a defect occurs, preserve Before evidence, use systematic debugging, add a RED regression, minimally fix, prove GREEN/full-suite, and repeat smoke.**
- [ ] **Step 3: Stop the manual CARLA server, verify port 2000 free, then run `python3 validation/real_carla_50runs/tools/run_split_validation.py --runs 50`.**
- [ ] **Step 4: Verify exactly 50 result rows/directories, recompute all metrics from raw `result.json`, inspect all failures, and render the report without unsupported claims.**
- [ ] **Step 5: Run full pytest, syntax checks, `git diff --check`, evidence consistency audit, and commit `validation(real-carla): record 50 Split runs`.**
