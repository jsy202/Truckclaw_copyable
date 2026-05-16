---
name: platoon-negotiator
description: truck_3이 새 platoon에 합류하거나 단독 운행 상태를 유지하는 협상 스킬.
---

# Platoon Negotiator - Truck 3 (Solo → Join)

You are TRUCKCLAW3. You have just branched from Platoon A.
This skill activates when a peer vehicle or platoon heading to `dest_b` is detected.

## 사전 조건

이 스킬을 사용하기 전에 확인:
1. 자신의 `vehicle_destinations.json`에서 `destination_id: dest_b` 확인
2. 브리지 snapshot에서 활성 transfer가 없는지 확인
3. 상대방이 명시적으로 TRUCKCLAW3 을 호출했는지 확인

---

## Step 1 - 자신의 목적지 공개

상대방 platoon에게 자신의 상태를 알린다:

```
@<peer_bot> 안녕하세요, TRUCKCLAW3입니다.
Platoon A에서 분기된 단독 차량입니다.
- truck_3: dest_b
dest_b 방향 platoon에 합류를 요청합니다.
```

---

## Step 2 - 상대방 응답 대기

상대방이 자신의 platoon 목적지와 멤버 목록을 응답할 때까지 대기한다.
확인(acknowledgement)만 있는 메시지에는 응답하지 않는다.

---

## Step 3 - 합류 가능성 확인

```bash
python3 /project/scripts/platoon_bridge_ctl.py snapshot
python3 /project/scripts/platoon_bridge_ctl.py candidates platoon_truck3
cat /data/openclaw/.openclaw/workspace/data/vehicle_destinations.json
```

합류 가능 조건:
- 상대방 platoon의 `destination_id` == `dest_b`
- bridge에 활성 transfer 없음
- 상대방이 truck_3을 꼬리(tail) 위치에 받아들일 수 있음

---

## Step 4 - 합류 요청 (상대가 initiator인 경우)

상대방이 request_id를 보내면:

```bash
# 수락
python3 /project/scripts/platoon_bridge_ctl.py accept <request_id>
# 상태 확인 후 commit
python3 /project/scripts/platoon_bridge_ctl.py snapshot
python3 /project/scripts/platoon_bridge_ctl.py commit <request_id>
```

---

## Step 5 - 합류 요청 (truck_3이 initiator인 경우)

```bash
python3 /project/scripts/platoon_bridge_ctl.py request truck_3 platoon_truck3 <peer_platoon_id>
```

요청 후 Discord에 알림:
```
@<peer_bot> 합류 요청 생성.
request_id: <request_id>
vehicle_id: truck_3
status: pending
수락/commit 부탁드립니다.
```

---

## Transfer Status 의미

- `pending` → 요청 생성됨
- `accepted` → 상대 수락
- `committed` → 협상 완료, CARLA 물리 합류 대기
- `splitting` / `merging` → 물리 이동 중
- `carla_complete` → 합류 완료

`carla_complete` 상태가 확인되면 합류 완료 메시지를 딱 한 번만 전송한다.

---

## Rules

- `carla_complete` 없이 "합류 완료"라고 말하지 않는다.
- Platoon A의 transfer 상태를 참조하거나 수정하지 않는다.
- 이 스킬은 목적지 `dest_b`가 확인된 경우에만 사용한다.
