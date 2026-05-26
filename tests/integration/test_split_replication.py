"""Split (branch) + OpenClaw agent replication, without CARLA or Docker.

- BranchReplicator runs for real with docker replaced by FakeDocker and
  PROJECT_ROOT redirected to tmp_path (holding a copy of the real agents/ tree).
- BranchCoordinator is imported from the scenario with CARLA stubbed and is
  driven only through CRUISE -> MIGRATE -> GAP (the physical part needs CARLA).
"""

import tarfile
import time
from unittest.mock import MagicMock

import pytest

from conftest import scenario_replicator
from fakes.carla_stub import load_scenario_module


# ── replicator ───────────────────────────────────────────────────────────────

def _template_replicator(r, tmp_path):
    """Replicator pointed at the identity template the repo actually ships (agents/truck3)."""
    return r.BranchReplicator(
        source_truck_id="truck0", branch_truck_id="truck2",
        branch_agent_dir=tmp_path / "agents" / "truck3",
        branch_openclaw_data_dir=tmp_path / ".openclaw-truck2",
    )


def test_replication_with_shipped_template_starts_branch_agent(replicator, tmp_path, fake_docker):
    rep = _template_replicator(replicator, tmp_path)
    rep.replicate(blocking=True)
    assert rep._success is True
    assert fake_docker.subcommands() == ["save", "load", "rm", "run"]
    run = fake_docker.calls[-1]
    assert run[run.index("--name") + 1] == "openclaw-truck3"
    data = tmp_path / ".openclaw-truck2"
    assert "TRUCKCLAW3" in (data / "SOUL.md").read_text() and "Branched Vehicle Note" in (data / "SOUL.md").read_text()
    for rel in ("AGENTS.md", "data/vehicle_destinations.json", "data/platoon_decision_context.json", "TOOLS.md"):
        assert (data / rel).exists(), rel


def test_config_bundle_patches_identity_in_soul(replicator, tmp_path):
    out = tmp_path / "bundle.tar"
    replicator.create_config_bundle(out, tmp_path / "agents" / "platoon-a", tmp_path / "agents" / "truck3")
    with tarfile.open(out, "r:gz") as tar:
        soul = tar.extractfile("./SOUL.md").read().decode()
    assert "<@1479297673432399923>" not in soul          # platoon A's Discord id must not leak into the clone
    assert "TRUCKCLAW2" not in soul and "TRUCKCLAW3" in soul


def test_v2v_transfer_is_byte_identical(replicator, tmp_path):
    import hashlib
    src = tmp_path / "src.bin"
    src.write_bytes(bytes(range(256)) * 1000)
    dst = tmp_path / "rx" / "dst.bin"
    replicator._v2v_transfer(src, dst, "test")
    assert hashlib.sha256(dst.read_bytes()).digest() == hashlib.sha256(src.read_bytes()).digest()


def test_docker_run_failure_marks_replication_failed(replicator, tmp_path, fake_docker):
    fake_docker.fail("run")
    rep = _template_replicator(replicator, tmp_path)
    rep.replicate(blocking=True)
    assert rep._success is False and rep._done_event.is_set()


def test_wait_reports_failure_after_failed_replication(replicator, tmp_path, fake_docker):
    # REQ: BranchReplicator.wait() must be True only for a successful replication.
    fake_docker.fail("save")
    rep = _template_replicator(replicator, tmp_path)
    rep.replicate(blocking=True)
    assert rep.wait(timeout=0) is False


def test_cli_exit_code_reflects_replication_failure(replicator, tmp_path, fake_docker, monkeypatch):
    # REQ: the standalone tool must signal failure through its exit code.
    fake_docker.fail("save")
    monkeypatch.setattr("sys.argv", ["replicator.py",
                                     "--truck1-agent", str(tmp_path / "agents" / "platoon-a"),
                                     "--truck3-template", str(tmp_path / "agents" / "truck3"),
                                     "--openclaw-dir", str(tmp_path / ".openclaw-truck3")])
    assert replicator.main() == 1


@pytest.mark.xfail(strict=True, reason="DEF-C03: replication 'succeeds' with no identity files when the identity template dir is missing")
def test_replication_fails_when_identity_template_missing(replicator, tmp_path, fake_docker):
    # REQ: a replicated agent must not start without its identity files (AGENTS.md, destinations, decision context).
    rep = scenario_replicator(replicator, tmp_path)   # agents/truck2 does not exist in the repo
    assert not (tmp_path / "agents" / "truck2").exists()
    rep.replicate(blocking=True)
    assert rep._success is False
    assert "run" not in fake_docker.subcommands()


def test_scenario_branch_agent_dir_exists_in_repo():
    # REQ: the identity template the scenario actually passes must exist in the repository.
    # Static contract check (AST of single_platoon_branch_scenario.py main()); CARLA is not needed.
    import ast
    from fakes.carla_stub import ROOT, SCENARIO
    tree = ast.parse(SCENARIO.read_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "BranchReplicator"]
    assert len(calls) == 1
    arg = next(k.value for k in calls[0].keywords if k.arg == "branch_agent_dir")
    def path_parts(node):  # left-to-right string constants of `_PROJECT / "a" / "b"`
        if isinstance(node, ast.BinOp):
            return path_parts(node.left) + path_parts(node.right)
        return [node.value] if isinstance(node, ast.Constant) and isinstance(node.value, str) else []
    parts = path_parts(arg)
    template = ROOT.joinpath(*parts)
    assert template.is_dir(), f"{template.relative_to(ROOT)} does not exist"
    assert (template / "AGENTS.md").exists()


def test_concurrent_replicate_calls_run_once(replicator, tmp_path, fake_docker):
    # REQ: one split = one replication; duplicate requests while in progress are ignored.
    fake_docker.hang("save", seconds=0.5)
    rep = _template_replicator(replicator, tmp_path)
    rep.replicate(blocking=False)
    time.sleep(0.1)
    rep.replicate(blocking=False)          # e.g. /start_replicate followed by the split trigger
    rep._done_event.wait(3)
    time.sleep(0.8)
    assert fake_docker.subcommands().count("save") == 1


# ── scenario coordinator (CARLA stubbed) ─────────────────────────────────────

@pytest.fixture
def scenario(monkeypatch):
    mod = load_scenario_module(monkeypatch)
    posts = []
    monkeypatch.setattr(mod, "_bridge_post", lambda path, body=None: posts.append((path, body)) or {"ok": True})
    mod._test_posts = posts
    return mod


def _pump(coord, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and coord.state.name in ("CRUISE", "MIGRATE"):
        if coord.state.name == "CRUISE" and not coord.triggered:
            return
        coord.update(0)
        time.sleep(0.01)


def _coordinator(scenario, rep):
    coord = scenario.BranchCoordinator(MagicMock(), MagicMock(), MagicMock(), replicator=rep)
    coord.trigger()
    return coord


def test_coordinator_advances_to_gap_after_successful_replication(scenario, replicator, tmp_path, fake_docker):
    coord = _coordinator(scenario, _template_replicator(replicator, tmp_path))
    _pump(coord, 3.0)
    assert coord.state.name == "GAP"
    assert ("/branch", {"vehicle": "truck2", "status": "started"}) in scenario._test_posts


def test_split_does_not_proceed_when_replication_fails(scenario, replicator, tmp_path, fake_docker):
    # REQ: the physical split must not start unless the branch agent was replicated successfully;
    # the failure is reported and the vehicle stays in the platoon.
    fake_docker.fail("run", stderr="port 18793 already in use")
    coord = _coordinator(scenario, _template_replicator(replicator, tmp_path))
    _pump(coord, 2.0)
    assert coord.state.name == "CRUISE"
    assert ("/branch", {"vehicle": "truck2", "status": "failed"}) in scenario._test_posts


def test_coordinator_times_out_hung_replication(scenario, replicator, tmp_path, fake_docker, monkeypatch):
    # REQ: a replication that never finishes must not block the branch forever.
    monkeypatch.setattr(scenario, "MIGRATE_TIMEOUT_S", 0.3)  # default 120 s, shortened for the test
    fake_docker.hang("save", seconds=3.0)
    coord = _coordinator(scenario, _template_replicator(replicator, tmp_path))
    _pump(coord, 1.5)
    assert coord.state.name == "CRUISE"
    assert ("/branch", {"vehicle": "truck2", "status": "failed"}) in scenario._test_posts
