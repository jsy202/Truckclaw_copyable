# Truckclaw — 군집 분기 시나리오 + OpenClaw 에이전트 복제

CARLA Town06 고속도로에서 3대 트럭이 단일 군집으로 주행하다가, 한 대의 목적지가 달라지면 그 차량이 분기되고 자신만의 AI 에이전트(OpenClaw)를 복제해서 단독 운행하는 시스템이다.

---

## 시나리오

```
[truck_1] → [truck_2] → [truck_3]
  리더       팔로워       팔로워(분기 대상)
```

| 차량 | 역할 | OpenClaw | 목적지 |
|------|------|----------|--------|
| truck_1 | 리더 | openclaw-truck1 (항상 실행) | dest_a |
| truck_2 | 팔로워 | 없음 | dest_a |
| truck_3 | 팔로워 → 분기 후 단독 | openclaw-truck3 (분기 시 생성) | dest_b |

---

## 분기 흐름

```
주행 시작 (3대 군집, SYNC_SPEED 10km/h)
  ↓ 30초 후 자동 또는 '3' 키 수동
목적지 불일치 감지
  truck_3 목적지(dest_b) ≠ 군집 목적지(dest_a)
  ↓
① GAP_OPEN
   truck_3 목표 간격 → 20m
   truck_2 ↔ truck_3 거리 18m 이상을 0.5초 안정적으로 유지하면 다음 단계
  ↓
② DETACH
   platoon.split(2, 2) 호출
   truck_3 군집에서 물리적 분리 → autopilot 단독 주행
   남은 군집: truck_1 + truck_2 (2대)
  ↓
③ SPAWN_OC — OpenClaw 복제 (핵심)

   [Bundle 1] truck_1 컨테이너 안에서:
     docker save openclaw:local → openclaw_image.tar (976MB)
     → V2V 청크 전송 에뮬레이션 → truck_3 수신 버퍼

   [Bundle 2] config 파일 선택적 패키징:
     SOUL.md (patch)  TOOLS.md (복사)  SKILL.md (복사)
     AGENTS.md (재생성)  vehicle_destinations.json (재생성)
     platoon_decision_context.json (재생성)
     → config_bundle.tar → truck_3 수신 버퍼

   [실행] truck_3 컨테이너 안에서:
     docker load openclaw_image.tar
     config 압축 해제 → /data/openclaw/
     docker run --name openclaw-truck3 (포트 18792)
  ↓
④ DONE
   truck_1 + truck_2: 2대 군집 계속 주행
   truck_3: 단독 주행 + openclaw-truck3 실행 중
```

---

## 복제된 truck_3이 아는 것

| 항목 | truck_1 (원본) | truck_3 (복제 후) |
|------|---------------|-----------------|
| 이름 | TRUCKCLAW2 | TRUCKCLAW3 |
| 소속 | platoon_a (3대) | platoon_truck3 (혼자) |
| 목적지 | dest_a | **dest_b** |
| 역할 | 리더 (군집) | 리더 (단독) |
| 분기 출처 | - | platoon_a / platoon_a_truck2 |
| 분기 이유 | - | destination_mismatch |
| Discord 채널 | 1505104257634926602 | **동일 채널** |

---

## 선택적 파일 복사 원칙

| 파일 | 처리 | 이유 |
|------|------|------|
| SOUL.md | 복사 + patch | 행동 방식은 동일, 이름·소속만 교체 |
| SKILL.md | 그대로 복사 | 협상 절차는 차량 무관 |
| TOOLS.md | 그대로 복사 | CLI 명령어 동일 |
| AGENTS.md | 재생성 | 정체성이 완전히 다름 |
| vehicle_destinations.json | 재생성 | truck_3만의 목적지·소속 |
| platoon_decision_context.json | 재생성 | truck_3의 브리지·채널 컨텍스트 |
| Discord 봇 토큰 | **복사 금지** | 같은 계정 동시 로그인 → 충돌 |
| 활성 transfer 상태 | **복사 금지** | truck_1 협상이 truck_3에 오염 |

---

## Docker-in-Docker 구조

```
Host
├── vehicle-truck1 (Docker)
│     └── openclaw-truck1 (Docker, 포트 18789)  ← 항상 실행
│           /data/openclaw/SOUL.md → "You are TRUCKCLAW2..."
│
├── vehicle-truck2: 없음 (순수 CACC 팔로워)
│
└── vehicle-truck3 (Docker, 분기 시 생성)
      └── openclaw-truck3 (Docker, 포트 18792)
            /data/openclaw/SOUL.md → "You are TRUCKCLAW3..."
            /data/openclaw/data/vehicle_destinations.json → dest_b
```

MVP: Vehicle Docker = 호스트 디렉터리 에뮬레이션, Docker 소켓 공유로 DinD 대체

---

## 아키텍처

```
브리지 서버 (포트 18801)  ↔  CARLA 시나리오 (포트 18802)  ↔  CARLA Town06 (포트 2000)
```

---

## 분기 로직 수정 이력

| 수정 | 내용 |
|------|------|
| GAP 하이스테리시스 | 18m 순간 초과 → 50 tick(0.5초) 연속 유지 후 DETACH |
| 스레드 Lock | OpenClaw 복제 완료 시 `state = DONE` 쓰기를 Lock으로 보호 |

---

## 프로젝트 구조

```
Truckclaw_copyable/
├── scenario/examples/
│   ├── single_platoon_branch_scenario.py   ← 메인 시나리오 (CARLA)
│   └── two_platoon_truck_scenario.py       ← 기존 양방향 시나리오 (수정 안 함)
│
├── openclaw_migration/
│   ├── replicator.py     ← 두 tar 번들 생성 + V2V 전송 + docker run
│   ├── monitor.py        ← 터미널 실시간 컨테이너 모니터
│   ├── reset.py          ← 시나리오 초기 상태 복귀
│   └── test_migration.py ← CARLA 없이 OpenClaw 복제만 테스트
│
├── vehicle/
│   ├── Dockerfile        ← Docker CLI 포함 차량 컨테이너 이미지
│   └── entrypoint.sh     ← 시작 시 openclaw 자동 실행
│
├── agents/
│   ├── platoon-a/        ← truck_1 OpenClaw 설정 (행동 DNA 소스)
│   └── truck3/           ← truck_3 전용 템플릿 (정체성 파일)
│
├── bridge/
│   ├── platoon_bridge_server.py   ← 협상 상태 REST API (포트 18801)
│   └── platoon_bridge_ctl.py
│
├── config/simulation.json         ← 속도·간격 파라미터
├── run_scenario.sh                ← CARLA 연결 실행 스크립트
├── docker-compose.single-platoon.yml
└── .env.single-platoon            ← 봇 토큰 (git 제외)
```

---

## 실행

### CARLA 없이 OpenClaw 복제 테스트

```bash
python3 openclaw_migration/test_migration.py
```

### CARLA 포함 전체 시나리오

```bash
# CARLA Docker no-rendering 실행 후
./run_scenario.sh
# '3' = 분기 트리거   'r' = 리셋   Ctrl-C = 종료
```

### 단계별 수동 실행

```bash
# 1. 브리지 서버
python3 bridge/platoon_bridge_server.py

# 2. truck_1 OpenClaw
docker compose -f docker-compose.single-platoon.yml up vehicle-truck1

# 3. CARLA 시나리오
export PYTHONPATH=$PYTHONPATH:/opt/carla-0.9.13/PythonAPI/carla
python3 scenario/examples/single_platoon_branch_scenario.py
```

---

## 주요 파라미터 (config/simulation.json)

| 파라미터 | 기본값 | 설명 |
|----------|--------|------|
| `sync_speed_kmh` | 18 | 군집 기본 주행 속도 |
| `open_gap_m` | 20 | 분기 전 목표 간격 |
| `open_gap_ready_m` | 18 | 분기 트리거 최소 간격 |
| `platoon_spacing_m` | 18 | 초기 차간 간격 |

## 포트

| 포트 | 용도 |
|------|------|
| 2000 | CARLA 시뮬레이터 |
| 18801 | 브리지 서버 REST API |
| 18789 | openclaw-truck1 gateway |
| 18792 | openclaw-truck3 gateway (분기 후) |

---

## 기술적 상세

### 알고리즘

#### CACC (Cooperative Adaptive Cruise Control)

팔로워 차량의 참조 속도 계산:

```
v_ref = v_lead + 0.55 × (gap - desired_gap) + 0.80 × (v_lead - v_ego)
```

| 항 | 역할 |
|----|------|
| `v_lead` | 선행차 속도 기준 |
| `0.55 × (gap - desired_gap)` | 간격 피드백 — 간격이 부족하면 감속, 넓으면 가속 |
| `0.80 × (v_lead - v_ego)` | 속도 차 피드백 — 선행차와 속도를 맞춤 |

속도는 `[v_lead - 14 km/h, v_lead + 20 km/h]` 범위로 클리핑.

#### GAP 하이스테리시스

```
단순 임계값: gap >= 18m → 즉시 DETACH  (순간 튐에 취약)
개선 후:     gap >= 18m 을 50 tick (0.5초) 연속 유지 → DETACH
```

```python
if gap >= OPEN_GAP_READY_M:
    self._gap_ok_count += 1
else:
    self._gap_ok_count = 0          # 한 번이라도 미달이면 리셋
if self._gap_ok_count >= 50:
    self.state = BranchState.DETACH
```

---

### 프롬프트 구조 (OpenClaw Agent)

OpenClaw는 차량마다 아래 파일들을 system prompt처럼 읽고 행동합니다.

```
/data/openclaw/
├── SOUL.md                          ← 성격·판단 기준 (system prompt 역할)
├── AGENTS.md                        ← 신분·역할·제약
├── TOOLS.md                         ← 사용 가능한 CLI 명령어
├── skills/platoon-negotiator/
│   └── SKILL.md                     ← 협상 7단계 절차서
└── data/
    ├── vehicle_destinations.json    ← 목적지 진실 소스
    └── platoon_decision_context.json ← 브리지 URL·채널·멤버
```

**SOUL.md 핵심 구조:**
```
[정체성]  You are TRUCKCLAW3, solo vehicle in platoon_truck3.
[진실]    vehicle_destinations.json만 신뢰. 브리지 snapshot으로 상태 확인.
[말투]    짧고 사무적. 한국어 + 기계 필드는 영어.
[역할]    Solo Navigator — dest_b로 단독 주행.
[금지]    carla_complete 없이 "합류 완료" 금지.
          platoon_a의 활성 transfer 참조 금지.
```

---

### 하네스 구조

```
[시나리오 하네스 - single_platoon_branch_scenario.py]
  ├── BranchCoordinator          ← 상태머신 (CRUISE/GAP/DETACH/SPAWN/DONE)
  ├── ContainerMonitor           ← docker ps 폴링 (1초 주기, 백그라운드 스레드)
  ├── KeyInput                   ← termios 기반 논블로킹 키 입력
  └── SmoothCamera               ← CARLA spectator 부드러운 추적

[복제 하네스 - replicator.py]
  ├── create_image_bundle()      ← docker save → .tar (976MB)
  ├── create_config_bundle()     ← 선택적 파일 패키징 → .tar.gz
  ├── _v2v_transfer()            ← 64KB 청크 복사 (V2V 에뮬레이션)
  └── _load_and_run()            ← docker load + tar 해제 + docker run

[브리지 하네스 - platoon_bridge_server.py]
  REST API: pending → accepted → committed → splitting → merging → carla_complete
  포트: 18801

[대화 가드 - platoon_dialogue_guard.py]
  inbound gate: 자신에게 온 메시지인지 확인
  validate-json: 목적지 일치 여부 검증
  확인 전용 메시지 무시 (무한 응답 루프 방지)
```

---

### 엔지니어링 결정 기록

| 결정 | 이유 |
|------|------|
| 두 tar 번들 분리 | 이미지(런타임)와 설정(임무)을 명확히 구분. V2V 전송 현실성 |
| SOUL.md만 patch, SKILL.md는 복사 | 협상 방법(HOW)은 보편적, 정체성(WHO)만 교체 |
| AGENTS.md 재생성 | 6단계 협상 워크플로우가 truck_3 상황과 구조적으로 다름 |
| destinations.json 재생성 | 원본 그대로면 truck_3이 platoon_a 소속인 줄 알고 오작동 |
| Discord 토큰 복사 금지 | 동일 계정 동시 접속 → Discord 정책 위반 + 메시지 혼선 |
| Docker 소켓 공유 (DinD MVP) | true DinD 대비 설정 간단, 기능 동일 |
| 포트 18792 고정 (truck3) | truck1의 18789와 충돌 방지 |
| GAP 50 tick 하이스테리시스 | 0.5초 안정 확인으로 진동에 의한 조기 분리 방지 |
| threading.Lock on state write | SPAWN_OC 스레드와 메인 루프 경쟁 조건 방지 |

---

## Post-project Split & Agent Replication Verification

> 이 섹션은 **연구 종료 후(2026-10)** 수행한 검증 작업이다.
> 위의 설명과 설계 근거는 연구 당시 내용이며 수정하지 않았다.
> 아래에 적은 결함은 **이번 검증에서 처음 발견한 것**이다. 연구 당시 코드는 tag `research-baseline`(`24cee6b`)에 보존되어 있다.

### 검증 목적

분기 차량에 AI agent를 복제하는 과정이 실패하거나 지연될 때 다음이 지켜지는지 확인한다.

- **agent 없이 물리 분기가 일어나지 않는가**
- **복제된 agent가 올바른 정체성을 갖는가**

CARLA와 Docker 없이 확인한다.

### 테스트 구조

```text
[Production]  BranchCoordinator ─▶ BranchReplicator ─▶ docker save/load/run
              scenario ─▶ bridge /branch, agent ─▶ bridge /replicate ─▶ CARLA :18802
[Test]        BranchCoordinator (carla stub) ─▶ 실제 BranchReplicator ─▶ FakeDocker (subprocess.run 대체)
              pytest ─▶ 실제 bridge Handler (in-process) ─▶ FakeTriggerReceiver
```

### 발견한 결함 (실제 실행으로 재현) → 수정

| ID | 결함 | 수정 |
|---|---|---|
| DEF-C01 | `wait()`가 복제에 **실패한 뒤에도** True | `84e0d1a` |
| DEF-C06 | 그 결과 복제 실패 후에도 물리 분기(GAP) 진행 → agent 없는 분기 차량 | `84e0d1a` |
| DEF-C07 | MIGRATE timeout 없음 | `14a340b` |
| DEF-C05 | `/start_replicate` 후 분기 trigger가 오면 복제 2회 동시 실행 | `7645f7a` |
| DEF-C02 | 단독 CLI가 실패해도 exit 0 | `accfabc` |
| DEF-C04 | 시나리오가 존재하지 않는 `agents/truck2`를 정체성 템플릿으로 전달 → 복제 agent에 AGENTS.md와 destinations가 빠짐. 위 설계 근거 표의 "destinations.json 재생성" 의도와 어긋남 | `364a645` |
| DEF-C03 | 정체성 파일이 없어도 복제 "성공" | `e90256d` (+ `d0e2d31`: 이 commit에 들어간 문법 오류 수정) |
| DEF-C08 | 시나리오가 보고하는 `POST /branch`가 bridge에 없음(404, 오류가 무시됨) | `75922b7` (기록만 하는 최소 구현) |
| DEF-C09 | `/replicate`가 알 수 없는 차량으로도 CARLA trigger | `b2695bb` |

Truckclaw-improve의 bridge transfer 결함 11건도 이 저장소에 그대로 있다. 실행으로 재현했지만 이 저장소에서는 수정하지 않았다.

### 결과 (2026-10-01, 로컬)

- 21 passed, 0 xfailed, 0 failed. 10회 연속 실행에서 같은 결과였다.
- 같은 테스트를 baseline 소스에 실행하면 12 failed, 9 passed다.
- CI(`.github/workflows/test.yml`)는 아직 push하지 않아 **GitHub에서 실행된 기록이 없다.**

### Limitations

- CARLA 물리 분기, 실제 Docker 및 Discord 동작은 확인하지 않았다.
- 신규 agent의 gateway readiness는 확인하지 않는다.
- `/branch`는 기록만 하며 bridge 멤버십은 바꾸지 않는다.
- README의 포트 표기(18792)와 코드(18793)가 다르다.

문서: [validation/](validation/)

---

## Post-project Real-CARLA Validation

Logical and physical state consistency was observed in all 50 runs under the tested fixed scenario.

### Test Environment

- **Simulator**: CARLA 0.9.13 (Python 3.7.17 client)
- **Host OS**: Ubuntu 22.04 LTS (Linux 6.8.0-138-generic)
- **Hardware**: NVIDIA GeForce RTX 3060
- **Rendering**: `-RenderOffScreen` (실제 CARLA 물리 시뮬레이션이며 디스플레이 출력만 생략)
- **Map**: Town06
- **Vehicle Blueprint**: `vehicle.carlamotors.carlacola` (기존 blueprint fallback)

### Validation Criteria

Split 동작 완료 판정은 단순 `DONE` 상태 도달이 아닌 아래 invariant를 동시에 만족해야 합니다:
- 최종 시나리오 상태: `DONE`
- 최종 플래툰 멤버십: 기존 대열 `[truck0, truck1]`, 분기 차량 `truck2` 독립 분리
- 컨트롤러 배정: `truck2`에 독립 `LeadNavigator` 정상 배정
- 간격 조건: `gap_ready` 관측 (간격 >= 15.0 m 및 10 ticks 안정 유지)
- 차선 및 물리적 분리: 실제 차선 또는 물리적 이격 확인
- 독립 주행: `truck2`의 `DONE` 이후 추가 변위 >= 0.5 m
- 생존 및 충돌: 전 차량 actor 생존 및 무충돌 (collision count 0)

### Results

| Metric | Result |
|---|---:|
| Runs | 50 |
| Success | 50/50 |
| Logical / Physical Consistency | 50/50 |
| Timeout | 0 |
| Crash | 0 |
| Cleanup Failure | 0 |

*참고: Agent Copy는 `openclaw:local` 이미지, Discord gateway, 소스 에이전트 환경 부재로 `Not tested`로 분리되었으며, CARLA 물리 분기 결과에 합산되지 않습니다.*

### Timing

| Phase | Mean | P50 (Median) | P95 | Max | Min |
|---|---:|---:|---:|---:|---:|
| `trigger → logical_detach` | 0.006440 s | 0.006252 s | 0.008413 s | 0.009025 s | 0.005469 s |
| `trigger → gap_ready` | 0.047792 s | 0.048274 s | 0.056017 s | 0.063378 s | 0.038002 s |
| `trigger → lane_separated` | 0.655984 s | 0.667157 s | 0.793306 s | 0.808414 s | 0.046153 s |
| `trigger → done` | 5.761277 s | 5.494773 s | 6.350484 s | 17.032763 s | 4.752508 s |

*49개 run은 인접 차선(lane -4)으로 변경 완료하였으며, Run 004는 waypoint geometry 특성으로 road 8 램프 분기 주행(물리 이격 약 31.6 m)으로 invariant를 충족하였습니다.*

### Validation Defect Found

- **VAL-S01 (CARLA child process 잔류 및 포트 미해제)**:
  - **현상**: 1차 50회 검증 중 Run 50에서 `CarlaUE4.sh` 래퍼 프로세스 종료 후 `CarlaUE4-Linux-Shipping` 자식 프로세스가 잔류하여 포트 2000이 점유된 상태로 남아 cleanup failure 발생 (`evidence_before_fix/`에 원본 보존).
  - **원인**: `stop_process()`가 래퍼 `Popen` 종료만 확인하고 동일 프로세스 그룹 내 자식 잔류 여부를 확인하지 않음.
  - **수정**: 프로세스 그룹 단위 감시 및 유예 후 SIGKILL escalation 적용.
  - **회귀 검증**: `test_owned_child_is_killed_after_wrapper_exits_on_term` 통과 후 전체 50회 처음부터 재실행하여 50/50 PASS 및 cleanup failure 0 달성.

### Limitations

- **Fixed Condition**: Town06 단일 고정 spawn, 단일 목표 속도, 단일 날씨 조건에서만 검증되었습니다.
- **Single Scenario Configuration**: 3대 플래툰 단일 설정입니다.
- **CARLA Simulation**: CARLA 0.9.13 시뮬레이션 환경 검증이며 실차 검증이 아닙니다.
- **Off-screen Rendering**: `-RenderOffScreen` 모드 시뮬레이션입니다.
- **Blueprint Fallback**: `vehicle.carlamotors.carlacola` 모델을 사용했습니다.
- **Agent Copy Not tested**: 환경 부재로 Agent Copy는 테스트 대상에서 제외되었습니다.
- **Generalization 미검증**: 다양한 환경에 대한 일반화는 검증되지 않았습니다.

자세한 실험 데이터, 통계 및 감사 내역은 [validation/real_carla_50runs/validation_report.md](validation/real_carla_50runs/validation_report.md)를 참고하십시오.


