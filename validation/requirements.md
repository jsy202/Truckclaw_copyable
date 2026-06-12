# Requirements — Truckclaw_copyable (Split / Agent Replication)

> 연구 종료 후 수행한 Post-project Validation 산출물이다.
>
> - 출처: Existing = README/코드에 명시됨, Derived = 기존 설계에서 도출됨, Proposed = 이번에 새로 제안함
> - 증거 등급: A = 실행, B = 정적 분석, C = 제안

| ID | 요구사항 | 출처 | 검증 |
|---|---|---|---|
| REQ-SR-001 | 분기 agent는 truck1(platoon-a)의 행동 파일(SOUL 패치, TOOLS, SKILL)과 truck3 템플릿의 정체성 파일(AGENTS.md, vehicle_destinations, decision_context)로 구성된다. | Existing (README "복제된 truck_3이 아는 것", replicator) | A |
| REQ-SR-002 | 복제된 SOUL에는 원본 platoon A의 Discord ID와 봇 이름이 남지 않는다. | Existing (`_patch_soul`) | A |
| REQ-SR-003 | `BranchReplicator.wait()`는 복제가 **성공**한 경우에만 True를 반환한다. | Derived (coordinator가 "agent 준비 완료"로 사용) | A |
| REQ-SR-004 | 복제가 실패하면 물리 분기(GAP 이후)를 시작하지 않는다. 분기를 중단하고 bridge에 보고하며, truck2는 군집에 유지된다. | Derived | A |
| REQ-SR-005 | 복제가 `MIGRATE_TIMEOUT_S`(120 s, `wait()` 기본값) 안에 끝나지 않으면 분기를 중단한다. | Derived | A |
| REQ-SR-006 | 하나의 분기에는 한 번의 복제만 수행한다. 진행 중에 들어온 중복 요청은 무시한다. | Derived (`/start_replicate`와 분기 trigger가 둘 다 복제를 시작할 수 있음) | A |
| REQ-SR-007 | 정체성 파일이 하나라도 없으면 복제는 실패로 처리하고 컨테이너를 기동하지 않는다. | Derived | A |
| REQ-SR-008 | 시나리오가 사용하는 정체성 템플릿 경로는 저장소에 존재해야 한다. | Derived | A (정적 계약 테스트, AST) |
| REQ-SR-009 | 단독 실행 CLI의 종료 코드는 복제 실패를 반영한다. | Derived | A |
| REQ-SR-010 | bridge는 시나리오가 보고하는 분기 진행(`/branch` started/complete/failed)을 기록한다. | Derived (시나리오가 이미 이 계약으로 호출) | A |
| REQ-SR-011 | `/replicate`는 존재하는 차량에 대해서만 CARLA를 trigger한다. | Derived | A |
| REQ-SR-012 | V2V 전송(청크 복사 에뮬레이션)은 원본과 바이트 단위로 동일하다. | Derived | A |

## Proposed / DEFERRED

| ID | 내용 | 상태 |
|---|---|---|
| REQ-SR-P01 | 신규 agent gateway health를 확인한 뒤에야 "복제 성공"으로 판정 | C — 미구현(movable의 DEF-M09와 같은 공백) |
| REQ-SR-P02 | 분기 `complete` 시 bridge의 논리 멤버십에서 truck2 분리 | C — 새 기능이라 이번에 구현하지 않음 |
| REQ-SR-P03 | MIGRATE timeout 뒤 복제 스레드 취소 | C |
| REQ-SR-P04 | 이미지 로드 실패를 "이미 존재"로 간주하는 처리(`_load_and_run`) 재검토 | C — 원본 설계 유지(B) |
| REQ-TR-* | improve의 transfer 결함 11건 | 재현됨(A), 미수정 |
