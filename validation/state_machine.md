# State Machines — Truckclaw_copyable

## BranchCoordinator (`BranchState`)

연구 당시의 상태만 사용한다. 새 상태는 없다.

```text
CRUISE ──trigger──▶ MIGRATE ──replication success──▶ GAP ─▶ LC ─▶ SIDE_BY_SIDE ─▶ DONE
   ▲    (already replicated → GAP)  │
   └──── replication failed / MIGRATE_TIMEOUT_S 초과 (bridge /branch failed) [changed]
```

| 상태 | Entry | Exit | Timeout | Failure |
|---|---|---|---|---|
| CRUISE | 시작 또는 중단 | trigger → MIGRATE. 복제가 이미 성공했거나 replicator가 없으면 GAP | – | – |
| MIGRATE | `_start_migrate`: `/branch started`, `replicate(blocking=False)` | `wait(0)`이 True면 GAP | **120 s [changed]** | **finished 상태인데 성공이 아니면 → `_abort_branch` → CRUISE [changed]** (baseline: 실패해도 GAP으로 진행) |
| GAP → LC → SIDE_BY_SIDE | 물리 분리·차선 변경 | – | 없음 | 없음 (CARLA 필요, 미검증) |
| DONE | `_finalize`: `/branch complete` | – | – | – |

## BranchReplicator

```text
idle ──replicate()──▶ running ──ok──▶ done/success
          ▲              ├─ replicate() again → ignored [changed]
          │              └─ error (save/run fail, identity incomplete [changed]) ─▶ done/failed
          └──────────── replicate() (resets done/success) [changed] ─────────────────┘
```

## Bridge `/branch` 기록 [changed, 신규]

`{}` → started → complete 또는 failed. 전이 순서는 강제하지 않는다(기록용, 최소 구현).
