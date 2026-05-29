"""Bridge contract used by the branch scenario: POST /replicate (agent -> bridge -> CARLA :18802)
and POST /branch (scenario -> bridge progress reports)."""

import pytest


def test_replicate_triggers_carla_with_vehicle_id(client, replicate_receiver):
    status, body = client.post("/replicate", {"vehicle_id": "platoon_a_truck2"})
    assert status == 200 and body["status"] == "replicate_triggered"
    assert replicate_receiver.count() == 1
    assert replicate_receiver.triggers[0] == {"vehicle_id": "platoon_a_truck2"}


def test_bridge_accepts_branch_progress_reports(client):
    # REQ: the bridge must record the split lifecycle the scenario reports, so agents/operators can observe it.
    for status in ("started", "complete"):
        code, body = client.post("/branch", {"vehicle": "truck2", "status": status})
        assert code == 200, (status, body)
    assert client.get("/snapshot")[1]["branch"]["status"] == "complete"


@pytest.mark.xfail(strict=True, reason="DEF-C09: /replicate accepts an unknown vehicle_id and triggers CARLA")
def test_replicate_rejects_unknown_vehicle(client, replicate_receiver):
    # REQ: replication may only be requested for a vehicle that exists in the bridge state.
    status, _ = client.post("/replicate", {"vehicle_id": "ghost_truck9"})
    assert status == 404
    assert replicate_receiver.count() == 0


def test_branch_report_rejects_unknown_status(client):
    assert client.post("/branch", {"vehicle": "truck2", "status": "banana"})[0] == 400


def test_branch_failed_report_is_recorded(client):
    assert client.post("/branch", {"vehicle": "truck2", "status": "failed"})[0] == 200
    assert client.get("/branch")[1]["status"] == "failed"
