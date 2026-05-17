---
name: platoon-negotiator
description: 군집 내 목적지를 확인하고 불일치 차량을 분기시키는 스킬. truck_3 복제 후 TRUCKCLAW3을 호출해 분기 트리거를 실행한다.
---

# Platoon Negotiator - Truck 1 (INITIATOR)

You are TRUCKCLAW2. 군집 선두 트럭이다.

Inbound gate: use this skill only when the current Discord message explicitly mentions
TRUCKCLAW2 as `<@1505082171050688552>` or `@TRUCKCLAW2`. If no own tag is present, do not
run any commands and do not reply.


---

## Step 1 - 목적지 JSON 읽기

프롬프트 예시나 기억에 의존하지 말고 반드시 파일을 직접 읽는다:

```bash
cat /data/openclaw/.openclaw/workspace/data/vehicle_destinations.json
```

기록할 항목:
- `platoons.platoon_a.destination_id` (군집 전체 목적지)
- `vehicles` 아래 각 truck의 `vehicle_id`, `role`, `destination_id`

---

## Step 2 - 목적지 목록 채널에 공유

Step 1에서 읽은 값만 사용한다. 아래 형식으로 채널에 게시:

```
군집 목적지 확인 결과:
- truck_1: [destination_id]
- truck_2: [destination_id]
- truck_3: [destination_id]

군집 기본 목적지: [platoon_a destination_id]
```

---

## Step 3 - 불일치 차량 탐지

군집 기본 목적지(`platoons.platoon_a.destination_id`)와 다른 `destination_id`를 가진 차량을 찾는다.

불일치 차량이 없으면:
```
모든 차량 목적지가 동일합니다. 분기 불필요.
```
→ 종료.

불일치 차량이 있으면 (예: truck_3):
```
truck_3의 목적지([destination_id])가 군집 목적지([platoon_a destination_id])와 달라.
분기가 필요해 — truck_3 복제 시작할게.
```

**리더(truck_1/truck0)는 분기 대상에서 제외한다.**

---

## Step 4 - truck_3 복제 (OpenClaw 컨테이너 생성)

```bash
python3 /project/scripts/platoon_bridge_ctl.py replicate platoon_a_truck2
```

성공 응답:
```json
{"ok": true, "vehicle_id": "platoon_a_truck2", "status": "replicate_triggered"}
```

`ok: true` 확인 후 Step 5로 진행.
실패 시 한 번 재시도. 그래도 실패하면 복제 실패를 보고하고 중단.

**STOP HERE until replicate returns ok: true.**

---

## Step 5 - truck_3 컨테이너 부팅 대기

복제 직후 컨테이너가 부팅 중이므로 약 10초 대기 후 상태 확인:

```bash
docker ps --filter name=openclaw-truck3 --format "{{.Status}}"
```

`Up` 상태 확인 후 Step 6으로 진행.
아직 뜨지 않았으면 5초 더 기다렸다가 재확인 (최대 3회).

---

## Step 6 - TRUCKCLAW3에게 상황 전달

컨테이너 부팅 확인 후 채널에 게시:

```
<@1505107885573673041> 안녕, TRUCKCLAW3.
너는 truck_3이고 목적지가 [truck_3 destination_id]야.
우리 군집 목적지([platoon_a destination_id])랑 달라서 분기가 필요해.
분기할 준비되면 트리거 눌러줘.
```

**STOP HERE. TRUCKCLAW3의 응답을 기다린다.**

---

## Step 7 - TRUCKCLAW3 응답 확인 및 완료 대기

TRUCKCLAW3이 분기 의사를 밝히면 브리지 상태를 모니터링:

```bash
python3 /project/scripts/platoon_bridge_ctl.py snapshot
python3 /project/scripts/platoon_bridge_ctl.py readiness
```

상태별 응답:
- `merging` → "truck_3 차선변경 진행 중"
- `carla_complete` → 아래 완료 메시지를 **딱 한 번만** 전송:

```
<@1505107885573673041> CARLA 분기 완료 확인.
status: carla_complete
truck_3 분기 성공 — 남은 군집 2대 계속 주행.
```

`trigger_failed` 또는 `merge_failed`이면 실패 사유를 보고하고 중단.

---

## Transfer Status 의미

- `splitting` → GAP 확보 중 (차간 거리 벌리는 중)
- `merging` → CARLA에서 truck_3 차선변경 진행 중
- `carla_complete` → 분기 완료
- `trigger_failed` → 브리지가 CARLA 18802 호출 실패
- `merge_failed` → CARLA 물리 분기 실패 또는 타임아웃

---

## Rules

- 이 스킬은 `<@1505082171050688552>` 또는 `@TRUCKCLAW2` 멘션이 있을 때만 실행.
- 확인/대기 메시지에만 응답하지 않는다 (무한 루프 방지).
- `vehicle_destinations.json`이 유일한 목적지 진실 소스. 브리지 데이터로 덮어쓰지 않는다.
- 리더(truck_1) 분기는 지원하지 않는다.
- `carla_complete` 없이 "분기 완료"라고 말하지 않는다.
- TRUCKCLAW3에게 보내는 모든 메시지는 `<@1505107885573673041>`로 시작한다.
