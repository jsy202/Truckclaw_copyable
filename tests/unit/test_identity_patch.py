"""Unit tests for the clone identity patch (existing behavior of _patch_soul)."""

from openclaw_migration import replicator


def test_patch_soul_rewrites_platoon_a_identity_to_truck3():
    src = "I am TRUCKCLAW2 for Platoon A (`platoon_a`). Peer: TRUCKCLAW1 <@1479297098938585170>. Me: <@1479297673432399923>\n## Role: Initiator"
    out = replicator._patch_soul(src)
    assert "TRUCKCLAW3" in out and "TRUCKCLAW2" not in out
    assert "<@1479297673432399923>" not in out and "<@1479297098938585170>" not in out
    assert "platoon_truck3" in out and "Solo Navigator" in out


def test_patch_soul_appends_branch_note_with_destination():
    assert "Your destination is `dest_b`" in replicator._patch_soul("x")


def test_identity_and_behavior_file_sets():
    assert set(replicator.IDENTITY_FILES) == {"AGENTS.md", "data/vehicle_destinations.json", "data/platoon_decision_context.json"}
    assert replicator.BEHAVIOR_FILES["SOUL.md"] == "patch"
