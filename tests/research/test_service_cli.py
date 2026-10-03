import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner


def analysis(tmp_path, body="import numpy as np\nX = np.arange(12).reshape(3, 4)\nY = X.mean(axis=0)\n"):
    script = tmp_path / "analysis.py"
    script.write_text(body, encoding="utf-8")
    return script


def wait_for(service, run_id, expected=None, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = service.store.run(run_id)
        if record["status"] in ({expected} if expected else {"completed", "failed", "cancelled", "interrupted", "timeout"}):
            return record
        time.sleep(0.02)
    pytest.fail(f"Run {run_id} did not reach expected state: {service.store.run(run_id)}")


def test_cli_and_http_share_snapshot_semantics(tmp_path):
    from contract_driven_ai_flow.cli import app
    from contract_driven_ai_flow.research.routes import create_research_app

    script = analysis(tmp_path)
    result = CliRunner().invoke(app, ["--json", "observe", str(script), "--project", str(tmp_path)])
    assert result.exit_code == 0, result.output
    observed_run = json.loads(result.stdout)
    with TestClient(create_research_app(tmp_path, token="test-session")) as client:
        headers = {"Authorization": "Bearer test-session"}
        page = client.get(f"/api/v1/research/runs/{observed_run['id']}/snapshots", headers=headers)
        assert page.status_code == 200
        x = next(s for s in page.json() if s["name"] == "X")
        assert x["descriptor"]["shape"] == [3, 4]
        assert x["sample"]["values"][0] == [0, 1, 2, 3]
        inspected = CliRunner().invoke(app, ["--json", "research", "inspect", x["id"], "--project", str(tmp_path)])
        assert inspected.exit_code == 0
        assert json.loads(inspected.stdout) == x


def test_stream_resumes_without_duplicate_events(tmp_path):
    from contract_driven_ai_flow.research.routes import create_research_app
    from contract_driven_ai_flow.research.service import ResearchService

    with ResearchService(tmp_path) as service:
        handle = service.start_analysis(analysis(tmp_path), interpreter=Path(sys.executable))
        wait_for(service, handle.run_id)
        events = service.events(handle.run_id, limit=10000)
    with TestClient(create_research_app(tmp_path, token="s")) as client:
        headers = {"Authorization": "Bearer s", "Last-Event-ID": str(events[2]["sequence"])}
        response = client.get(f"/api/v1/research/runs/{handle.run_id}/events", headers=headers)
        ids = [int(line[4:]) for line in response.text.splitlines() if line.startswith("id: ")]
    assert ids == [e["sequence"] for e in events[3:]]
    assert len(ids) == len(set(ids))


def test_selected_interpreter_is_used(tmp_path):
    from contract_driven_ai_flow.research.service import ResearchService

    with ResearchService(tmp_path) as service:
        handle = service.start_analysis(analysis(tmp_path, "import sys\nexecutable = sys.executable\nX = 7\n"), interpreter=Path(sys.executable))
        record = wait_for(service, handle.run_id)
    assert Path(record["environment"]["executable"]).resolve() == Path(sys.executable).resolve()
    assert record["status"] == "completed"


def test_missing_history_slice_is_unavailable(tmp_path):
    from contract_driven_ai_flow.research.service import ResearchService

    with ResearchService(tmp_path) as service:
        handle = service.start_analysis(analysis(tmp_path), interpreter=Path(sys.executable))
        wait_for(service, handle.run_id)
        x = next(s for s in service.store.snapshots(handle.run_id) if s.name == "X")
        region = service.slice(x.id, [])
    assert region["available"] is False and region["snapshot_id"] == x.id


def test_viewer_disconnect_does_not_block_analysis(tmp_path):
    from contract_driven_ai_flow.research.service import ResearchService

    with ResearchService(tmp_path) as service:
        handle = service.start_analysis(analysis(tmp_path, "import numpy as np\nfor i in range(100):\n    X = np.ones(4) * i\n"), interpreter=Path(sys.executable))
        # No event subscriber exists; persistence and scientific computation proceed.
        record = wait_for(service, handle.run_id)
        last = next(s for s in service.store.snapshots(handle.run_id) if s.name == "X")
    assert record["status"] == "completed" and last.sample["values"] == [[99.0] * 4]


def test_cancel_flushes_terminal_state(tmp_path):
    from contract_driven_ai_flow.research.service import ResearchService

    with ResearchService(tmp_path) as service:
        handle = service.start_analysis(analysis(tmp_path, "import time\nX = 1\nwhile True:\n    time.sleep(0.1)\n    X += 1\n"), interpreter=Path(sys.executable))
        wait_for(service, handle.run_id, expected="running")
        service.cancel(handle.run_id)
        record = wait_for(service, handle.run_id)
        terminal = [e for e in service.events(handle.run_id, limit=10000) if e["kind"] == "run.finished"]
    assert record["status"] == "cancelled"
    assert len(terminal) == 1 and terminal[0]["payload"]["status"] == "cancelled"


def test_agent_runs_without_application_libraries_in_selected_environment(tmp_path):
    import subprocess
    from contract_driven_ai_flow.research.service import ResearchService

    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(tmp_path / "scientific-env")], check=True, capture_output=True)
    interpreter = tmp_path / "scientific-env" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    script = analysis(tmp_path, "import sys\nassert 'fastapi' not in sys.modules\nassert 'pydantic' not in sys.modules\nX = 42\n")
    with ResearchService(tmp_path) as service:
        handle = service.start_analysis(script, interpreter=interpreter)
        record = wait_for(service, handle.run_id)
    assert record["status"] == "completed"


def test_boundary_gate_pauses_until_explicit_resume(tmp_path):
    from contract_driven_ai_flow.research.models import ProbeSpec
    from contract_driven_ai_flow.research.service import ResearchService

    script = analysis(tmp_path, "import numpy as np\nfrom pathlib import Path\nX = np.array([np.nan])\nPath('after-gate.txt').write_text('reached')\n")
    with ResearchService(tmp_path) as service:
        handle = service.start_analysis(script, interpreter=Path(sys.executable), probes=[ProbeSpec(id="gate", binding="X", policy="pause")])
        wait_for(service, handle.run_id, expected="paused")
        assert not (tmp_path / "after-gate.txt").exists()
        service.resume(handle.run_id)
        record = wait_for(service, handle.run_id)
    assert record["status"] == "completed"
    assert (tmp_path / "after-gate.txt").read_text() == "reached"


def test_process_crash_leaves_explainable_terminal_evidence(tmp_path):
    from contract_driven_ai_flow.research.service import ResearchService

    with ResearchService(tmp_path) as service:
        handle = service.start_analysis(analysis(tmp_path, "import os\nX = 3\nos._exit(17)\n"), interpreter=Path(sys.executable))
        record = wait_for(service, handle.run_id)
    assert record["status"] == "failed" and record["summary"]["exit_code"] == 17


def test_raw_stdout_never_corrupts_events_or_leaks_into_history(tmp_path):
    from contract_driven_ai_flow.research.service import ResearchService

    with ResearchService(tmp_path) as service:
        handle = service.start_analysis(analysis(tmp_path, "import os\nprint('person@example.org')\nos.write(1, b'raw output\\n')\nX = 5\n"), interpreter=Path(sys.executable))
        record = wait_for(service, handle.run_id)
        encoded = json.dumps(service.events(handle.run_id, limit=10000))
    assert record["status"] == "completed" and "person@example.org" not in encoded and "raw output" not in encoded


def test_research_api_obeys_local_session_and_origin_boundaries(tmp_path):
    from contract_driven_ai_flow.research.routes import create_research_app

    with TestClient(create_research_app(tmp_path, token="s")) as client:
        assert client.get("/api/v1/research/runs").status_code == 401
        assert client.get("/api/v1/research/runs", headers={"Authorization": "Bearer s", "Origin": "https://example.org"}).status_code == 403


def test_invalid_interpreter_has_usage_exit_code(tmp_path):
    from contract_driven_ai_flow.cli import app

    result = CliRunner().invoke(app, ["--json", "observe", str(analysis(tmp_path)), "--python", str(tmp_path / "missing-python")])
    assert result.exit_code == 2


def test_installed_agent_does_not_expose_tool_site_packages(tmp_path, monkeypatch):
    import os
    import shutil
    import subprocess
    from contract_driven_ai_flow.research import runners
    from contract_driven_ai_flow.research.service import ResearchService

    # A normal wheel lives beside web dependencies, unlike an editable src tree.
    tool_site = tmp_path / "tool-site-packages"
    package = tool_site / "contract_driven_ai_flow"
    shutil.copytree(Path(runners.__file__).parents[1], package,
                    ignore=shutil.ignore_patterns("static", "templates", "__pycache__"))
    (tool_site / "tool_only_web_dependency.py").write_text("VALUE = 1\n")
    monkeypatch.setattr(runners, "__file__", str(package / "research/runners.py"))
    scientific_env = tmp_path / "scientific-env"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(scientific_env)],
                   check=True, capture_output=True)
    interpreter = scientific_env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    source = analysis(tmp_path, "import importlib.util\nassert importlib.util.find_spec('tool_only_web_dependency') is None\nX = 42\n")
    with ResearchService(tmp_path / "evidence") as service:
        handle = service.start_analysis(source, interpreter=interpreter)
        record = wait_for(service, handle.run_id)
    assert record["status"] == "completed", record["summary"]
