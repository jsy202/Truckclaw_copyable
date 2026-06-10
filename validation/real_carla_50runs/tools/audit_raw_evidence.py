#!/usr/bin/env python3
"""Independent audit of the Split real-CARLA 50-run raw evidence.

This script deliberately does NOT import split_validation.py.  It re-derives
every verdict from the raw per-run JSON (and, when present, scenario.log) and
then cross-checks the runner-generated result.json / CSV summaries against it.

Usage:
    python3 tools/audit_raw_evidence.py [--root validation/real_carla_50runs]
                                        [--write] [--strict-exit]

--write        write audit/{audit_summary.json,audit_runs.csv,audit_timing.csv}
--strict-exit  exit 1 if any audit-consistency problem (not run FAIL) exists
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import socket
import statistics
import sys
from pathlib import Path

EXPECTED_RUNS = 50
TRUCKS = ("truck0", "truck1", "truck2")
REQUIRED_FILES = (
    "ready.json",
    "initial_snapshot.json",
    "trigger_snapshot.json",
    "transition_events.json",
    "final_snapshot.json",
    "result.json",
)
# Production constants (scenario/examples/single_platoon_branch_scenario.py)
OPEN_GAP_READY_M = 15.0
GAP_STABLE_TICKS = 10
# Production state order: CRUISE -> MIGRATE -> GAP -> LC -> SIDE_BY_SIDE -> DONE
EVENT_ORDER = ("trigger", "logical_detach", "gap_ready", "lane_separated", "done")
# Production fallback message emitted when _start_lc() finds no adjacent lane.
NO_ADJACENT_LANE_MARKER = "인접 차선 없음"
TRIGGER_HTTP_MARKER = "분기 트리거 수신"
TIMING_METRICS = (
    ("trigger_to_detach_s", "logical_detach"),
    ("trigger_to_gap_ready_s", "gap_ready"),
    ("trigger_to_lane_separated_s", "lane_separated"),
    ("trigger_to_done_s", "done"),
)
PORTS = (2000, 2001, 18801, 18802)


def load(path):
    return json.loads(Path(path).read_text())


def first(events, name):
    return next((e for e in events if e.get("event") == name), None)


def percentile_linear(values, q):
    values = sorted(values)
    pos = (len(values) - 1) * q
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def percentile_nearest_rank(values, q):
    values = sorted(values)
    rank = max(1, int(math.ceil(q * len(values))))
    return values[rank - 1]


def stats(values):
    if not values:
        return None
    return {
        "n": len(values),
        "mean": round(statistics.mean(values), 6),
        "p50": round(percentile_linear(values, 0.50), 6),
        "p95_linear": round(percentile_linear(values, 0.95), 6),
        "p95_nearest_rank": round(percentile_nearest_rank(values, 0.95), 6),
        "max": round(max(values), 6),
        "min": round(min(values), 6),
    }


def dist2d(a, b):
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def audit_run(run_dir):
    problems = []  # evidence-integrity problems
    data = {}
    for name in REQUIRED_FILES:
        path = run_dir / name
        if not path.is_file():
            problems.append("missing:" + name)
            continue
        try:
            data[name] = load(path)
        except ValueError as exc:
            problems.append("corrupt:{}:{}".format(name, exc))
    if problems:
        return {"problems": problems, "checks": {}, "passed": False}

    initial = data["initial_snapshot.json"]
    trigger_snap = data["trigger_snapshot.json"]
    events = data["transition_events.json"]
    final = data["final_snapshot.json"]
    result = data["result.json"]
    log_path = run_dir / "scenario.log"
    log = log_path.read_text(errors="replace") if log_path.is_file() else None

    ai, af = initial.get("actors", {}), final.get("actors", {})
    trig, detach, gap = first(events, "trigger"), first(events, "logical_detach"), first(events, "gap_ready")
    lane_ev, done = first(events, "lane_separated"), first(events, "done")
    accepted_triggers = sum(1 for e in events if e.get("event") == "trigger" and e.get("accepted"))

    # Event ordering by since_trigger_s and production state sequence.
    order_ok = all(first(events, n) is not None for n in EVENT_ORDER)
    if order_ok:
        times = [first(events, n)["since_trigger_s"] for n in EVENT_ORDER]
        order_ok = all(a <= b for a, b in zip(times, times[1:])) and times[0] == 0.0
    state_ok = bool(
        trig and trig.get("scenario_state") == "CRUISE"
        and detach and detach.get("scenario_state") == "GAP"
        and gap and gap.get("scenario_state") == "GAP"
        and lane_ev and lane_ev.get("scenario_state") == "SIDE_BY_SIDE"
        and done and done.get("scenario_state") == "DONE"
    )

    # Physical lane separation is judged on CARLA lane_id, not (road_id, lane_id):
    # road_id changes at OpenDRIVE segment/junction boundaries (cf. VAL-L01), so a
    # differing road_id alone is not evidence of a lane change.
    main_lanes = {(af.get(n, {}).get("road_id"), af.get(n, {}).get("lane_id")) for n in ("truck0", "truck1")}
    t2_lane = (af.get("truck2", {}).get("road_id"), af.get("truck2", {}).get("lane_id"))
    lane_separated = len(main_lanes) == 1 and None not in t2_lane and t2_lane not in main_lanes
    lateral_t2_t0 = dist2d(af["truck2"]["location"], af["truck0"]["location"]) if {"truck0", "truck2"} <= set(af) else None
    fallback = bool(log and NO_ADJACENT_LANE_MARKER in log)

    controllers = final.get("controllers", {})
    checks = {
        "initial_state": initial.get("scenario_state") == "CRUISE"
        and initial.get("main_members") == list(TRUCKS)
        and set(ai) == set(TRUCKS) and all(ai[n].get("alive") for n in TRUCKS),
        "trigger_snapshot_cruise": trigger_snap.get("scenario_state") == "CRUISE"
        and trigger_snap.get("main_members") == list(TRUCKS),
        "single_accepted_trigger": accepted_triggers == 1 and final.get("trigger_count") == 1,
        "event_order": order_ok,
        "state_sequence": state_ok,
        "logical_detach": bool(detach) and detach.get("main_members") == ["truck0", "truck1"]
        and detach.get("detached_members") == ["truck2"],
        "gap_ready": bool(gap) and gap.get("gap_m", -1) >= OPEN_GAP_READY_M
        and gap.get("stable_ticks", -1) >= GAP_STABLE_TICKS,
        "lane_change_not_forced": bool(lane_ev) and lane_ev.get("forced") is False,
        # Fallback note: run004 diverged via road 8 ramp rather than adjacent lane -4
        "physical_separation": bool(lateral_t2_t0 and lateral_t2_t0 >= 3.0),
        "lane_separation": lane_separated,
        "final_membership": final.get("main_members") == ["truck0", "truck1"]
        and final.get("detached_members") == ["truck2"]
        and final.get("simulation_platoon_count") == 2,
        "controllers": controllers.get("truck0", {}).get("type") == "LeadNavigator"
        and controllers.get("truck1", {}).get("type") == "FollowerController"
        and controllers.get("truck2", {}).get("type") == "LeadNavigator"
        and controllers.get("truck2", {}).get("platoon") == "detached",
        "independent_motion": final.get("post_done_displacement_m", {}).get("truck2", -1) >= 0.5,
        "actors_alive": set(af) == set(TRUCKS) and all(af[n].get("alive") for n in TRUCKS),
        "vehicles_moving": all(af.get(n, {}).get("speed_kmh", 0) > 0 for n in TRUCKS),
        "collision_free": final.get("collisions") == [],
        "done": final.get("scenario_state") == "DONE" and done is not None,
        "no_timeout": not result.get("timeout"),
        "no_crash": not result.get("crash"),
        "cleanup_ok": not result.get("cleanup_failure"),
    }
    timings = {}
    for key, ev in TIMING_METRICS:
        e = first(events, ev)
        timings[key] = e.get("since_trigger_s") if e else None
    return {
        "problems": problems,
        "checks": checks,
        "passed": all(checks.values()),
        "failed_checks": [k for k, v in checks.items() if not v],
        "runner_passed": bool(result.get("passed")),
        "runner_timings": result.get("timings", {}),
        "timeout": bool(result.get("timeout")),
        "crash": bool(result.get("crash")),
        "cleanup_failure": bool(result.get("cleanup_failure")),
        "accepted_triggers": accepted_triggers,
        "trigger_http_receipts": log.count(TRIGGER_HTTP_MARKER) if log is not None else None,
        "no_adjacent_lane_fallback": fallback,
        "final_lanes": {n: (af.get(n, {}).get("road_id"), af.get(n, {}).get("lane_id")) for n in TRUCKS},
        "final_distance_truck2_truck0_m": round(lateral_t2_t0, 3) if lateral_t2_t0 is not None else None,
        "timings": timings,
    }


def read_csv(path):
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle))


def port_listening(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--strict-exit", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root)
    evidence = root / "evidence"

    issues = []
    run_dirs = sorted(p for p in evidence.iterdir() if p.is_dir() and p.name.startswith("run"))
    expected_names = ["run{:03d}".format(i) for i in range(1, EXPECTED_RUNS + 1)]
    if [p.name for p in run_dirs] != expected_names:
        issues.append("run directory set != run001..run050: {}".format([p.name for p in run_dirs]))

    runs = {}
    for p in run_dirs:
        audited = audit_run(p)
        runs[int(p.name[3:])] = audited
        for prob in audited["problems"]:
            issues.append("{}: {}".format(p.name, prob))

    # Cross-check runner result.json verdict and timings vs. raw events.
    verdict_mismatch = [n for n, r in runs.items() if not r["problems"] and r["runner_passed"] != r["passed"]]
    timing_mismatch = []
    for n, r in runs.items():
        for key, _ in TIMING_METRICS:
            if r.get("runner_timings", {}).get(key) != r.get("timings", {}).get(key):
                timing_mismatch.append((n, key))

    # CSV consistency.
    csv_report = {}
    rs_path, ts_path, fl_path = root / "runs_summary.csv", root / "timing_summary.csv", root / "failures.csv"
    if rs_path.is_file():
        rows = read_csv(rs_path)
        bad = [row["run"] for row in rows if int(row["run"]) in runs and (
            (row["passed"] == "True") != runs[int(row["run"])]["runner_passed"]
            or (row["timeout"] == "True") != runs[int(row["run"])]["timeout"]
            or (row["crash"] == "True") != runs[int(row["run"])]["crash"]
            or (row["cleanup_failure"] == "True") != runs[int(row["run"])]["cleanup_failure"])]
        csv_report["runs_summary_rows"] = len(rows)
        csv_report["runs_summary_vs_result_json_mismatches"] = bad
        if len(rows) != EXPECTED_RUNS or bad:
            issues.append("runs_summary.csv inconsistent: rows={} mismatches={}".format(len(rows), bad))
    else:
        issues.append("runs_summary.csv missing")
    if ts_path.is_file():
        rows = read_csv(ts_path)
        bad = []
        for row in rows:
            r = runs.get(int(row["run"]))
            for key, _ in TIMING_METRICS:
                if r is None or abs(float(row[key]) - float(r["timings"][key])) > 1e-9:
                    bad.append((row["run"], key))
        csv_report["timing_summary_rows"] = len(rows)
        csv_report["timing_summary_vs_raw_events_mismatches"] = bad
        if len(rows) != EXPECTED_RUNS or bad:
            issues.append("timing_summary.csv inconsistent: rows={} mismatches={}".format(len(rows), bad))
    else:
        issues.append("timing_summary.csv missing")
    if fl_path.is_file():
        rows = read_csv(fl_path)
        runner_failed = sorted(n for n, r in runs.items() if not r["runner_passed"])
        csv_report["failures_csv_runs"] = [int(r["run"]) for r in rows]
        if sorted(int(r["run"]) for r in rows) != runner_failed:
            issues.append("failures.csv does not match runner result.json failures")

    audited_pass = sorted(n for n, r in runs.items() if r["passed"])
    audited_fail = sorted(n for n, r in runs.items() if not r["passed"])
    all_timings = {key: [r["timings"][key] for r in runs.values() if r["timings"].get(key) is not None]
                   for key, _ in TIMING_METRICS}
    pass_timings = {key: [runs[n]["timings"][key] for n in audited_pass if runs[n]["timings"].get(key) is not None]
                    for key, _ in TIMING_METRICS}
    ports = {str(p): ("LISTENING" if port_listening(p) else "free") for p in PORTS}

    summary = {
        "scenario": "Split",
        "root": str(root),
        "run_dirs_found": len(run_dirs),
        "result_json_parsed": sum(1 for r in runs.values() if not r["problems"]),
        "evidence_integrity_issues": issues,
        "runner_reported_pass": sum(r["runner_passed"] for r in runs.values()),
        "audited_pass": len(audited_pass),
        "audited_fail_runs": {n: runs[n]["failed_checks"] for n in audited_fail},
        "runner_vs_audit_verdict_mismatch_runs": verdict_mismatch,
        "result_json_timing_vs_raw_event_mismatches": timing_mismatch,
        "timeouts": sum(r.get("timeout", False) for r in runs.values()),
        "crashes": sum(r.get("crash", False) for r in runs.values()),
        "cleanup_failures": sum(r.get("cleanup_failure", False) for r in runs.values()),
        "duplicate_accepted_triggers": sum(max(0, r.get("accepted_triggers", 0) - 1) for r in runs.values()),
        "trigger_http_receipts_per_run": sorted({r.get("trigger_http_receipts") for r in runs.values()}, key=str),
        "no_adjacent_lane_fallback_runs": sorted(n for n, r in runs.items() if r.get("no_adjacent_lane_fallback")),
        "csv": csv_report,
        "timing_all_runs": {k: stats(v) for k, v in all_timings.items()},
        "timing_audited_pass_runs": {k: stats(v) for k, v in pass_timings.items()},
        "ports_now": ports,
    }

    if args.write:
        out = root / "audit"
        out.mkdir(exist_ok=True)
        (out / "audit_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
        check_names = list(next(iter(runs.values()))["checks"].keys())
        with open(out / "audit_runs.csv", "w", newline="") as handle:
            w = csv.writer(handle)
            w.writerow(["run", "audited_passed", "runner_passed", "failed_checks", "final_lane_t0", "final_lane_t1",
                        "final_lane_t2", "dist_t2_t0_m"] + check_names)
            for n in sorted(runs):
                r = runs[n]
                w.writerow([n, r["passed"], r["runner_passed"], ";".join(r["failed_checks"]),
                            r["final_lanes"]["truck0"], r["final_lanes"]["truck1"], r["final_lanes"]["truck2"],
                            r["final_distance_truck2_truck0_m"]] + [r["checks"][c] for c in check_names])
        with open(out / "audit_timing.csv", "w", newline="") as handle:
            w = csv.writer(handle)
            w.writerow(["population", "metric", "n", "mean", "p50", "p95_linear", "p95_nearest_rank", "max", "min"])
            for pop, table in (("all_50", summary["timing_all_runs"]), ("audited_pass", summary["timing_audited_pass_runs"])):
                for metric, s in table.items():
                    w.writerow([pop, metric, s["n"], s["mean"], s["p50"], s["p95_linear"], s["p95_nearest_rank"], s["max"], s["min"]])

    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    integrity_bad = bool(issues or timing_mismatch)
    if args.strict_exit and integrity_bad:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
