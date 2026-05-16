# Tools - Truck 3

Run bridge commands from inside the OpenClaw container (`openclaw-truck3`).
Destination source of truth: `/data/openclaw/.openclaw/workspace/data/vehicle_destinations.json`

```bash
# 브리지 상태 확인
python3 /project/scripts/platoon_bridge_ctl.py snapshot
python3 /project/scripts/platoon_bridge_ctl.py readiness

# 목적지 및 맥락 확인
cat /data/openclaw/.openclaw/workspace/data/vehicle_destinations.json
cat /data/openclaw/.openclaw/workspace/data/platoon_decision_context.json

# 이송 후보 확인 (platoon_truck3 기준)
python3 /project/scripts/platoon_bridge_ctl.py candidates platoon_truck3

# 이송 요청 (대상 platoon이 있을 경우)
python3 /project/scripts/platoon_bridge_ctl.py request truck_3 platoon_truck3 <target_platoon_id>

# 특정 이송 상태 확인
python3 /project/scripts/platoon_bridge_ctl.py transfer <request_id>
```

## Notes

- truck_3은 단독 차량이므로 협상 상대가 있을 때만 transfer 요청을 생성한다.
- bridge URL: `http://127.0.0.1:18801` (브리지 서버가 호스트에서 실행 중)
- truck_1 (openclaw-truck1)의 bridge 트랜잭션을 수정하거나 참조하지 않는다.
