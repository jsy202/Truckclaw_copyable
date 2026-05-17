# Truckclaw 🚛 (트럭 군집 분기 시뮬레이션 + OpenClaw AI 에이전트 연동)

CARLA 0.9.6 시뮬레이터에서 3대 트럭 군집이 주행하다가 AI 에이전트(OpenClaw)가 목적지를 확인하고 불일치 차량을 자동으로 분기시키는 시뮬레이션 시스템.

---

## 🚀 시나리오 개요

```
3대 군집 (truck_1, truck_2, truck_3) 주행 중
  ↓
사람이 Discord에서 @TRUCKCLAW2 에게 목적지 확인 요청
  ↓
TRUCKCLAW2 (truck_1 에이전트):
  → vehicle_destinations.json 읽기
  → 목적지 목록 채널에 공유
  → truck_3 목적지 불일치 감지
  → truck_3 OpenClaw 컨테이너 복제
  → 부팅 완료 후 @TRUCKCLAW3 호출
  ↓
TRUCKCLAW3 (truck_3 에이전트):
  → "분기할게" 선언
  → 브리지 트리거 실행
  ↓
CARLA: truck_3 차선변경 → 단독 주행
남은 군집 (truck_1, truck_2): x=600 분기점에서 lane=-4 진입
```

---

## 🏗 아키텍처

```
Discord 채널 (1505104257634926602)
  TRUCKCLAW2 <@1505082171050688552>  ↔  TRUCKCLAW3 <@1505107885573673041>
        │                                        │
        ▼                                        ▼
  Bridge Server (port 18801)          Bridge Server (port 18801)
  협상 상태 관리 REST API
        │
        │ commit → trigger
        ▼
  CARLA Trigger Server (port 18802)
  /start_replicate  → truck_3 컨테이너 복제
  /start_merge      → truck_3 차선변경 트리거
        │
        ▼
  CARLA Town06 (port 2000)
  물리 시뮬레이션
```

---

## 📂 프로젝트 구조

```
Truckclaw_copyable/
├── carla_start.sh                  # CARLA 0.9.6 원클릭 실행
├── run_truckclaw.sh                # 시나리오 원클릭 실행
├── carla_stop.sh                   # CARLA 종료
├── .env.single-platoon             # 봇 토큰 설정 (직접 생성)
├── scenario/
│   └── examples/
│       └── single_platoon_branch_scenario.py  # 메인 시나리오
├── bridge/
│   ├── platoon_bridge_server.py    # REST API 브리지 서버 (18801)
│   └── platoon_bridge_ctl.py       # 브리지 CLI 도구
├── agents/
│   ├── platoon-a/                  # TRUCKCLAW2 에이전트 설정
│   │   ├── AGENTS.md
│   │   ├── SOUL.md
│   │   ├── TOOLS.md
│   │   ├── skills/platoon-negotiator/SKILL.md
│   │   └── data/
│   │       ├── vehicle_destinations.json
│   │       └── platoon_decision_context.json
│   └── truck3/                     # TRUCKCLAW3 에이전트 템플릿
│       ├── AGENTS.md
│       ├── SOUL.md
│       ├── skills/platoon-negotiator/SKILL.md
│       └── data/
│           ├── vehicle_destinations.json
│           └── platoon_decision_context.json
├── openclaw_migration/
│   └── replicator.py               # truck_3 컨테이너 복제기
├── config/
│   └── simulation.json             # 시뮬레이션 파라미터
└── docker-compose.single-platoon.yml
```

---

## 🛠 실행 방법

### 사전 준비

1. CARLA 0.9.6 설치: `/opt/carla-0.9.6/`
2. Docker 설치 및 실행
3. OpenClaw 이미지 빌드: `docker build -t openclaw:local .`
4. `.env.single-platoon` 생성:

```bash
cp .env.example .env.single-platoon
# 아래 값 설정:
# TRUCK1_DISCORD_BOT_TOKEN=<TRUCKCLAW2 봇 토큰>
# TRUCK3_DISCORD_BOT_TOKEN=<TRUCKCLAW3 봇 토큰>
# OPENCLAW_IMAGE=openclaw:local
```

### 1단계 — CARLA 실행

```bash
./carla_start.sh
```

- CARLA 0.9.6 windowed 모드로 실행
- Town06 맵 자동 로드
- 마우스 캡처 자동 해제 (xdotool)

### 2단계 — 시나리오 실행

```bash
./run_truckclaw.sh
```

- 브리지 서버 자동 시작 (18801)
- Docker 컨테이너 상태 표시
- 3대 군집 CARLA 시뮬레이션 시작
- 포트 18802에서 OpenClaw 트리거 대기

### 3단계 — Discord에서 협상 시작

Discord 채널 `1505104257634926602`에 입력:

```
<@1505082171050688552> 군집 목적지 확인하고 다른 차량 있으면 split 해줘
```

### 4단계 — 자동 진행

이후는 에이전트가 자동으로 처리:

| 단계 | 에이전트 | 행동 |
|------|---------|------|
| 1 | TRUCKCLAW2 | vehicle_destinations.json 읽고 목적지 목록 공유 |
| 2 | TRUCKCLAW2 | truck_3 불일치 감지 → replicate 실행 |
| 3 | TRUCKCLAW2 | truck_3 부팅 확인 후 @TRUCKCLAW3 호출 |
| 4 | TRUCKCLAW3 | "분기할게" 선언 → 브리지 트리거 실행 |
| 5 | CARLA | truck_3 차선변경 시작 |
| 6 | CARLA | 남은 2대 x=600에서 lane=-4 진입 |

---

## ⌨️ 키보드 단축키 (시나리오 실행 중)

| 키 | 동작 |
|----|------|
| `3` | 수동 분기 트리거 (OpenClaw 없이 즉시 테스트) |
| `r` | 시나리오 리셋 |
| `Ctrl-C` | 종료 |

---

## ⚙️ 설정 파일

### `config/simulation.json`

| 파라미터 | 기본값 | 설명 |
|---------|--------|------|
| `sync_speed_kmh` | 15 | 군집 기본 주행 속도 |
| `platoon_spacing_m` | 18 | 군집 차간 거리 |
| `open_gap_ready_m` | 18 | 분기 전 확보할 최소 간격 |

### `agents/platoon-a/data/vehicle_destinations.json`

목적지 설정 파일. 여기서 각 truck의 `destination_id`를 바꾸면 분기 대상이 달라진다.

```json
{
  "vehicles": {
    "platoon_a_truck0": { "destination_id": "dest_a" },
    "platoon_a_truck1": { "destination_id": "dest_a" },
    "platoon_a_truck2": { "destination_id": "dest_b" }  ← 이게 다르면 분기
  }
}
```

---

## 🔌 브리지 API

```bash
# 상태 확인
python3 bridge/platoon_bridge_ctl.py snapshot
python3 bridge/platoon_bridge_ctl.py readiness

# truck_3 복제 트리거
python3 bridge/platoon_bridge_ctl.py replicate platoon_a_truck2

# 분기 트리거 (수동)
curl -X POST http://127.0.0.1:18802/start_merge
```

---

## ⚠️ 주의 사항

- CARLA 0.9.6 전용 (`-RenderOffScreen` 플래그 사용 불가 — segfault)
- `BRANCH_AUTO_S = 0.0` — 자동 타이머 비활성화, OpenClaw 트리거만 사용
- 키보드 `3`으로 수동 테스트 가능 (OpenClaw 없이)
- CARLA 창 클릭 시 마우스 캡처됨 → `Alt+Tab`으로 포커스 전환

