# Traceability Matrix — Truckclaw_copyable

| REQ | Production code (validation 브랜치) | Test | Baseline | Current | Commit |
|---|---|---|---|---|---|
| SR-001 | `openclaw_migration/replicator.py` `create_config_bundle` L128, `_load_and_run` L265 | TC-01, TC-19–21 | PASS | PASS | – |
| SR-002 | `_patch_soul` L76 | TC-02, TC-19 | PASS | PASS | – |
| SR-003 | `wait` L199, `finished` L203 | TC-04, TC-05 | PASS, FAIL | PASS, PASS | `84e0d1a` |
| SR-004 | `scenario/examples/single_platoon_branch_scenario.py` MIGRATE 분기 L296, `_abort_branch` L320 | TC-11, TC-12 | PASS, FAIL | PASS, PASS | `84e0d1a` |
| SR-005 | `MIGRATE_TIMEOUT_S` L62, L298 | TC-13 | FAIL | PASS | `14a340b` |
| SR-006 | `replicate` L183–186 (`_running` guard) | TC-10 | FAIL | PASS | `7645f7a` |
| SR-007 | `create_config_bundle` L146 (missing identity → RuntimeError) | TC-07, TC-08 | FAIL, FAIL | PASS, PASS | `e90256d` + `d0e2d31` (문법 오류 수정) |
| SR-008 | 시나리오 L574 `branch_agent_dir=agents/truck3` | TC-09 | FAIL | PASS | `364a645` |
| SR-009 | `replicate` L194 (blocking 시 `_success` 반환), `main` | TC-06 | FAIL | PASS | `accfabc` |
| SR-010 | `bridge/platoon_bridge_server.py` `POST /branch` L264–269, `GET /branch` L233 | TC-15–17 | FAIL | PASS | `75922b7` |
| SR-011 | `/replicate` L275 (`_find_vehicle` L84) | TC-14, TC-18 | PASS, FAIL | PASS, PASS | `b2695bb` |
| SR-012 | `_v2v_transfer` L92 | TC-03 | PASS | PASS | – |
| SR-P01–P04 | – | – | – | 미구현 | – |
| REQ-TR-* (상속) | bridge `/transfers*` | improve 결함 스위트 | 11/11 재현 | 미수정 | – |
