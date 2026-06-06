import json

import pytest

from validation.real_carla_50runs.tools.split_validation import (
    atomic_write_json,
    evaluate_split,
    load_json,
    summarize_results,
)


def good_split_evidence():
    initial = {
        "scenario_state": "CRUISE",
        "main_members": ["truck0", "truck1", "truck2"],
        "actors": {name: {"alive": True} for name in ("truck0", "truck1", "truck2")},
    }
    events = [
        {"event": "trigger", "accepted": True, "trigger_count": 1, "since_trigger_s": 0.0},
        {"event": "logical_detach", "main_members": ["truck0", "truck1"], "detached_members": ["truck2"], "since_trigger_s": 0.2},
        {"event": "gap_ready", "gap_m": 15.25, "stable_ticks": 10, "since_trigger_s": 1.5},
        {"event": "lane_separated", "since_trigger_s": 2.5},
        {"event": "done", "since_trigger_s": 7.5},
    ]
    final = {
        "scenario_state": "DONE",
        "main_members": ["truck0", "truck1"],
        "detached_members": ["truck2"],
        "actors": {
            "truck0": {"alive": True, "road_id": 46, "lane_id": -3, "speed_kmh": 20.0},
            "truck1": {"alive": True, "road_id": 46, "lane_id": -3, "speed_kmh": 19.8},
            "truck2": {"alive": True, "road_id": 46, "lane_id": -4, "speed_kmh": 20.1},
        },
        "controllers": {"truck2": {"type": "LeadNavigator", "platoon": "detached"}},
        "collisions": [],
        "post_done_displacement_m": {"truck2": 10.8},
        "trigger_count": 1,
    }
    return initial, events, final


def test_evaluator_requires_logical_and_physical_split_not_done_alone():
    initial, events, final = good_split_evidence()
    assert evaluate_split(initial, events, final)["passed"] is True

    final["main_members"] = ["truck0", "truck1", "truck2"]
    result = evaluate_split(initial, events, final)
    assert result["passed"] is False
    assert result["checks"]["logical_membership"] is False


@pytest.mark.parametrize(
    ("mutation", "failed_check"),
    [
        (lambda i, e, f: e.__setitem__(2, {**e[2], "gap_m": 14.99}), "gap_ready"),
        (lambda i, e, f: e.__setitem__(2, {**e[2], "stable_ticks": 9}), "gap_ready"),
        (lambda i, e, f: f["actors"]["truck2"].update(lane_id=-3), "lane_separation"),
        (lambda i, e, f: f["post_done_displacement_m"].update(truck2=0.49), "independent_motion"),
        (lambda i, e, f: f["controllers"]["truck2"].update(type="FollowerController"), "independent_controller"),
        (lambda i, e, f: f["collisions"].append({"actor": "truck2"}), "collision_free"),
        (lambda i, e, f: f.update(trigger_count=2), "single_trigger"),
        (lambda i, e, f: f["actors"]["truck1"].update(alive=False), "actors_alive"),
    ],
)
def test_evaluator_rejects_each_fixed_split_invariant(mutation, failed_check):
    initial, events, final = good_split_evidence()
    mutation(initial, events, final)
    result = evaluate_split(initial, events, final)
    assert result["passed"] is False
    assert result["checks"][failed_check] is False


def test_evaluator_requires_three_initial_live_members():
    initial, events, final = good_split_evidence()
    initial["main_members"] = ["truck0", "truck1"]
    result = evaluate_split(initial, events, final)
    assert result["checks"]["initial_state"] is False


def test_atomic_json_never_leaves_temporary_file(tmp_path):
    path = tmp_path / "evidence" / "result.json"
    atomic_write_json(path, {"passed": False, "run": 7})
    assert json.loads(path.read_text()) == {"passed": False, "run": 7}
    assert list(path.parent.glob("*.tmp")) == []


def test_missing_or_corrupt_json_is_an_explicit_error(tmp_path):
    with pytest.raises(ValueError, match="missing JSON"):
        load_json(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    with pytest.raises(ValueError, match="invalid JSON"):
        load_json(bad)


def test_summary_preserves_failures_and_uses_interpolated_percentiles():
    results = [
        {"passed": True, "timings": {"trigger_to_done_s": 1.0}},
        {"passed": False, "timings": {"trigger_to_done_s": 2.0}, "failure_reasons": ["collision_free"]},
        {"passed": True, "timings": {"trigger_to_done_s": 3.0}},
    ]
    summary = summarize_results(results)
    assert summary["runs"] == 3 and summary["successes"] == 2 and summary["failures"] == 1
    assert summary["timing"]["mean"] == 2.0
    assert summary["timing"]["p50"] == 2.0
    assert summary["timing"]["p95"] == 2.9
    assert summary["timing"]["max"] == 3.0

