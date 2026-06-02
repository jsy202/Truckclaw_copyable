# Test Cases — Truckclaw_copyable

CARLA, Docker, Discord 없이 실행된다. "Baseline" 열은 현재 테스트를 research-baseline(`24cee6b`) 소스에서 `--runxfail`로 실행한 결과다(`evidence/baseline_crosscheck.txt`).

| TC | DEF | 테스트 | 기대 | REQ | Baseline | Current |
|---|---|---|---|---|---|---|
| TC-01 | – | `test_replication_with_shipped_template_starts_branch_agent` | docker 호출 순서 save→load→rm→run, openclaw-truck3, SOUL 패치, 정체성 파일 존재 | SR-001 | PASS | PASS |
| TC-02 | – | `test_config_bundle_patches_identity_in_soul` | 원본 Discord ID와 TRUCKCLAW2가 없어야 함 | SR-002 | PASS | PASS |
| TC-03 | – | `test_v2v_transfer_is_byte_identical` | sha256 일치 | SR-012 | PASS | PASS |
| TC-04 | – | `test_docker_run_failure_marks_replication_failed` | `_success` False | SR-003 | PASS | PASS |
| TC-05 | C01 | `test_wait_reports_failure_after_failed_replication` | 실패 후 `wait(0)` False | SR-003 | FAIL | PASS |
| TC-06 | C02 | `test_cli_exit_code_reflects_replication_failure` | `main()` == 1 | SR-009 | FAIL | PASS |
| TC-07 | C03 | `test_replication_fails_when_identity_template_missing` | 템플릿 없음 → 실패, docker run 없음 | SR-007 | FAIL | PASS |
| TC-08 | – | `test_replication_fails_when_one_identity_file_is_missing` | 파일 1개 누락 → 실패 | SR-007 | FAIL | PASS |
| TC-09 | C04 | `test_scenario_branch_agent_dir_exists_in_repo` | 시나리오의 `branch_agent_dir`(AST로 추출)가 존재하고 AGENTS.md 포함 | SR-008 | FAIL (`agents/truck2` 없음) | PASS |
| TC-10 | C05 | `test_concurrent_replicate_calls_run_once` | 진행 중 재호출 → docker save 1회 | SR-006 | FAIL (2회) | PASS |
| TC-11 | – | `test_coordinator_advances_to_gap_after_successful_replication` | MIGRATE→GAP, `/branch started` | SR-004 | PASS | PASS |
| TC-12 | C06 | `test_split_does_not_proceed_when_replication_fails` | docker run 실패 → CRUISE + `/branch failed` | SR-004 | FAIL (GAP 진행) | PASS |
| TC-13 | C07 | `test_coordinator_times_out_hung_replication` | save가 3 s 동안 멈춤, timeout 0.3 s → CRUISE + failed | SR-005 | FAIL (MIGRATE 고착) | PASS |
| TC-14 | – | `test_replicate_triggers_carla_with_vehicle_id` | trigger 1회, vehicle_id 전달 | SR-011 | PASS | PASS |
| TC-15 | C08 | `test_bridge_accepts_branch_progress_reports` | started/complete 200, snapshot.branch | SR-010 | FAIL (404) | PASS |
| TC-16 | – | `test_branch_report_rejects_unknown_status` | 400 | SR-010 | FAIL (404) | PASS |
| TC-17 | – | `test_branch_failed_report_is_recorded` | GET /branch → failed | SR-010 | FAIL (404) | PASS |
| TC-18 | C09 | `test_replicate_rejects_unknown_vehicle` | 404, trigger 0회 | SR-011 | FAIL (200) | PASS |
| TC-19–21 | – | `tests/unit/test_identity_patch.py` (3건) | `_patch_soul` 치환, 파일 집합 | SR-001, 002 | PASS | PASS |

## 미실행 (CARLA·Docker 필요)

- 실제 CARLA에서 truck2 차선 변경과 단독 주행
- 실제 docker save(약 976 MB 이미지)와 load
- openclaw-truck3의 Discord 접속
