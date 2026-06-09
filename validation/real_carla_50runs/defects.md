# Validation Defect Record

## VAL-S01 — CARLA child survived wrapper termination

### Before

The first 50-run Split attempt is preserved under `evidence_before_fix/split_cleanup_attempt_49of50/`. Runs 1–49 passed. Run 50 reached `DONE` with every logical and physical check true, but was correctly marked FAIL because cleanup left port 2000 owned by CARLA PID 42433. The attempt result was therefore 49/50 with one cleanup failure.

### Root cause

The runner launched `CarlaUE4.sh` in a new process group and sent SIGTERM to that group, but `stop_process()` waited only for the wrapper `Popen` object. On run 50 the shell wrapper exited while `CarlaUE4-Linux-Shipping` remained in the same process group. Because the wrapper had exited, the function returned without escalating to SIGKILL for the surviving child.

### Fix

`stop_process()` now checks the process group itself after SIGTERM. If any group member remains through the fixed grace period, it sends SIGKILL to that exact runner-owned group and waits for the group to disappear. The same lifecycle helper in the Leader Change runner received the identical correction.

### Regression test

`test_owned_child_is_killed_after_wrapper_exits_on_term` starts a wrapper whose child ignores SIGTERM. It failed before the change because the child group remained and passes after the change. Full suites after the fix: Split 44 passed; Leader Change 49 passed with the existing gateway-health xfail.

### After

Per the validation protocol, the Split 50-run measurement is restarted from run 1. The failed cleanup attempt is not counted in the final 50-run measurement and remains explicitly reported as pre-fix evidence.
