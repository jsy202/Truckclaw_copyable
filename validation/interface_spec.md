# Interface Specification — Truckclaw_copyable

transfer 엔드포인트는 improve와 같다(baseline, 미수정). **[changed]** 표시는 research-baseline(`24cee6b`)과 달라진 부분이다.

## Bridge (:18801)

| Endpoint | 요청 | 응답 |
|---|---|---|
| `POST /replicate` | `{"vehicle_id": "platoon_a_truck2"}` (생략 시 같은 값) | 200 `{ok, vehicle_id, status: "replicate_triggered"}` + CARLA :18802/start_replicate. **알 수 없는 차량이면 404, trigger 없음 [changed]** |
| `POST /branch` **[changed, 신규]** | `{"vehicle": "truck2", "status": "started"\|"complete"\|"failed"}` | 200 + 기록 객체. 필드가 잘못되면 400. baseline: 경로 없음(404) |
| `GET /branch` **[changed, 신규]** | – | `{vehicle, status, updated_at}` 또는 `{}` |
| `GET /snapshot` | – | `branch` 키가 추가됨 **[changed]** |
| `POST /reload` | – | branch 기록도 초기화 **[changed]** |

`/branch`는 **기록만** 한다. 군집 멤버십은 바꾸지 않는다.

## 시나리오 :18802 (bridge → 시나리오)

| Path | 효과 |
|---|---|
| `/start_merge`, `/branch` | 분기 trigger 이벤트 |
| `/start_replicate` | 복제만 시작. 분기는 이후 trigger로 시작 |

## 시나리오 → bridge

| 시점 | 호출 |
|---|---|
| `_start_migrate` | `/branch {vehicle: truck2, status: started}` |
| `_abort_branch` **[changed, 신규]** | `/branch {..., status: failed}` |
| `_finalize` | `/branch {..., status: complete}` |

## BranchReplicator (Python API)

| API | baseline | 현재 |
|---|---|---|
| `replicate(blocking=True)` | 항상 True | **성공 여부** 반환 [changed] |
| `replicate(blocking=False)` | 스레드 시작, True | 이미 진행 중이면 새로 시작하지 않음 [changed], True |
| `wait(timeout)` | 완료 여부 | **완료 AND 성공** [changed] |
| `finished()` | – | 완료 여부(성공/실패 무관) **[changed, 신규]** |

### 외부 명령 (FakeDocker 경계)

| 명령 | timeout | 실패 처리 |
|---|---|---|
| `docker save` | 없음 | RuntimeError → 복제 실패 |
| `docker load` | 없음 | "이미 존재"로 간주하고 계속 진행(원본 설계) |
| `docker rm -f openclaw-truck3` | 없음 | 무시 |
| `docker run -d --name openclaw-truck3 ... (port 18793)` | 없음 | `check=True` → 복제 실패 |

### config_bundle.tar (gzip)

```text
./SOUL.md (patched)  ./TOOLS.md  ./skills/platoon-negotiator/SKILL.md      ← truck1 (agents/platoon-a)
./AGENTS.md  ./data/vehicle_destinations.json  ./data/platoon_decision_context.json   ← agents/truck3 (필수 [changed])
```

### 명명 규칙 (정적 확인, B)

| 위치 | 분기 차량 표기 |
|---|---|
| README | 1부터 번호: `truck_3`, `openclaw-truck3` |
| 코드 | 0부터 번호: 분기 차량 = `truck2` |
| 컨테이너, 토큰, 포트 | `openclaw-truck3`, `TRUCK3_*`, 18793 (README에는 18792로 적혀 있음 — 문서 불일치) |
