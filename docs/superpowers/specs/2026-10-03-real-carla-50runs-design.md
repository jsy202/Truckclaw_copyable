# Split Real-CARLA 50-Run Validation Design

## Purpose

Validate whether the production Split scenario completes consistently across 50 repetitions under one fixed CARLA condition. The result is limited to this condition and must be reported as “X of 50 runs succeeded under the fixed CARLA condition.”

## Validation target

- Base branch: local `validation`
- Base commit: `a22220c23f4ebb58711216f525494e2668794bd2`
- Production scenario: `scenario/examples/single_platoon_branch_scenario.py`
- Actual state machine: `CRUISE → MIGRATE → GAP → LC → SIDE_BY_SIDE → DONE`
- CARLA: 0.9.13, Town06, synchronous `dt=0.01`, `vehicle.carlamotors.carlacola`
- Server flags: `-RenderOffScreen -quality-level=Low`
- OpenClaw: `Not tested`; physical runs use the existing `--no-openclaw` path

The scenario calls `platoon.split(2, 2)` when `GAP` first updates, before the 15 m gap criterion is met. Logical detach, gap readiness, lane separation, and independent driving are therefore distinct observations.

## Architecture

The production scenario remains the executable under test. A validation-only hook, enabled only by a CLI evidence-directory option, records direct in-process state without changing the normal path. It records state transitions, `Core.Platoon` membership and controller references, actor identity and kinematics, waypoint road/lane, collision events, and monotonic timing.

An external runner owns every CARLA process used by the suite. For each run it verifies port 2000 is free, starts CARLA, waits for RPC readiness, starts the bridge and production scenario, waits for the ready artifact, sends exactly one HTTP trigger, watches the bounded run, saves evidence, terminates the scenario and bridge, stops CARLA, verifies the port is free, and continues after a non-fatal run failure.

The manually started CARLA process may be used only for the smoke run. Before the 50-run suite, it must be stopped and port 2000 must be verified free. The suite refuses to start a server when the port is occupied by a process it does not own.

## Evidence and data flow

Each `evidence/runNNN/` contains:

- `initial_snapshot.json`
- `trigger_snapshot.json`
- `transition_events.json`
- `final_snapshot.json`
- `result.json`
- compact scenario, bridge, and CARLA logs

The recorder writes atomically so the external runner never reads partial JSON. Actor names map from the direct Python vehicle objects, not guessed actor ordering. Timings use monotonic wall time with the trigger accepted by the scenario as origin; simulation time is also retained for diagnosis.

## Fixed PASS invariants

A run passes only when all of these hold:

1. Initial: exactly three named vehicle actors are alive in one in-memory platoon ordered `[truck0, truck1, truck2]`; `truck2` is a member.
2. Trigger: the runner sends one trigger and the scenario records one accepted trigger.
3. Gap: the production criterion is observed with measured `truck1`–`truck2` distance at least `OPEN_GAP_READY_M=15.0` for `GAP_STABLE_TICKS=10` consecutive ticks before `LC`.
4. Logical detach: the final main membership is `[truck0, truck1]`; the detached membership is `[truck2]`.
5. Physical separation: all actors remain alive, truck2 is on a different driving lane from the main platoon, and no collision event is recorded.
6. Independent driving: after `DONE`, truck2 has a `LeadNavigator`, remains moving, and displaces at least 0.5 m during a fixed 2.0 simulation-second settle interval.
7. Final state: scenario state is `DONE`; no timeout, crash, or validation abort occurred.

`DONE` alone never passes a run. Thresholds above are fixed before the smoke run and are not changed based on results.

## Timing

Record ready→trigger, trigger→logical detach, trigger→gap ready, trigger→lane separation, and trigger→DONE. Agent Copy duration is `Not tested`.

## Failure handling

A failed run retains its state, last transition, exception/timeout, collision data, and final physical snapshot. Cleanup then runs and the next run proceeds. Server death is retried only as lifecycle recovery; it is still recorded. If a production defect is confirmed, preserve Before evidence, write a failing regression test, make the smallest production correction, prove RED→GREEN, and restart the 50-run measurement from run 1.

## Outputs

`validation/real_carla_50runs/` contains `validation_report.md`, `runs_summary.csv`, `timing_summary.csv`, `failures.csv`, `environment.json`, `limitations.md`, `run.log`, the baseline record, tools, tests, and 50 evidence directories. Existing CARLA-free regression results remain a separate section and never count as real-CARLA runs.

## Non-goals

No claim is made about other maps, vehicles, speeds, spawn points, render modes, hardware, real vehicles, production reliability, or failure probability. OpenClaw Agent Copy is not exercised in this environment.
