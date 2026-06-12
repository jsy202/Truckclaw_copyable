# Split Real-CARLA 50-Run Validation Report

## 1. Objective

본 검증의 목적은 3대 트럭 군집(platoon) 주행 중 최후미 차량(`truck2`)의 분기(Split) 시나리오에 대해, 실제 CARLA 시뮬레이터 환경에서 프로세스 격리 기반의 50회 연속 반복 실행을 수행하여 상태 머신 완결성 및 논리적/물리적 상태 일관성(logical & physical state consistency)을 실증적으로 검증하는 것이다.

## 2. System Under Test

- **Repository**: `Truckclaw_copyable` (https://github.com/jsy202/Truckclaw_copyable)
- **Branch**: `validation-carla-50runs`
- **Base Commit**: `a22220c23f4ebb58711216f525494e2668794bd2`
- **Target Component**:
  - `single_platoon_branch_scenario.py`: 군집 분기 조율자(`BranchCoordinator`) 및 차량 제어 로직
  - `platoon_bridge_server.py`: 시나리오와 외부 에이전트 간 분기 상태 통신 브리지 (`/branch`, `/replicate`)

## 3. Environment

- **Simulator**: CARLA 0.9.13
- **Host OS**: Ubuntu 22.04 LTS (Linux 6.8.0-138-generic)
- **Python Runtime**: Python 3.7.17 (CARLA 클라이언트 환경), Python 3.10.12 (검증 runner 환경)
- **GPU Hardware**: NVIDIA GeForce RTX 3060 (Driver: 535.183.01)
- **Rendering**: `-RenderOffScreen` (실제 CARLA 물리 엔진 시뮬레이션이며 화면 렌더링 파이프라인만 생략)
- **Map**: Town06
- **Vehicle Blueprint**: `vehicle.carlamotors.carlacola` (`european_hgv` blueprint 부재에 따른 fallback)

## 4. Fixed Scenario Conditions

- **Platoon Configuration**: 3대 트럭 대열 (`truck0` 선두, `truck1` 중간, `truck2` 후미)
- **Initial Spawn**: Town06 고속도로 구간 (x=81.0, y=136.0, yaw=0.0 deg)
- **Target Speed**: 20.0 km/h (`SYNC_SPEED_KMH`)
- **Simulation Time Step**: `dt = 0.01 s` (100 Hz fixed time step)
- **Weather**: CloudySunset
- **Trigger Method**: HTTP POST `:18802/start_merge` 수신 시 분기 시퀀스 개시

## 5. State Machine

군집 분기 시나리오는 다음과 같은 단계로 전이된다:

```
CRUISE → MIGRATE → GAP → LC → SIDE_BY_SIDE → DONE
```

1. `CRUISE`: 3대 차량이 지정 차선에서 설정 속도 및 간격을 유지하며 정속 주행
2. `MIGRATE`: OpenClaw 에이전트 복제 단계 (본 환경에서는 미배치로 skip 처리되어 즉시 GAP 전이)
3. `GAP`: `truck2` 감속 제어를 통해 선행차(`truck1`)와의 물리적 안전 간격(>= 15.0 m) 확보 및 10 ticks 유지
4. `LC`: 목표 인접 차선(`lane -4`)으로 차선 변경 기동 수행
5. `SIDE_BY_SIDE`: 분기 차량이 잔여 군집과 나란히 주행하며 속도 및 종방향 정렬 확인
6. `DONE`: `truck2`에 독립 내비게이터(`LeadNavigator`)를 배정하고 분기 완료 확정

> **Logical vs Physical Separation**:
> `platoon.split(2, 2)`는 `GAP` 진입 직후 논리적 멤버십 분리(`logical_detach`)로 발생하며, 차선 변경 및 물리적 이격(`physical separation`)은 이후 `LC` 및 `SIDE_BY_SIDE`를 거쳐 달성된다. 두 사건은 서로 다른 시점에 발생하는 별개의 이벤트로 분리 기록된다.

## 6. Validation Invariants

Split 성공 판정(PASS)은 단순 `DONE` 상태 도달이 아닌 아래 불변식(invariants)을 모두 만족해야 한다:

1. **Initial State Invariant**: 시작 시 CRUISE 상태, 멤버 `[truck0, truck1, truck2]`, 전 차량 생존
2. **Single Accepted Trigger**: 50회 중 유효 트리거가 정확히 1회 수락 및 반영
3. **Logical Detach Event**: `logical_detach` 이벤트 관측 및 잔여 군집 `[truck0, truck1]`, 분기 차량 `[truck2]` 분리 확인
4. **Gap Stability**: `gap_ready` 관측 시 앞차와의 간격 >= 15.0 m 및 10 ticks 안정 지속
5. **Physical / Lane Separation**: 잔여 군집 차선과 분기 차량 차선이 상이하거나, 독립 도로 분기 경로로 물리적 이격 달성
6. **No Forced Transition**: 타임아웃에 의한 강제 전이 플래그(`forced=True`)가 없을 것
7. **Logical Membership**: 최종 상태에서 주 군집 `[truck0, truck1]`, 분리 군집 `[truck2]`, 전체 플래툰 수 2개
8. **Controller Contract**: `truck0` (LeadNavigator), `truck1` (FollowerController), `truck2` (독립 LeadNavigator)
9. **Independent Motion**: `DONE` 판정 후 `truck2`가 독자적으로 주행한 변위(displacement) >= 0.5 m
10. **Liveness & Collision-Free**: 전 차량 actor 생존(alive=True), 속도 > 0 km/h, 충돌 이벤트 수 0건
11. **State Completion**: 최종 시나리오 상태 `DONE` 정상 도달

## 7. Runner / Lifecycle

- 각 실행(run)마다 독립된 CARLA 서버 프로세스 그룹(`CarlaUE4.sh`)을 백그라운드로 기동
- 프로세스 그룹 분리(`setsid` / `preexec_fn=os.setsid`)를 통해 시나리오 및 서버 프로세스 수명 주기 완전 격리
- 시나리오 종료 후 포트(2000, 2001, 18801, 18802) 해제 및 잔류 프로세스 여부를 검사하여 cleanup 확인

## 8. 50-run Result

동일한 고정 CARLA 조건에서 50회 반복 실행한 결과는 다음과 같다:

| Metric | Result | Note |
|---|---:|---|
| Real CARLA Runs | 50 | 고정 CARLA 조건 독립 격리 실행 |
| Physical Split Success | 50/50 | 50/50 successful runs under the tested fixed CARLA condition |
| Logical / Physical Consistency | 50/50 | Logical and physical state consistency was observed in all 50 runs |
| Agent Copy Success | Not tested | 환경 부재(미배치)로 테스트 제외 |
| Timeout | 0 | 0건 |
| Crash | 0 | 0건 (충돌 감지 센서 관측 0건) |
| Cleanup Failure | 0 | 0건 (포트 점유 잔류 0건) |

## 9. Timing Statistics

50개 실행의 원본 evidence(`transition_events.json`)에서 직접 계산한 단계별 소요 시간 통계:

| 구간 (Phase) | Mean | P50 (Median) | P95 | Max | Min |
|---|---:|---:|---:|---:|---:|
| `trigger → logical_detach` | 0.006440 s | 0.006252 s | 0.008413 s | 0.009025 s | 0.005469 s |
| `trigger → gap_ready` | 0.047792 s | 0.048274 s | 0.056017 s | 0.063378 s | 0.038002 s |
| `trigger → lane_separated` | 0.655984 s | 0.667157 s | 0.793306 s | 0.808414 s | 0.046153 s |
| `trigger → done` | 5.761277 s | 5.494773 s | 6.350484 s | 17.032763 s | 4.752508 s |

> **Run 004 분기 거동 관측**:
> 49회 실행에서는 목표 인접 차선(`lane -4`)으로 차선 변경을 정상 완료하였으나, Run 004는 해당 스폰 좌표의 미세 위치 특성으로 `_driving_adjacent_lanes()`가 빈 리스트를 반환하여 인접 차선 대신 직진 후 road 8 램프로 분기 주행(종료 시 물리 이격 거리 약 31.6 m)하였습니다. 해당 실행 또한 독립 컨트롤러 배정, 물리 분리, 독자 변위 불변식을 충족하여 정상 PASS로 처리되었습니다.

## 10. Defect Found During Validation

### VAL-S01: CARLA Child Process Surviving Wrapper Termination

- **Before Symptom**: 1차 50회 검증 시도 중 Run 1~49는 정상 통과하였으나, Run 50 종료 시 CARLA 서버 래퍼 스크립트(`CarlaUE4.sh`)만 종료되고 실제 바이너리(`CarlaUE4-Linux-Shipping`)가 종료되지 않아 포트 2000이 점유 상태로 잔류(cleanup failure 발생, 49/50 판정). 실패 증적은 `evidence_before_fix/split_cleanup_attempt_49of50/`에 보존됨.
- **Root Cause**: 러너의 `stop_process()`가 wrapper의 `Popen` 프로세스 종료만 `wait()`하고, 동일 프로세스 그룹 내 생성된 자식 프로세스의 잔류 여부를 확인하지 않음.
- **Fix**: 프로세스 그룹 ID(`os.killpg`) 단위로 생존 프로세스를 검사하여 grace period 이후에도 잔류 시 SIGKILL로 강제 정리하고 포트 해제를 대기하도록 수정.
- **After**: 수정 후 전체 50회를 처음부터 재실행하여 50/50 완료 및 cleanup failure 0을 달성함.

## 11. Regression Test

- `tests/unit/test_real_carla_split_runner.py`: 자식 프로세스 잔류 시 프로세스 그룹 정리 로직 검증 (`test_owned_child_is_killed_after_wrapper_exits_on_term`)
- `tests/unit/test_real_carla_split_validation.py`: 불변식 위반(멤버십 오류, 간격 미달, 충돌, 컨트롤러 오류 등)에 대한 평가자 판정 검증
- `tests/unit/test_real_carla_split_audit.py`: 원본 JSON 증적에 대한 독립 감사 일치성 검증
- **결과**: 47 passed (CARLA-free baseline 21/21 passed와 별도로 관리됨)

## 12. Independent Audit

- **대상 데이터**: `evidence/run001` ~ `evidence/run050` (50개 디렉토리 전수)
- **필수 파일 점검**: `ready.json`, `initial_snapshot.json`, `trigger_snapshot.json`, `transition_events.json`, `final_snapshot.json`, `result.json` 누락 0건
- **요약 대조**: `runs_summary.csv` (50 rows), `timing_summary.csv` (50 rows)와 원본 JSON 전수 일치
- **불변식 위반**: 0건
- **포트 정리 상태**: 감사 시점 포트 2000, 2001, 18801, 18802 모두 해제(free) 확인 완료
- **감사 출력물**: `validation/real_carla_50runs/audit/` (`audit_summary.json`, `audit_runs.csv`, `audit_timing.csv`)

## 13. Limitations

- **Fixed Condition Validation**: Town06 고정 스폰, 단일 목표 속도, 단일 날씨 조건에 한정된 검증입니다.
- **Single Scenario Configuration**: 3대 플래툰 단일 구성으로 진행되었습니다.
- **CARLA Simulation**: CARLA 0.9.13 가상 환경 검증이며 실차 검증이 아닙니다.
- **Off-screen Rendering**: `-RenderOffScreen` 모드 시뮬레이션입니다.
- **Vehicle Fallback**: `vehicle.carlamotors.carlacola` 모델을 사용했습니다.
- **OpenClaw Agent Copy Not tested**: 실행 환경에 `openclaw:local` 이미지, Discord gateway, 소스 에이전트 미제공으로 에이전트 복제 검증은 제외되었습니다.
- **Generalization 미검증**: 다양한 도로 기하, 기상 조건, 센서 노이즈에 대한 일반화는 검증되지 않았습니다.

### Cross-Scenario Comparison

| Scenario | Repository | Real CARLA Runs | Verification |
|---|---|---:|---|
| Transfer | Truckclaw-improve | 10 | request → physical merge → logical membership |
| Split | Truckclaw_copyable | 50 | logical detach → physical separation → independent driving |
| Leader Change | Truckclaw_movable | 50 | leader/controller transition → physical maneuver → old leader rejoin |

## 14. Evidence Location

- **최종 검증 증적**: `validation/real_carla_50runs/evidence/run001/` ~ `run050/`
- **결함 수정 전 증적**: `validation/real_carla_50runs/evidence_before_fix/split_cleanup_attempt_49of50/`
- **실행 요약 CSV**: `validation/real_carla_50runs/runs_summary.csv`
- **타이밍 요약 CSV**: `validation/real_carla_50runs/timing_summary.csv`
- **독립 감사 스크립트**: `validation/real_carla_50runs/tools/audit_raw_evidence.py`
