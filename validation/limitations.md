# Limitations — Truckclaw_copyable Validation

| 항목 | 상태 |
|---|---|
| CARLA 물리 분기(GAP→LC→SIDE_BY_SIDE→DONE) | 미검증. CARLA stub으로 MIGRATE 경계까지만 테스트했다 |
| 실제 docker save/load/run, DinD | 미검증 (FakeDocker) |
| openclaw-truck3의 실제 Discord 동작, 정체성 반영 | 미검증. 파일 구성까지만 확인했다 |
| 신규 agent readiness | 미구현. `docker run -d`가 성공하면 복제 성공으로 판정한다 |
| MIGRATE timeout 뒤의 복제 스레드 | 취소되지 않아 늦게 성공하면 컨테이너가 기동될 수 있다 |
| `/branch` complete 후 bridge 멤버십 | 바꾸지 않는다(기록만 함). 새 기능이라 구현하지 않았다 |
| `docker load` 실패 처리 | "이미 존재"로 간주하고 계속 진행한다(원본 설계 유지) |
| 상속 transfer 결함 11건 | 재현됨, 미수정 |
| README 포트 표기 | README는 18792, 코드는 18793 (B, 수정하지 않음) |
| 차량 명명 | README는 1부터, 코드는 0부터 번호를 매긴다. 분기 차량 truck_3 = 코드의 truck2 (B) |

## 동작 변화 (실제 시연에서 확인 필요)

| 변화 | 연구 당시 | 현재 |
|---|---|---|
| 정체성 템플릿 | `agents/truck2`(없음) → 정체성 파일 없이 복제 | `agents/truck3` → AGENTS.md, destinations, decision_context 포함 |
| 복제 실패 | 그래도 물리 분기 진행 | 분기 중단, truck2 군집 유지, `/branch failed` |
| `/start_replicate` 후 분기 trigger | 복제 2회 동시 실행 가능 | 1회 |
