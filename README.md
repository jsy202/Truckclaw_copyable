# Truckclaw — 군집 분기 시나리오 + OpenClaw 에이전트 복제

CARLA 시뮬레이터에서 3대 트럭이 단일 군집으로 주행하다가, 한 대의 목적지가 달라지면 그 차량이 분기되고 자신만의 AI 에이전트(OpenClaw)를 복제해서 단독 운행하는 시스템이다.

---

## 아키텍처

```
Host
├── Vehicle Docker (truck_1)  →  OpenClaw Docker (openclaw-truck1)  ← 항상 실행
├── Vehicle Docker (truck_2)  →  OpenClaw 없음
└── Vehicle Docker (truck_3)  →  OpenClaw Docker (openclaw-truck3)  ← 분기 시 자동 생성
```

MVP에서는 Vehicle Docker를 호스트 디렉터리로 에뮬레이션하고, 호스트에서 `docker run`을 직접 실행해 DinD를 대체한다.

```
브리지 서버 (포트 18801)  ↔  CARLA 시나리오 (포트 18802)  ↔  CARLA Town06 (포트 2000)
```

---

## 차량 구성

| 차량 | 역할 | OpenClaw |
|------|------|----------|
| truck_1 | 리더 | openclaw-truck1 (항상 실행, 분기 후에도 유지) |
| truck_2 | 팔로워 | 없음 (순수 CACC 추종) |
| truck_3 | 팔로워 → 분기 후 단독 리더 | openclaw-truck3 (분기 시 생성) |

---

## 분기 흐름

```
CRUISE        정상 군집 주행 중
  ↓           목적지 불일치 감지 (자동 30초 or 키 '3')
GAP_OPEN      truck_3의 follow gap을 20m로 설정 → 18m 이상 벌어질 때까지 대기
  ↓
DETACH        Platoon.split(2, 2) 호출 → truck_3 분리, autopilot으로 단독 주행
  ↓
SPAWN_OC      replicator.py 실행 → OpenClaw 파일 복제 + docker run openclaw-truck3
  ↓
DONE          truck_1+2: 2대 군집 계속 / truck_3: 단독 주행 + 자체 에이전트 실행
```

---

## OpenClaw 에이전트 복제 — 실제 파일 내용과 변경 근거

분기 시점에 `openclaw_migration/replicator.py`가 실행되며, 파일마다 다른 처리를 한다.

---

### SOUL.md — truck_1 원본을 복사한 뒤 일부만 수정

**SOUL.md는 에이전트의 판단 기준과 행동 원칙을 담는 파일이다.**
대부분의 내용은 truck_3에서도 동일하게 적용되어야 하므로 복사하되, 정체성 참조 부분만 교체한다.

#### 원본 (truck_1 / agents/platoon-a/SOUL.md)

```
You are TRUCKCLAW2, the operational leader for Platoon A (`platoon_a`).

Only respond when the current Discord message explicitly mentions TRUCKCLAW2 as
`<@1479297673432399923>` or `@TRUCKCLAW2`.

Every peer-facing message must mention TRUCKCLAW1 with `<@1479297098938585170>`.

## Role: Initiator
confirm the candidate is still in `platoon_a`, matches Platoon B's destination
```

#### 복제 후 (truck_3 / .openclaw-truck3/SOUL.md)

```
You are TRUCKCLAW3, the operational leader for Truck 3 (solo vehicle, `platoon_truck3`).

Only respond when the current Discord message explicitly mentions TRUCKCLAW3 as
`<@TRUCK3_DISCORD_ID>` or `@TRUCKCLAW3`.

Every peer-facing message must mention TRUCKCLAW_PEER with `<@PEER_DISCORD_ID>`.

## Role: Solo Navigator (분기 직후 단독 운행)
confirm the candidate is still in `platoon_truck3`, matches Platoon B's destination

## Branched Vehicle Note
You have just branched from Platoon A. Your destination is `dest_b`.
```

#### 무엇이 바뀌었고, 왜 그렇게 바꿨는가

| 항목 | truck_1 원본 | truck_3 복제본 | 바꾼 이유 |
|------|-------------|---------------|-----------|
| 봇 이름 | `TRUCKCLAW2` | `TRUCKCLAW3` | Discord에서 자기 이름으로 호출될 때만 응답해야 하므로 |
| Discord mention ID | `<@1479297673432399923>` | `<@TRUCK3_DISCORD_ID>` | Discord ID는 봇 계정마다 고유하다. truck_1의 ID로 응답하면 truck_3이 truck_1 행세를 하게 됨 |
| 소속 platoon | `platoon_a` | `platoon_truck3` | 분기 후 truck_3은 platoon_a 소속이 아님. 잘못된 소속으로 협상하면 bridge 상태와 불일치 발생 |
| 상대방 봇 참조 | `TRUCKCLAW1` | `TRUCKCLAW_PEER` | truck_3의 상대방은 아직 정해지지 않았다. 고정 ID를 넣으면 엉뚱한 봇에게만 말을 걸게 됨 |
| 역할 | `Initiator` | `Solo Navigator` | truck_3은 두 군집 간 협상 개시자가 아니라 단독 운행 중인 차량 |

#### 바꾸지 않은 부분과 이유

```
"bridge snapshot만 진실로 삼아라"               → truck_3에도 동일하게 적용되는 안전 원칙
"carla_complete 없이 합류 완료 선언 금지"        → 상태 기반 판단 원칙, 동일 적용
"확인만 있는 메시지에는 응답하지 마라"            → 무한 응답 루프 방지 규칙, 동일 적용
"vehicle_destinations.json만 목적지 기준으로"    → 데이터 신뢰 원칙, 동일 적용
```

이 규칙들은 어떤 차량 에이전트에도 공통으로 필요한 안전 원칙이므로 그대로 복사한다.

---

### AGENTS.md — 재생성 (복사 안 함)

**AGENTS.md는 이 에이전트가 누구이고, 어떤 상황에 있으며, 무엇을 해야 하는지를 담는 파일이다.**

#### truck_1 원본 (agents/platoon-a/AGENTS.md)

```
- Bot display name: TRUCKCLAW2
- Platoon id: `platoon_a`
- Own mention: `<@1479297673432399923>`
- Peer bot: TRUCKCLAW1
- Peer mention: `<@1479297098938585170>`
- Role in negotiation: initiator

## Required Workflow
1. Read vehicle_destinations.json
2. Post Platoon A's destination list
3. Wait for TRUCKCLAW1 to post Platoon B's list
4. Run bridge checks before requesting transfer
5. Request exactly one eligible follower transfer
6. Wait for TRUCKCLAW1 to accept and commit
```

#### truck_3 재생성본 (agents/truck3/AGENTS.md)

```
- Bot display name: TRUCKCLAW3
- Vehicle id: `truck_3`
- Container name: `openclaw-truck3`
- Current platoon: `platoon_truck3` (solo)
- Branched from: `platoon_a` (was `platoon_a_truck2`)
- Reason for branch: destination mismatch (`dest_b` ≠ `dest_a`)

## Current Mission
Navigate to `dest_b`.
If a platoon heading to `dest_b` is found, negotiate to join as tail follower.

## Constraints
- Do not reference Platoon A's active transfers.
- Do not use truck_1's Discord mention IDs.
```

#### 왜 복사하지 않고 재생성했는가

truck_1의 AGENTS.md에는 두 군집 간 6단계 협상 워크플로우가 들어 있다.
truck_3이 이 파일을 그대로 받으면 아래 문제가 생긴다.

- `TRUCKCLAW1`에게 먼저 말을 걸도록 되어 있다 → truck_3의 상황과 전혀 무관
- Platoon A 팔로워 이송 조건을 따르도록 되어 있다 → truck_3은 이미 분기된 단독 차량
- `<@1479297098938585170>` (TRUCKCLAW1 ID)로 모든 메시지를 시작하도록 되어 있다 → truck_3이 엉뚱한 봇에게 메시지를 보내게 됨

truck_3의 상황은 truck_1과 구조적으로 다르기 때문에 전체를 새로 작성한다.

---

### vehicle_destinations.json — 재생성 (복사 안 함)

**이 파일은 에이전트가 "어디로 가야 하는가, 나는 어느 소속인가"를 결정하는 유일한 기준이다.**

#### truck_1 원본 — 2개 군집 6대 차량 전체 포함

```json
{
  "platoons": {
    "platoon_a": { "destination_id": "dest_a", "ordered_members": ["platoon_a_truck0", "platoon_a_truck1", "platoon_a_truck2"] },
    "platoon_b": { "destination_id": "dest_b", "ordered_members": ["platoon_b_truck0", "platoon_b_truck1", "platoon_b_truck2"] }
  },
  "vehicles": {
    "platoon_a_truck0": { "platoon_id": "platoon_a", "role": "leader",   "destination_id": "dest_a" },
    "platoon_a_truck1": { "platoon_id": "platoon_a", "role": "follower", "destination_id": "dest_b" },
    "platoon_a_truck2": { "platoon_id": "platoon_a", "role": "follower", "destination_id": "dest_a" },
    "platoon_b_truck0": { "platoon_id": "platoon_b", "role": "leader",   "destination_id": "dest_b" },
    "platoon_b_truck1": { "platoon_id": "platoon_b", "role": "follower", "destination_id": "dest_b" },
    "platoon_b_truck2": { "platoon_id": "platoon_b", "role": "follower", "destination_id": "dest_b" }
  }
}
```

#### truck_3 재생성본 — truck_3 단독

```json
{
  "platoons": {
    "platoon_truck3": { "destination_id": "dest_b", "ordered_members": ["truck_3"] }
  },
  "vehicles": {
    "truck_3": {
      "platoon_id": "platoon_truck3",
      "role": "leader",
      "destination_id": "dest_b",
      "branched_from": "platoon_a",
      "original_vehicle_id": "platoon_a_truck2"
    }
  }
}
```

#### 왜 복사하지 않고 재생성했는가

truck_1의 파일을 그대로 복사하면:

- truck_3은 자신이 아직 `platoon_a` 소속(`platoon_a_truck2`)인 줄 안다
- `platoon_b`와 협상을 시작하려 한다 (truck_1이 하는 것처럼)
- `dest_a`로 가야 하는 차량들을 이송 후보로 판단한다
- 이미 분리됐는데도 bridge에 platoon_a 이송 요청을 만들 수 있다

truck_3에게 필요한 정보는 두 가지다: **"나는 dest_b로 간다"**, **"나는 platoon_truck3 소속이다"**
나머지 6대 차량 정보는 truck_3과 관계없으므로 포함하지 않는다.

---

### 복사 금지 항목과 이유

| 항목 | 금지 이유 |
|------|-----------|
| Discord 봇 토큰 | truck_1의 토큰으로 truck_3이 Discord에 로그인하면 같은 계정으로 두 봇이 동시 접속된다. 메시지가 뒤섞이고 Discord 정책 위반 |
| OpenClaw 게이트웨이 토큰 | 토큰은 봇 계정과 1:1 대응. 공유 불가 |
| 브리지 활성 transfer 상태 | truck_1이 진행 중인 `pending` 협상이 복사되면 truck_3이 자신과 무관한 협상의 후속 처리를 수행할 수 있다 |

---

## 프로젝트 구조

```
Truckclaw_copyable/
├── scenario/examples/
│   ├── two_platoon_truck_scenario.py      # 기존 양방향 이송 (수정 안 함)
│   └── single_platoon_branch_scenario.py  # 신규: 단일 군집 분기
├── openclaw_migration/
│   └── replicator.py   # bundle → restore → docker run 파이프라인
├── agents/
│   ├── platoon-a/      # truck_1 OpenClaw 설정 (행동 DNA 소스)
│   └── truck3/         # truck_3 전용 템플릿 (정체성 파일)
├── bridge/
│   ├── platoon_bridge_server.py
│   └── platoon_bridge_ctl.py
├── config/simulation.json
├── docker-compose.yml
└── docker-compose.single-platoon.yml
```

---

## 실행

```bash
cp -r agents/platoon-a/ .openclaw-truck1/
cp .env.example .env.single-platoon   # 토큰 입력

python3 bridge/platoon_bridge_server.py
docker compose -f docker-compose.single-platoon.yml up openclaw-truck1

export PYTHONPATH=$PYTHONPATH:/opt/carla-0.9.6/PythonAPI/carla
python3 scenario/examples/single_platoon_branch_scenario.py
# 30초 후 자동 분기, 또는 '3' 키로 수동 트리거

# CARLA 없이 복제 로직만 테스트
python3 openclaw_migration/replicator.py --dry-run
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
| 18802 | CARLA 트리거 수신 |
| 18791 | openclaw-truck1 gateway |
| 18792 | openclaw-truck3 gateway (분기 후 생성) |
