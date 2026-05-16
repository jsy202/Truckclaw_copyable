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
주행 시작 (3대 군집, SYNC_SPEED 18km/h)
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
export PYTHONPATH=$PYTHONPATH:/opt/carla-0.9.6/PythonAPI/carla
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
