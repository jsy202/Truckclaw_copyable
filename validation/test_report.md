# Test Report — Truckclaw_copyable (Post-project Validation)

> 연구 종료 후 수행한 검증이다. 연구 당시의 CARLA 분기와 실제 Docker 복제 시연은 재실행하지 않았다.

## 환경

Linux 6.8, Python 3.10.12, pytest 8.4.2. CARLA, Docker, Discord는 사용하지 않았다. baseline은 `research-baseline` = `24cee6b`(GitHub main 최신)이다.

## 결과 (최종, `2e2bf63`)

| 전체 | PASS | XFAIL | FAILED |
|---|---|---|---|
| 21 | 21 | 0 | 0 |

10회 연속 실행에서 매회 `21 passed`(약 3.04 s)였다(`evidence/repeat_runs.txt`).

## 결함 이력

| 단계 | commit | pytest |
|---|---|---|
| 하네스 + 결함 9건 strict xfail (production 변경 0) | `4e68113` | 6 passed, 9 xfailed |
| C01 + C06: `wait()`=성공, 실패 시 분기 중단 | `84e0d1a` | 8 passed, 7 xfailed |
| C07: MIGRATE timeout | `14a340b` | 9 passed, 6 xfailed |
| C05: 중복 `replicate()` 무시 | `7645f7a` | 10 passed, 5 xfailed |
| C02: CLI 종료 코드 | `accfabc` | 11 passed, 4 xfailed |
| C04: 시나리오 템플릿 경로 | `364a645` | 12 passed, 3 xfailed |
| C03: 정체성 파일 누락 시 실패 | `e90256d` | **2 passed, 2 xfailed, 12 errors** — SyntaxError가 들어간 상태로 commit됨 |
| 위 SyntaxError 수정 | `d0e2d31` | 14 passed, 2 xfailed |
| C08: `/branch` endpoint | `75922b7` | 17 passed, 1 xfailed |
| C09: `/replicate` 차량 검증 | `b2695bb` | 18 passed |
| unit 3건 + CI | `2e2bf63` | 21 passed |

**작업 중 실수 기록:** `e90256d`는 교체 범위 밖에 남은 `else:` 때문에 SyntaxError를 포함한 채 commit되었다. 테스트 결과를 확인하기 전에 commit을 실행했기 때문이다. history는 고치지 않았고, 다음 commit `d0e2d31`에서 수정했다. 이후 commit은 compile 오류나 failed/error가 있으면 commit을 거부하는 스크립트를 거쳤다.

## 테스트 도구 자체의 결함 (발견 후 수정)

- FakeDocker가 `subprocess.run(check=True)`의 예외 동작을 흉내 내지 않았다.
- 그래서 처음 실행에서 "docker run 실패인데 성공"이라는 잘못된 결과가 나왔다(TC-04).
- production 결함이 아니라 Fake의 충실도 문제였으므로, Fake를 고친 뒤 결함 목록에서 뺐다. movable의 FakeDocker에도 같은 수정을 반영했다(movable `482cef6`).

## Baseline 교차 검증

현재 테스트 21건을 baseline 소스에서 실행한 결과: **12 failed, 9 passed**. 실패한 12건은 위 결함 9건과 관련 보강 테스트 3건(TC-08, 16, 17)이다.

## 상속 결함

improve의 transfer 결함 스위트로 확인한 결과 11/11이 재현되었다(`evidence/inherited_transfer_defects.txt`). 이 저장소에서는 수정하지 않았다.

## CI

workflow는 아직 GitHub에서 실행되지 않았다. 같은 명령을 로컬에서 실행한 결과: 문법 OK, unit 3 passed, integration 18 passed.
