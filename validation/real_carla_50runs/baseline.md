# Validation Branch Baseline

Captured before creating `validation-carla-50runs`.

| Item | Value |
|---|---|
| Repository | `Truckclaw_copyable` |
| Starting branch | local `validation` |
| Base commit | `a22220c23f4ebb58711216f525494e2668794bd2` |
| `origin/main` | `24cee6bb76f19171297571332ae6b0a2d448c124` |
| Start status | clean (`## validation`) |
| New branch | `validation-carla-50runs` |
| Baseline tests | 21 passed in 3.07 s |

## Existing validation changes over `origin/main`

The base contains 12 local validation commits: a CARLA/Docker-free Split and replication harness; fixes for replication success reporting, timeout/failure handling, duplicate replication, truck3 identity-template selection and completeness, the bridge `/branch` contract, and unknown `/replicate` vehicles; CI/tests; and validation documentation. Its diff from `origin/main` is 28 files, 1007 insertions, and 11 deletions.

These inherited regression results and fixes are prerequisites, not outcomes of the real-CARLA 50-run measurement.
