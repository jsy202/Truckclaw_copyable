# Split Real-CARLA 50-Run Validation Report

Base commit: local `validation` commit `a22220c23f4ebb58711216f525494e2668794bd2` on branch `validation-carla-50runs`.

동일한 고정 CARLA 조건에서 50회 반복 실행해 50/50 완료 및 logical/physical state consistency 50/50을 확인했다.

이 결과는 특정 고정 시뮬레이션 조건에서의 E2E 반복 완결성을 실증한 것으로, 일반적인 신뢰성(general reliability)이나 실차 신뢰성을 의미하지 않습니다.

## Result Summary

| Metric | Result | Note |
|---|---:|---|
| Runs | 50 | 고정 CARLA 조건 독립 프로세스 격리 실행 |
| Physical Split success | 50/50 | 물리적 분리 및 독립 주행 확인 |
| Logical / physical consistency | 50/50 | `[truck0, truck1]` 유지 + `truck2` 독립 LeadNavigator |
| Agent Copy success | Not tested | 환경 부재로 테스트 대상 제외 |
| Timeout | 0 | 0건 |
| Crash | 0 | 0건 (충돌 감지 센서 0건) |
| Cleanup failure | 0 | 0건 (포트 2000/2001/18801/18802 프로세스 그룹 정리) |

## Timing Statistics (Raw Evidence Based)

| Phase | Mean | P50 (Median) | P95 | Max | Min |
|---|---:|---:|---:|---:|---:|
| `trigger → logical_detach` | 0.006440 s | 0.006252 s | 0.008413 s | 0.009025 s | 0.005469 s |
| `trigger → gap_ready` | 0.047792 s | 0.048274 s | 0.056017 s | 0.063378 s | 0.038002 s |
| `trigger → lane_separated` | 0.655984 s | 0.667157 s | 0.793306 s | 0.808414 s | 0.046153 s |
| `trigger → done` | 5.761277 s | 5.494773 s | 6.350484 s | 17.032763 s | 4.752508 s |

> **주목할 점 (Run 004)**: 49개 실행에서는 목표 인접 차선(lane -4)으로 차선 변경을 완료했으나, Run 004에서는 해당 스폰 지점 기하 특성으로 `_driving_adjacent_lanes`가 빈 값을 반환하여 인접 차선 변경 대신 도로 분기(road 8 램프)로 분기 주행(이격 거리 31.6m)하여 `DONE`에 도달했습니다.

## Defect History

- **VAL-S01**: CARLA child process survived wrapper termination
  - **Before**: 49/50 통과 후 Run 50에서 `CarlaUE4.sh` 래퍼 종료 시 자식 `CarlaUE4-Linux-Shipping`이 잔류하여 포트 2000 점유로 cleanup failure 발생 (기록: `evidence_before_fix/split_cleanup_attempt_49of50/`).
  - **Root Cause**: `stop_process()`가 래퍼 Popen의 종료만 대기하고 프로세스 그룹 내 자식 잔류 여부를 확인하지 않음.
  - **Fix**: 프로세스 그룹 자체를 검사하여 SIGTERM 유예 후에도 잔류 시 그룹 전체에 SIGKILL 송신하도록 수정.
  - **Regression Test**: `test_owned_child_is_killed_after_wrapper_exits_on_term`
  - **After**: 수정 후 전체 50회 처음부터 재실행하여 50/50 완료 및 cleanup failure 0 달성.
  - 상세 내역: [defects.md](defects.md)

## Separate CARLA-free regression baseline

검증 착수 전 기존 단위/회귀 테스트는 21/21 passed였습니다. 이 테스트 결과는 실제 CARLA 50회 실행 통계에 합산하지 않습니다.

## Final Comparison

| Scenario | Repository | Real CARLA Runs | Verification |
|---|---|---:|---|
| Transfer | Truckclaw-improve | 10 | request → physical merge → logical membership |
| Split | Truckclaw_copyable | 50 | logical detach → physical separation → independent driving |
| Leader Change | Truckclaw_movable | 50 | leader/controller transition → physical maneuver → old leader rejoin |

## Limitations

- **Fixed condition**: 고정된 CARLA 시나리오 조건에서만 실행되었습니다.
- **Single scenario configuration**: 3대 플래툰 단일 설정입니다.
- **CARLA simulation**: CARLA 0.9.13 시뮬레이션 환경 검증이며 실차 검증이 아닙니다.
- **Off-screen rendering**: `-RenderOffScreen` 모드 시뮬레이션입니다.
- **carlacola fallback**: `vehicle.carlamotors.carlacola` 모델을 사용했습니다.
- **OpenClaw Agent Copy Not tested**: 환경 부재로 미검증되었습니다.
- **Generalization 미검증**: 다양한 환경에 대한 일반화는 검증되지 않았습니다.
- 상세 내역: [limitations.md](limitations.md)
