# Truckclaw — 군집 분기 시나리오 + OpenClaw 복제

CARLA 시뮬레이터에서 3대 트럭이 단일 군집으로 주행하다가, 한 대의 목적지가 달라지면 그 차량이 분기(branch)되고 자신만의 AI 에이전트(OpenClaw)를 복제해서 단독 운행하는 시스템이다.

---

## 아키텍처

```
Host
├── Vehicle Docker (truck_1)
│     └── OpenClaw Docker (openclaw-truck1)  ← 항상 실행
├── Vehicle Docker (truck_2)
│     └── (OpenClaw 없음)
└── Vehicle Docker (truck_3)
      └── OpenClaw Docker (openclaw-truck3)  ← 분기 시 자동 생성
```

MVP에서는 Vehicle Docker를 호스트 디렉터리로 에뮬레이션하고, 호스트에서 `docker run`을 직접 실행한다.

```
브리지 서버 (포트 18801)
    ↕ REST API
CARLA 시나리오 (포트 18802)
    ↕
CARLA Town06 (포트 2000)
```

---

## 차량 구성

| 차량 | 역할 | OpenClaw |
|------|------|----------|
| truck_1 | 리더 | openclaw-truck1 (항상 실행) |
| truck_2 | 팔로워 | 없음 |
| truck_3 | 팔로워 → 분기 후 단독 리더 | openclaw-truck3 (분기 시 생성) |

---

## 분기 흐름

```
CRUISE
  목적지 불일치 감지 (자동 30초 or 키 '3')
  ↓
GAP_OPEN
  truck_3의 follow gap을 20m로 설정
  truck_2 ↔ truck_3 간격이 18m 이상 될 때까지 대기
  ↓
DETACH
  Platoon.split(2, 2) 호출 → truck_3 분리
  truck_3 autopilot으로 단독 주행
  ↓
SPAWN_OC
  replicator.py 실행 → OpenClaw 복제
  ↓
DONE
  truck_1 + truck_2: 2대 군집 계속 주행
  truck_3: 단독 주행 + openclaw-truck3 실행 중
```

---

## OpenClaw 복제 원리

분기 시 truck_1의 OpenClaw 파일을 **선택적으로** 복사한다.

| 파일 | 전략 | 이유 |
|------|------|------|
| `SOUL.md` | 복사 후 patch | 행동 방식은 동일, 정체성 참조만 교체 |
| `SKILL.md` | 그대로 복사 | 협상 절차는 차량 무관 |
| `TOOLS.md` | 그대로 복사 | CLI 명령어 동일 |
| `AGENTS.md` | 재생성 | bot 이름, platoon_id, 소속이 완전히 다름 |
| `vehicle_destinations.json` | 재생성 | truck_3의 목적지(dest_b), 단독 platoon |
| `platoon_decision_context.json` | 재생성 | truck_3의 브리지/멤버 컨텍스트 |
| Discord 토큰 | 복사 금지 | 환경변수로만 주입 |
| 활성 transfer 상태 | 복사 금지 | truck_1 협상이 truck_3에 오염되면 안 됨 |

V2V 전송은 64KB 청크 단위 로컬 파일 복사로 에뮬레이션한다.

---

## 프로젝트 구조

```
Truckclaw_copyable/
├── scenario/
│   └── examples/
│       ├── two_platoon_truck_scenario.py   # 기존 양방향 이송 (수정 안 함)
│       └── single_platoon_branch_scenario.py  # 신규: 단일 군집 분기
│
├── openclaw_migration/
│   └── replicator.py       # OpenClaw 번들 → 복원 → docker run
│
├── agents/
│   ├── platoon-a/          # truck_1 OpenClaw 설정 (기존)
│   ├── platoon-b/          # 기존
│   └── truck3/             # truck_3 전용 템플릿 (신규)
│       ├── SOUL.md
│       ├── AGENTS.md
│       ├── TOOLS.md
│       ├── data/
│       └── skills/
│
├── bridge/
│   ├── platoon_bridge_server.py   # 협상 상태 REST API
│   └── platoon_bridge_ctl.py
│
├── config/
│   └── simulation.json     # 속도/간격/타임아웃 파라미터
│
├── docker-compose.yml                  # 기존 양방향 시나리오
└── docker-compose.single-platoon.yml   # 단일 군집 시나리오
```

---

## 실행

### 사전 준비

```bash
# truck_1 config 디렉터리 초기화
cp -r agents/platoon-a/ .openclaw-truck1/

# 환경변수 설정
cp .env.example .env.single-platoon
# TRUCK1_DISCORD_BOT_TOKEN, TRUCK1_OPENCLAW_GATEWAY_TOKEN 입력
```

### 서버 실행

```bash
# 브리지 서버
python3 bridge/platoon_bridge_server.py

# truck_1 OpenClaw
docker compose -f docker-compose.single-platoon.yml up openclaw-truck1
```

### CARLA 시나리오

```bash
export PYTHONPATH=$PYTHONPATH:/opt/carla-0.9.6/PythonAPI/carla
python3 scenario/examples/single_platoon_branch_scenario.py
# 30초 후 자동 분기, 또는 '3' 키로 수동 트리거
```

### CARLA 없이 복제만 테스트

```bash
python3 openclaw_migration/replicator.py --dry-run
```

---

## 주요 파라미터 (`config/simulation.json`)

| 파라미터 | 기본값 | 설명 |
|----------|--------|------|
| `sync_speed_kmh` | 18 | 군집 기본 주행 속도 |
| `open_gap_m` | 20 | 분기 전 목표 간격 |
| `open_gap_ready_m` | 18 | 분기 트리거 최소 간격 |
| `platoon_spacing_m` | 18 | 초기 차간 간격 |

---

## 포트

| 포트 | 용도 |
|------|------|
| 2000 | CARLA 시뮬레이터 |
| 18801 | 브리지 서버 REST API |
| 18802 | CARLA 트리거 수신 |
| 18791 | openclaw-truck1 gateway |
| 18792 | openclaw-truck3 gateway (분기 후 생성) |
