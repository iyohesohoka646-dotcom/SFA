"""Local deployment must survive its launcher and never stop unrelated services."""
import json
import os
import socket
import subprocess
import sys
import time
from urllib.request import Request, urlopen

from fastapi.testclient import TestClient

from contract_driven_ai_flow.api import create_app
from contract_driven_ai_flow.examples import module
from contract_driven_ai_flow.models import ProbeSpec, ProjectSpec
from contract_driven_ai_flow.storage import Store, atomic_write


def command(root, *arguments):
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-c", "from contract_driven_ai_flow.cli import app; app()", "studio", "--project", str(root), *arguments],
        capture_output=True, text=True, encoding="utf-8", timeout=40,
    )


def request(record, route="/api/v1/studio", method="GET"):
    address = f"http://127.0.0.1:{record['port']}{route}"
    with urlopen(Request(address, headers={"Authorization": "Bearer " + record["token"]}, method=method), timeout=2) as response:
        return json.load(response)


def cleanup(root):
    state = root / ".cdaf/studio.json"
    if state.exists():
        try:
            request(json.loads(state.read_text(encoding="utf-8")), "/api/v1/studio/shutdown", "POST")
        except (OSError, ValueError):
            pass
    deadline = time.monotonic() + 10
    while state.exists() and time.monotonic() < deadline:
        time.sleep(.1)


def test_background_service_survives_launcher_exit_and_reuses_process(tmp_path):
    root = tmp_path / "local project"
    Store(root).save(ProjectSpec(name="Persistent Studio"), None)
    with socket.socket() as handle:
        handle.bind(("127.0.0.1", 0))
        port = handle.getsockname()[1]
    try:
        first = command(root, "--port", str(port), "--background", "--no-open")
        assert first.returncode == 0, first.stderr
        launched = json.loads(first.stdout)
        record = json.loads((root / ".cdaf/studio.json").read_text(encoding="utf-8"))
        assert launched["pid"] == request(record)["pid"]
        assert launched["pid"] != os.getpid()
        with urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
            assert b"assets/index-" in response.read()
        assert request(record, "/api/v1/project")["project"]["name"] == "Persistent Studio"
        again = command(root, "--port", str(port), "--background", "--no-open")
        assert again.returncode == 0, again.stderr
        assert json.loads(again.stdout)["pid"] == launched["pid"]
        assert json.loads(again.stdout)["reused"] is True
        stopped = command(root, "--stop", "--no-open")
        assert stopped.returncode == 0, stopped.stderr
        assert json.loads(stopped.stdout)["stopped"] is True
        with socket.socket() as handle:
            assert handle.connect_ex(("127.0.0.1", port)) != 0
    finally:
        cleanup(root)


def test_occupied_port_fails_without_replacing_listener(tmp_path):
    Store(tmp_path).save(ProjectSpec(), None)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        result = command(tmp_path, "--port", str(port), "--background", "--no-open")
        assert result.returncode == 1, result.stderr
        assert str(port) in result.stderr
        assert not (tmp_path / ".cdaf/studio.json").exists()
        assert listener.getsockname()[1] == port


def test_stale_state_cannot_kill_reused_pid(tmp_path):
    Store(tmp_path).save(ProjectSpec(), None)
    with socket.socket() as handle:
        handle.bind(("127.0.0.1", 0))
        port = handle.getsockname()[1]
    state = tmp_path / ".cdaf/studio.json"
    state.write_text(json.dumps({"pid": os.getpid(), "port": port, "token": "expired-session", "project": str(tmp_path)}), encoding="utf-8")
    result = command(tmp_path, "--stop", "--no-open")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["stopped"] is False
    assert not state.exists()


def test_simultaneous_shortcut_launches_share_one_server(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    Store(tmp_path).save(ProjectSpec(), None)
    with socket.socket() as handle:
        handle.bind(("127.0.0.1", 0))
        port = handle.getsockname()[1]
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _: command(tmp_path, "--port", str(port), "--background", "--no-open"), range(2)))
        assert all(response.returncode == 0 for response in responses), [response.stderr for response in responses]
        records = [json.loads(response.stdout) for response in responses]
        assert len({record["pid"] for record in records}) == 1
        assert sorted(record["reused"] for record in records) == [False, True]
    finally:
        cleanup(tmp_path)


def test_shutdown_is_authenticated_and_calls_graceful_control(tmp_path):
    Store(tmp_path).save(ProjectSpec(), None)
    calls = []
    with TestClient(create_app(tmp_path, token="studio-session", shutdown=lambda: calls.append("shutdown"))) as client:
        assert client.post("/api/v1/studio/shutdown").status_code == 401
        assert calls == []
        headers = {"Authorization": "Bearer studio-session"}
        response = client.post("/api/v1/studio/shutdown", headers=headers)
        assert response.status_code == 200
        assert calls == ["shutdown"]


def test_shutdown_cancels_breakpoint_run_before_waiting_for_connections(tmp_path):
    project = ProjectSpec(modules=[module("f", {}, {"type": "integer"})],
                          probes=[ProbeSpec(id="hold", module="f", expression="True", policy="breakpoint")])
    store = Store(tmp_path)
    store.save(project, None)
    atomic_write(tmp_path / "src/steps.py", "def f():\n    return 1\n")
    headers = {"Authorization": "Bearer studio-session"}
    with TestClient(create_app(tmp_path, token="studio-session", shutdown=lambda: None)) as client:
        response = client.post("/api/v1/runs", headers=headers, json={"input": {}, "base_revision": project.revision})
        assert response.status_code == 202
        run_id = response.json()["id"]
        deadline = time.monotonic() + 10
        while store.run(run_id)["status"] != "paused" and time.monotonic() < deadline:
            time.sleep(.05)
        assert store.run(run_id)["status"] == "paused"
        assert client.post("/api/v1/studio/shutdown", headers=headers).status_code == 200
        deadline = time.monotonic() + 5
        while store.run(run_id)["status"] == "paused" and time.monotonic() < deadline:
            time.sleep(.05)
        assert store.run(run_id)["status"] == "cancelled"
