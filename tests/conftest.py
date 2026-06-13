"""Shared fixtures for Truckclaw_copyable (split / agent replication).

- Bridge: the real bridge Handler is served in-process on an ephemeral port.
  Test isolation uses the bridge's existing POST /reload.
- CARLA side: FakeTriggerReceiver records bridge -> CARLA :18802 triggers.
- Docker: subprocess.run is monkeypatched with FakeDocker.
- Replicator: module PROJECT_ROOT is redirected to tmp_path, which receives a
  copy of the repository's real agents/ tree (so bundles use real templates).
No production code is modified for testability.
"""

from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bridge"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))

os.environ["PLATOON_DESTINATIONS_PATH"] = str(ROOT / "tests" / "fixtures" / "platoons.json")
os.environ["MOCK_CARLA"] = "false"

import platoon_bridge_server as bridge  # noqa: E402
from fakes.fake_docker import FakeDocker  # noqa: E402


class BridgeClient:
    def __init__(self, host, port, timeout=3.0):
        self.host, self.port, self.timeout = host, port, timeout

    @property
    def base_url(self):
        return f"http://{self.host}:{self.port}"

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        data = json.dumps(body).encode() if body is not None else None
        try:
            conn.request(method, path, body=data, headers={"Content-Type": "application/json"} if data else {})
            resp = conn.getresponse()
            text = resp.read().decode()
            return resp.status, (json.loads(text) if text else None)
        finally:
            conn.close()

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, body=None):
        return self.request("POST", path, body if body is not None else {})

    def members(self, platoon_id="platoon_a"):
        return [(m["vehicle_id"], m["role"]) for m in self.get(f"/platoons/{platoon_id}")[1]["members"]]

    def leader(self, platoon_id="platoon_a"):
        return next(v for v, r in self.members(platoon_id) if r == "leader")


class FakeTriggerReceiver:
    """Stands in for the scenario's :18802 trigger server (/start_replicate, /start_merge)."""

    def __init__(self):
        self.triggers: list[dict] = []
        self._lock = threading.Lock()
        fake = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
                with fake._lock:
                    fake.triggers.append(body)
                self.send_response(200)
                self.end_headers()

            def log_message(self, *a):
                pass

        self._server = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self._server.server_port}/start_replicate"

    def count(self, settle=0.3):
        time.sleep(settle)  # bridge sends the trigger from a background thread
        with self._lock:
            return len(self.triggers)

    def stop(self):
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture(scope="session")
def bridge_server():
    server = HTTPServer(("127.0.0.1", 0), bridge.Handler)
    server.RequestHandlerClass.log_message = lambda *a: None
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture
def client(bridge_server, monkeypatch):
    c = BridgeClient("127.0.0.1", bridge_server.server_port)
    monkeypatch.setattr(bridge, "MOCK_MODE", False)
    assert c.post("/reload")[0] == 200
    return c


@pytest.fixture
def replicate_receiver(client, monkeypatch):
    fake = FakeTriggerReceiver()
    monkeypatch.setattr(bridge, "CARLA_REPLICATE_URL", fake.url)
    yield fake
    fake.stop()


@pytest.fixture
def fake_docker(monkeypatch):
    fake = FakeDocker()
    monkeypatch.setattr(subprocess, "run", fake)
    return fake


@pytest.fixture
def replicator(monkeypatch, tmp_path):
    """openclaw_migration.replicator with PROJECT_ROOT redirected to tmp_path (holding a copy of agents/)."""
    import shutil
    from openclaw_migration import replicator as r

    shutil.copytree(ROOT / "agents", tmp_path / "agents")
    monkeypatch.setattr(r, "PROJECT_ROOT", tmp_path)
    for k in ("TRUCK3_DISCORD_BOT_TOKEN", "TRUCK3_OPENCLAW_GATEWAY_TOKEN", "OPENAI_API_KEY"):
        monkeypatch.setenv(k, f"test-{k.lower()}")
    return r


def scenario_replicator(r, tmp_path):
    """BranchReplicator constructed exactly as single_platoon_branch_scenario.py main() does."""
    return r.BranchReplicator(
        source_truck_id="truck0", branch_truck_id="truck2",
        branch_agent_dir=tmp_path / "agents" / "truck2",
        source_openclaw_data_dir=tmp_path / ".openclaw-truck0",
        branch_openclaw_data_dir=tmp_path / ".openclaw-truck2",
    )
