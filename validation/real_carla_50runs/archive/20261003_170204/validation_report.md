# Split Real-CARLA 50-Run Validation Report

Base: local `validation` commit `a22220c23f4ebb58711216f525494e2668794bd2` on branch `validation-carla-50runs`.

This report measures repeated E2E completion only under the fixed CARLA condition described in the design. It does not claim general reliability.

| Metric | Result |
|---|---:|
| Runs | 1 |
| Physical Split success | 1/1 |
| Logical / physical consistency | 1/1 |
| Agent Copy success | Not tested |
| Timeout | 0 |
| Crash | 0 |
| Cleanup failure | 0 |
| Mean trigger → detach | 0.007 |
| P50 | 0.007 |
| P95 | 0.007 |
| Max | 0.007 |

## Separate CARLA-free regression baseline

Before this work, 21/21 tests passed. These tests are not included in the real-CARLA run count.

## Final Comparison

| Scenario | Repository | Real CARLA Runs | Main Verification |
|---|---|---:|---|
| Transfer | Truckclaw-improve | 10 | request → physical merge → logical membership |
| Split | Truckclaw_copyable | 1 | platoon detach → independent driving |
| Leader Change | Truckclaw_movable | pending separate report | leader transition → old leader physical rejoin |
