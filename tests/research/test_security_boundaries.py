"""Local peers do not receive an operator's execution or collector authority."""
import json
import os
from pathlib import Path
import socket
import subprocess

import pytest


@pytest.mark.parametrize("payload", [b"[]\n", b"null\n", b'{"token":4}\n', None])
def test_rejected_or_stalled_peer_does_not_kill_the_real_agent(tmp_path, payload):
    from contract_driven_ai_flow.research.runners import PythonRunner, RunnerRegistry
    from contract_driven_ai_flow.research.service import ResearchService

    class PeerFirstRunner(PythonRunner):
        backend = "test.peer-first"

        def launch(self, job, job_file):
            self.peer = socket.create_connection(("127.0.0.1", job["port"]), timeout=3)
            if payload is not None:
                self.peer.sendall(payload)
            return super().launch(job, job_file)

    runner = PeerFirstRunner()
    registry = RunnerRegistry()
    registry.register(runner)
    script = tmp_path / "analysis.py"
    script.write_text("X = 42\n", encoding="utf-8")
    try:
        with ResearchService(tmp_path, runner_registry=registry) as service:
            record = service.wait(service.start_analysis(script, runner=runner.backend).run_id, 15)
            assert record["status"] == "completed", record["summary"]
            assert record["summary"]["observer_error"] is None
            value = next(v for v in service.store.snapshots(record["id"]) if v.name == "X")
            assert value.sample["values"] == [[42]]
    finally:
        runner.peer.close()


def assert_private(path):
    if os.name == "nt":
        # Query real effective trustees without reading capability bytes.
        script = "$ErrorActionPreference='Stop'; $taskAllowed=@(([Security.Principal.WindowsIdentity]::GetCurrent()).User.Value,'S-1-5-18'); "
        script += "$taskRules=(Get-Acl -LiteralPath $env:CDAF_ACL_TEST_PATH).Access; foreach($taskRule in $taskRules){ "
        script += "if($taskRule.AccessControlType -eq 'Allow' -and $taskRule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -notin $taskAllowed){exit 1} }; exit 0"
        env = {**os.environ, "CDAF_ACL_TEST_PATH": str(path), "PSModulePath": str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/Modules")}
        check = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], env=env,
            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
        assert check.returncode == 0, "Capability must only grant access to its owner and SYSTEM"
    else:
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700


def test_finished_agent_evidence_is_drained_from_pending_connection(tmp_path):
    from contract_driven_ai_flow.research.runners import PythonRunner, RunnerRegistry
    from contract_driven_ai_flow.research.service import ResearchService

    class FinishedBeforeCollector(PythonRunner):
        backend = "test.finished-before-collector"

        def launch(self, job, job_file):
            # A short-lived independent runner may finish before collection.
            # Execute the actual selected script and publish its scalar via TCP.
            source = """import json,socket,sys,time
from pathlib import Path
job=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
scope={}
exec(compile(Path(job['script']).read_text(encoding='utf-8'),job['script'],'exec'),scope)
snapshot={'id':'finished-X','run_id':job['run_id'],'binding_id':'X','name':'X','version':1,
 'scope_id':'main','descriptor':{'kind':'scalar','backend':'python','type_name':'int'},'sample':{'values':[[scope['X']]]}}
events=[{'run_id':job['run_id'],'kind':'value.observed','snapshot_id':'finished-X','payload':{'snapshot':snapshot}},
 {'run_id':job['run_id'],'kind':'run.finished','payload':{'status':'completed'}}]
with socket.create_connection(('127.0.0.1',job['port']),timeout=3) as channel:
 hello={'type':'hello','protocol_version':1,'run_id':job['run_id'],'token':job['token']}
 channel.sendall((json.dumps(hello)+'\\n'+json.dumps({'type':'events','events':events})+'\\n').encode())
time.sleep(.1)
"""
            process = subprocess.Popen([job["interpreter"], "-X", "utf8", "-c", source, str(job_file)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return process

    class DelayedCollector(ResearchService):
        def _supervise(self, active):
            # The OS process group is established normally; only collection is
            # delayed until this real independent producer has exited.
            assert active.process.wait(timeout=10) == 0
            super()._supervise(active)

    registry = RunnerRegistry()
    registry.register(FinishedBeforeCollector())
    script = tmp_path / "analysis.py"
    script.write_text("X = 42\n", encoding="utf-8")
    with DelayedCollector(tmp_path, runner_registry=registry) as service:
        record = service.wait(service.start_analysis(script, runner="test.finished-before-collector").run_id, 10)
        values = service.store.snapshots(record["id"])
    assert record["status"] == "completed"
    assert any(value.name == "X" and value.sample["values"] == [[42]] for value in values), record['summary']


def test_capability_writer_is_private_before_and_after_replacement(tmp_path):
    from contract_driven_ai_flow.storage import atomic_write_private

    root = tmp_path / "readable-project"
    root.mkdir()
    if os.name == "nt":
        subprocess.run(["icacls.exe", str(root), "/grant", "*S-1-1-0:(OI)(CI)(R)"],
            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=15, check=True)
    old_umask = os.umask(0)
    try:
        path = root / ".cdaf/studio.json"
        atomic_write_private(path, '{"token":"synthetic-first"}')
        assert_private(path)
        atomic_write_private(path, '{"token":"synthetic-second"}')
        assert_private(path)
        assert json.loads(path.read_text())["token"] == "synthetic-second"
        assert not list(path.parent.glob("*.tmp"))
    finally:
        os.umask(old_umask)


def test_studio_and_windowless_launcher_use_private_capability_files(tmp_path, monkeypatch):
    from contract_driven_ai_flow import launcher, studio
    import uvicorn

    if os.name == "nt":
        subprocess.run(["icacls.exe", str(tmp_path), "/grant", "*S-1-1-0:(OI)(CI)(R)"],
            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=15, check=True)
    checked = []

    def run(server):
        assert_private(tmp_path / ".cdaf/studio.json")
        checked.append("studio")

    monkeypatch.setattr(uvicorn.Server, "run", run)
    studio.serve(tmp_path, managed=True, token="synthetic-live-session")
    monkeypatch.setattr(launcher, "start", lambda *a, **kw: {"url": "http://127.0.0.1:1234/#session=synthetic", "pid": 1})
    monkeypatch.setattr("sys.argv", ["cdaf-studio", "--home", str(tmp_path), "--no-open"])
    launcher.main()
    assert_private(tmp_path / ".cdaf/launcher.json")
    assert checked == ["studio"]


def test_fixture_session_requires_private_runtime_configuration(monkeypatch):
    from scripts.browser_session import fixture_session

    monkeypatch.delenv("CDAF_BROWSER_TEST_SESSION", raising=False)
    with pytest.raises(ValueError):
        fixture_session()
    monkeypatch.setenv("CDAF_BROWSER_TEST_SESSION", "browser-test-session")
    with pytest.raises(ValueError):
        fixture_session()
    monkeypatch.setenv("CDAF_BROWSER_TEST_SESSION", "a" * 43)
    assert fixture_session() == "a" * 43
