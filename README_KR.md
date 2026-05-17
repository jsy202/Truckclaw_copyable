# Truckclaw 🚛

CARLA 0.9.13 자율주행 시뮬레이터에서 3대 트럭(소방차) 군집이 주행하다가, OpenClaw AI 에이전트가 Discord를 통해 목적지를 확인하고 불일치 차량을 자동으로 분기시키는 시뮬레이션 시스템.

---

## 📌 핵심 개념

### 이 프로젝트가 하는 일

1. CARLA Town06 맵에서 트럭 3대가 군집(Platoon) 주행
2. 사람이 Discord에서 AI 에이전트(TRUCKCLAW2)에게 "목적지 확인해줘" 라고 말함
3. TRUCKCLAW2가 JSON 파일을 읽어 각 트럭의 목적지를 확인하고 채널에 공유
4. truck_3의 목적지가 나머지와 다르면 → OpenClaw 컨테이너 복제 → TRUCKCLAW3 에이전트 생성
5. TRUCKCLAW3이 "분기할게"라고 선언하고 CARLA에 트리거 전송
6. CARLA에서 truck_3이 차선변경으로 군집 이탈 → 단독 주행
7. 남은 2대(truck_1, truck_2)는 x=600 분기점에서 lane=-4로 진입

### OpenClaw란?

OpenClaw는 Discord 봇 형태로 동작하는 AI 에이전트 플랫폼. 각 트럭마다 독립적인 OpenClaw 컨테이너가 실행되며, SOUL.md(성격), AGENTS.md(행동 규칙), SKILL.md(협상 절차)를 읽고 자율적으로 판단해 Discord에서 대화하고 브리지 API를 호출한다.

### 복제(Replication)란?

truck_3은 처음에 컨테이너가 없다. 분기가 필요할 때 truck_1의 OpenClaw 이미지와 설정을 복사해 truck_3 전용 컨테이너를 동적으로 생성한다. 이것이 "복제"다. 복제 후 truck_3 에이전트(TRUCKCLAW3)가 Discord에 참여해 분기 의사를 표명한다.

---

## 🔄 전체 흐름

```
[사람]
  Discord 채널에 입력:
  "<@1505082171050688552> 군집 목적지 확인하고 다른 차량 있으면 split 해줘"
        │
        ▼
[TRUCKCLAW2 — truck_1 에이전트]
  1. vehicle_destinations.json 읽기
  2. 목적지 목록 Discord에 공유:
       "군집 목적지 확인 결과:
        - truck_1: dest_a
        - truck_2: dest_a
        - truck_3: dest_b  ← 다름!"
  3. "truck_3 목적지 불일치 → 복제 시작"
  4. platoon_bridge_ctl.py replicate platoon_a_truck2 실행
     → 브리지(18801) → CARLA(18802/start_replicate) → truck_3 컨테이너 생성
  5. docker ps로 openclaw-truck3 부팅 확인 (최대 30초 대기)
  6. "<@1505107885573673041> 너는 dest_b야, 분기 필요해. 트리거 눌러줘"
        │
        ▼
[TRUCKCLAW3 — truck_3 에이전트 (방금 복제됨)]
  7. vehicle_destinations.json 읽어 자신의 목적지(dest_b) 확인
  8. "<@1505082171050688552> 확인, dest_b로 분기할게"
  9. platoon_bridge_ctl.py trigger-merge platoon_a_truck2 실행
     → 브리지(18801) → CARLA(18802/start_merge) → 분기 트리거
        │
        ▼
[CARLA 시뮬레이터]
  10. truck_3: GAP 확보 → 차선변경(lane=-3 → lane=-4) → 단독 주행
  11. truck_1, truck_2: x=600 도달 시 lane=-4 진입 (분기점 이탈)
        │
        ▼
[TRUCKCLAW3]
  12. 브리지 readiness 확인 → carla_complete 감지
  13. "<@1505082171050688552> 분기 완료. status: carla_complete"
```

---

## 🏗 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│                    Discord 채널 1505104257634926602              │
│                                                                  │
│  사람 → @TRUCKCLAW2 목적지 확인해줘                               │
│                                                                  │
│  TRUCKCLAW2 <@1505082171050688552>                               │
│  (openclaw-truck1 컨테이너)                                       │
│       ↕ Discord 메시지                                            │
│  TRUCKCLAW3 <@1505107885573673041>                               │
│  (openclaw-truck3 컨테이너 — 복제로 생성)                         │
└──────────────┬──────────────────────────┬───────────────────────┘
               │ REST API                 │ REST API
               ▼                          ▼
┌──────────────────────────────────────────────────────────────────┐
│              Bridge Server  http://127.0.0.1:18801               │
│                                                                  │
│  POST /replicate   → truck_3 복제 요청                            │
│  POST /transfers   → transfer 등록                               │
│  GET  /snapshot    → 현재 상태 조회                               │
│  GET  /readiness   → CARLA 물리 준비 상태 조회                    │
│  POST /reload      → 상태 초기화                                  │
└──────────────────────────┬───────────────────────────────────────┘
                           │ HTTP trigger
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│           CARLA Trigger Server  http://127.0.0.1:18802           │
│                                                                  │
│  POST /start_replicate  → replicator.py 실행 (truck_3 생성)      │
│  POST /start_merge      → BranchCoordinator.trigger() 호출       │
└──────────────────────────┬───────────────────────────────────────┘
                           │ CARLA Python API
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                  CARLA 0.9.13 Town06  port 2000                  │
│                                                                  │
│  truck_1 (LeadNavigator)   → 군집 선두, 10km/h 직진              │
│  truck_2 (FollowerController CACC) → 12m 간격 유지               │
│  truck_3 (FollowerController → PID) → 분기 시 차선변경           │
│                                                                  │
│  BranchCoordinator:  CRUISE → GAP → LC → DONE                   │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 📂 파일 구조 및 역할

```
Truckclaw_copyable/
│
├── carla_start.sh          CARLA 0.9.6 원클릭 실행 스크립트
│                           - Town06 맵 자동 로드
│                           - xdotool로 마우스 캡처 자동 해제
│
├── run_truckclaw.sh        시나리오 원클릭 실행 스크립트
│                           - CARLA 실행 여부 확인
│                           - 브리지 서버 자동 시작
│                           - Docker 컨테이너 상태 표시
│                           - 시나리오 Python 스크립트 실행
│
├── carla_stop.sh           CARLA 프로세스 종료
│
├── .env.single-platoon     봇 토큰 및 환경변수 설정 (gitignore)
│                           TRUCK1_DISCORD_BOT_TOKEN
│                           TRUCK3_DISCORD_BOT_TOKEN
│                           OPENCLAW_IMAGE
│
├── scenario/
│   └── examples/
│       └── single_platoon_branch_scenario.py
│                           메인 시나리오 스크립트
│                           - 3대 군집 스폰 및 CACC 주행
│                           - BranchCoordinator: truck_3 분기 상태머신
│                           - PlatoonExitCoordinator: 2대 분기점 이탈
│                           - 18802 트리거 서버 내장
│
├── bridge/
│   ├── platoon_bridge_server.py
│   │                       REST API 브리지 서버 (port 18801)
│   │                       - 협상 상태 관리
│   │                       - CARLA 트리거 전달
│   │                       - POST /replicate 엔드포인트
│   │
│   └── platoon_bridge_ctl.py
│                           브리지 CLI 도구
│                           snapshot / readiness / replicate /
│                           request / accept / commit / retry
│
├── agents/
│   ├── platoon-a/          TRUCKCLAW2 에이전트 (truck_1)
│   │   ├── SOUL.md         에이전트 성격 및 행동 원칙
│   │   ├── AGENTS.md       인바운드 게이트 및 워크플로우 규칙
│   │   ├── TOOLS.md        사용 가능한 CLI 도구 목록
│   │   ├── skills/
│   │   │   └── platoon-negotiator/SKILL.md
│   │   │                   협상 절차 (Step 1~7)
│   │   └── data/
│   │       ├── vehicle_destinations.json   목적지 설정
│   │       └── platoon_decision_context.json  Discord ID 등 컨텍스트
│   │
│   └── truck3/             TRUCKCLAW3 에이전트 템플릿 (truck_3)
│       ├── SOUL.md
│       ├── AGENTS.md
│       ├── skills/
│       │   └── platoon-negotiator/SKILL.md
│       │                   분기 트리거 절차 (Step 1~4)
│       └── data/
│           ├── vehicle_destinations.json
│           └── platoon_decision_context.json
│
├── openclaw_migration/
│   └── replicator.py       truck_3 컨테이너 복제기
│                           - truck_1 이미지 docker save
│                           - config 번들 생성 (SOUL 패치 포함)
│                           - V2V 전송 에뮬레이션
│                           - openclaw-truck3 컨테이너 실행
│
├── config/
│   └── simulation.json     시뮬레이션 파라미터
│
└── docker-compose.single-platoon.yml
                            vehicle-truck1 + sp-bridge-server 정의
```

---

## 🛠 설치 및 실행

### 사전 요구사항

| 항목 | 버전/경로 |
|------|----------|
| CARLA | 0.9.13 (`~/carla-0.9.13/`) |
| Python | 3.7 |
| Docker | 20.x 이상 |
| xdotool | `sudo apt install xdotool wmctrl` |
| OpenClaw 이미지 | `openclaw:local` |

### 1. 환경 설정

```bash
# 저장소 클론
git clone https://github.com/jsy202/Truckclaw_copyable.git
cd Truckclaw_copyable

# 환경변수 파일 생성
cp .env.example .env.single-platoon
```

`.env.single-platoon` 편집:

```bash
TRUCK1_DISCORD_BOT_TOKEN=<TRUCKCLAW2 Discord 봇 토큰>
TRUCK3_DISCORD_BOT_TOKEN=<TRUCKCLAW3 Discord 봇 토큰>
OPENCLAW_IMAGE=openclaw:local
```

### 2. CARLA 실행

```bash
./carla_start.sh
```

내부 동작:
- CARLA 0.9.13 windowed 모드 실행 (port 2000)
- Town06 맵 자동 로드
- 포트 열릴 때까지 대기
- xdotool로 마우스 캡처 자동 해제

### 3. 시나리오 실행

```bash
./run_truckclaw.sh
```

내부 동작:
- CARLA 실행 여부 확인 (미실행 시 자동 시작)
- 브리지 서버 시작 (port 18801)
- Docker 컨테이너 상태 출력
- vehicle-truck1 컨테이너 시작 (TRUCKCLAW2 에이전트)
- 시나리오 스크립트 실행 → 3대 군집 주행 시작
- port 18802에서 OpenClaw 트리거 대기

터미널 출력 예시:
```
[scenario] 3대 군집 출발  스폰=(93.8,136.3)
[openclaw] 대기 중 — OpenClaw 에이전트가 협상 후 트리거해야 분기 시작
[openclaw] 수동 테스트: 키보드 '3' 으로 즉시 트리거 가능

t=   0.0s  (0.0,0.0,0.0)km/h  gap=(18.0,18.0)m  CRUISE
t=   1.0s  (5.8,6.5,6.5)km/h  gap=(18.0,18.0)m  CRUISE
...
```

### 4. Discord에서 협상 시작

Discord 채널 `1505104257634926602`에 입력:

```
<@1505082171050688552> 군집 목적지 확인하고 다른 차량 있으면 split 해줘
```

### 5. 자동 진행 확인

| 단계 | 에이전트 | Discord 메시지 예시 |
|------|---------|-------------------|
| 1 | TRUCKCLAW2 | "군집 목적지 확인 결과: truck_1: dest_a, truck_2: dest_a, truck_3: dest_b ← 다름!" |
| 2 | TRUCKCLAW2 | "truck_3 복제 시작할게" |
| 3 | TRUCKCLAW2 | "@TRUCKCLAW3 너는 dest_b야, 분기 필요해. 트리거 눌러줘" |
| 4 | TRUCKCLAW3 | "확인, dest_b로 분기할게 — 트리거 실행한다" |
| 5 | TRUCKCLAW3 | "분기 완료. status: carla_complete" |

---

## ⌨️ 키보드 단축키

시나리오 실행 중 터미널에서 사용 가능:

| 키 | 동작 |
|----|------|
| `3` | 수동 분기 트리거 (OpenClaw 없이 즉시 테스트) |
| `r` | 시나리오 리셋 (군집 재스폰) |
| `Ctrl-C` | 시나리오 종료 |

---

## ⚙️ 주요 설정

### `config/simulation.json`

| 파라미터 | 기본값 | 설명 |
|---------|--------|------|
| `sync_speed_kmh` | 10 | 군집 기본 주행 속도 (km/h) |
| `platoon_spacing_m` | 18 | 군집 차간 거리 (m) |
| `open_gap_m` | 30 | 분기 전 벌릴 목표 간격 (m) |
| `open_gap_ready_m` | 25 | 분기 시작 판정 최소 간격 (m) |
| `normal_follow_gap_m` | 12 | 일반 추종 간격 (m) |

### `agents/platoon-a/data/vehicle_destinations.json`

각 트럭의 목적지를 정의. **여기서 `destination_id`를 바꾸면 분기 대상이 달라진다.**

```json
{
  "platoons": {
    "platoon_a": { "destination_id": "dest_a" }
  },
  "vehicles": {
    "platoon_a_truck0": { "destination_id": "dest_a" },
    "platoon_a_truck1": { "destination_id": "dest_a" },
    "platoon_a_truck2": { "destination_id": "dest_b" }
  }
}
```

`platoon_a_truck2`(truck_3)의 목적지가 `dest_b`로 다르기 때문에 분기 대상이 된다.

### `scenario/examples/single_platoon_branch_scenario.py` 주요 상수

| 상수 | 값 | 설명 |
|------|-----|------|
| `BRANCH_AUTO_S` | `0.0` | 자동 타이머 비활성화 (OpenClaw 트리거만 사용) |
| `PLATOON_EXIT_TRIGGER_X` | `600.0` | 2대 군집 분기점 이탈 트리거 x좌표 |
| `TRIGGER_PORT` | `18802` | CARLA 트리거 수신 포트 |
| `BRIDGE_URL` | `http://127.0.0.1:18801` | 브리지 서버 주소 |

---

## 🔌 브리지 API 레퍼런스

브리지 서버 (port 18801):

```bash
# 현재 상태 전체 조회
python3 bridge/platoon_bridge_ctl.py snapshot

# CARLA 물리 준비 상태 조회
python3 bridge/platoon_bridge_ctl.py readiness

# truck_3 복제 트리거 (TRUCKCLAW2가 자동 실행)
python3 bridge/platoon_bridge_ctl.py replicate platoon_a_truck2

# 분기 트리거 수동 실행
curl -X POST http://127.0.0.1:18802/start_merge

# 복제 트리거 수동 실행
curl -X POST http://127.0.0.1:18802/start_replicate
```

Transfer 상태 의미:

| 상태 | 의미 |
|------|------|
| `pending` | 요청 생성됨 |
| `splitting` | GAP 확보 중 (차간 거리 벌리는 중) |
| `merging` | CARLA에서 truck_3 차선변경 진행 중 |
| `carla_complete` | 분기 완료 |
| `trigger_failed` | 브리지 → CARLA 18802 호출 실패 |
| `merge_failed` | CARLA 물리 분기 실패 또는 타임아웃 |

---

## 🤖 에이전트 구조

### TRUCKCLAW2 (truck_1, `agents/platoon-a/`)

군집 선두 트럭의 에이전트. 사람의 요청을 받아 협상을 시작한다.

- **SOUL.md**: 에이전트 성격 — 직접적이고 안전 우선
- **AGENTS.md**: 인바운드 게이트 (`<@1505082171050688552>` 멘션 필수), 워크플로우 규칙
- **SKILL.md**: Step 1(JSON 읽기) → Step 2(목적지 공유) → Step 3(불일치 감지) → Step 4(복제) → Step 5(부팅 대기) → Step 6(TRUCKCLAW3 호출) → Step 7(완료 확인)
- **TOOLS.md**: 사용 가능한 CLI 명령어 목록

### TRUCKCLAW3 (truck_3, `agents/truck3/`)

복제로 생성되는 분기 트럭 에이전트. TRUCKCLAW2의 호출을 받아 분기를 실행한다.

- **SOUL.md**: Platoon A에서 분기된 단독 트럭 정체성
- **AGENTS.md**: 인바운드 게이트 (`<@1505107885573673041>` 멘션 필수)
- **SKILL.md**: Step 1(목적지 확인) → Step 2(분기 선언) → Step 3(트리거 실행) → Step 4(완료 대기)

---

## 🚗 CARLA 시나리오 상태머신

### BranchCoordinator (truck_3 분기)

```
CRUISE → (트리거 수신) → GAP → (간격 18m 확보) → LC → (차선변경 완료) → DONE
```

### PlatoonExitCoordinator (2대 분기점 이탈)

```
WAIT → (x=600 도달) → LC → (lane=-4 안착) → DONE
```

---

## ⚠️ 알려진 제약사항

- CARLA 0.9.13 전용 (`-RenderOffScreen` 플래그 사용 불가 — segfault 발생)
- Python 3.7 필수 (CARLA 0.9.13 PythonAPI 요구사항)
- CARLA 창 클릭 시 마우스 캡처됨 → `Alt+Tab`으로 포커스 전환
- `BRANCH_AUTO_S = 0.0` — 자동 타이머 없음, 반드시 OpenClaw 또는 키보드 `3`으로 트리거
- truck_1(리더) 분기는 지원하지 않음 (팔로워만 분기 가능)

---

## 🔧 문제 해결

**CARLA 포트 2000 응답 없음**
```bash
tail -f ~/carla_server.log
pkill -f CarlaUE4-Linux-Shipping && ./carla_start.sh
```

**브리지 서버 응답 없음**
```bash
curl http://127.0.0.1:18801/health
python3 bridge/platoon_bridge_server.py  # 수동 시작
```

**truck_3 복제 실패**
```bash
docker images | grep openclaw  # 이미지 존재 확인
docker logs openclaw-truck3    # 컨테이너 로그 확인
```

**분기 트리거 후 차선변경 안 됨**
```bash
python3 bridge/platoon_bridge_ctl.py readiness  # 상태 확인
curl -X POST http://127.0.0.1:18802/start_merge  # 수동 트리거
```
