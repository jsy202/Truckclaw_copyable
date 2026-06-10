"""Regression tests pinning the independent audit of the committed Split 50-run evidence."""

import json
from pathlib import Path

import pytest

from validation.real_carla_50runs.tools import audit_raw_evidence as audit
from validation.real_carla_50runs.tools.split_validation import evaluate_split

ROOT = Path(__file__).resolve().parents[2] / "validation" / "real_carla_50runs"
EVIDENCE = ROOT / "evidence"

pytestmark = pytest.mark.skipif(not (EVIDENCE / "run050").is_dir(), reason="50-run evidence not present")


def _load(run, name):
    return json.loads((EVIDENCE / "run{:03d}".format(run) / name).read_text())


def test_fixed_evaluator_and_independent_audit_agree_on_raw_evidence():
    evaluator_failures = []
    for run in range(1, 51):
        verdict = evaluate_split(_load(run, "initial_snapshot.json"),
                                 _load(run, "transition_events.json"),
                                 _load(run, "final_snapshot.json"))
        if not verdict["passed"]:
            evaluator_failures.append(run)
    audit_failures = [run for run in range(1, 51) if not audit.audit_run(EVIDENCE / "run{:03d}".format(run))["passed"]]
    assert evaluator_failures == audit_failures == []


def test_run004_is_the_no_adjacent_lane_fallback_and_not_a_lane_change():
    final = _load(4, "final_snapshot.json")
    lanes = {name: final["actors"][name]["lane_id"] for name in ("truck0", "truck1", "truck2")}
    assert lanes == {"truck0": -3, "truck1": -3, "truck2": -3}
    assert final["actors"]["truck2"]["road_id"] != final["actors"]["truck0"]["road_id"]
    lane_event = next(e for e in _load(4, "transition_events.json") if e["event"] == "lane_separated")
    gap_event = next(e for e in _load(4, "transition_events.json") if e["event"] == "gap_ready")
    # LC "completed" one 10 ms tick after gap_ready: no lane change took place.
    assert lane_event["simulation_time_s"] - gap_event["simulation_time_s"] == pytest.approx(0.01, abs=1e-6)


def test_audit_raw_evidence_has_no_integrity_issues():
    runs = {n: audit.audit_run(EVIDENCE / "run{:03d}".format(n)) for n in range(1, 51)}
    assert all(not r["problems"] for r in runs.values())
    assert sum(r["timeout"] for r in runs.values()) == 0
    assert sum(r["crash"] for r in runs.values()) == 0
    assert sum(r["cleanup_failure"] for r in runs.values()) == 0
    assert all(r["accepted_triggers"] == 1 for r in runs.values())
