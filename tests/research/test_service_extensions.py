import json
import os
import sys
from pathlib import Path

from typer.testing import CliRunner


def test_startup_recovers_dead_owners_without_touching_live_analyses(tmp_path):
    from contract_driven_ai_flow.research.service import ResearchService
    from contract_driven_ai_flow.research.store import ExperimentStore

    store = ExperimentStore(tmp_path)
    dead = store.create_run("old.py", interpreter=sys.executable, source_digest="old")
    live = store.create_run("live.py", interpreter=sys.executable, source_digest="live")
    with store.connect() as db:
        db.execute("UPDATE runs SET owner=? WHERE id=?", (2147483647, dead["id"]))
    with ResearchService(tmp_path):
        assert store.run(dead["id"])["status"] == "interrupted"
        assert store.run(dead["id"])["summary"]["reason"] == "owner_process_exited"
        assert store.run(live["id"])["status"] == "queued"
    assert len([e for e in store.events(dead["id"]) if e.kind == "run.finished"]) == 1


def test_artifact_retention_preserves_history_active_runs_and_user_files(tmp_path):
    from contract_driven_ai_flow.research.models import ObservationEvent, SnapshotRef, ValueDescriptor
    from contract_driven_ai_flow.research.store import ExperimentStore

    store = ExperimentStore(tmp_path)
    old = store.create_run("old.py", interpreter=sys.executable, source_digest="old")
    live = store.create_run("live.py", interpreter=sys.executable, source_digest="live")
    store.append([ObservationEvent(run_id=old["id"], kind="run.finished", payload={"status": "completed"})])
    with store.connect() as db:
        db.execute("UPDATE runs SET finished='2020-01-01T00:00:00+00:00' WHERE id=?", (old["id"],))
    directory = store.state / "artifacts"
    directory.mkdir()
    for identifier in (old["id"], live["id"]):
        reference = "artifacts/" + identifier + ".npy"
        (store.state / reference).write_bytes(b"evidence")
        snapshot = SnapshotRef(id=identifier, run_id=identifier, binding_id="X", scope_id="main", name="X", version=1,
            descriptor=ValueDescriptor(kind="matrix", backend="numpy", type_name="ndarray"), artifact_ref=reference)
        store.append([ObservationEvent(run_id=identifier, kind="value.observed", snapshot_id=identifier,
            payload={"snapshot": snapshot.model_dump(mode="json")})])
    user_file = tmp_path / "analysis.py"
    user_file.write_text("X = 1\n")
    result = store.expire_artifacts(days=7)
    assert result["artifacts_deleted"] == 1
    assert not (directory / (old["id"] + ".npy")).exists()
    assert (directory / (live["id"] + ".npy")).exists()
    assert store.run(old["id"])["status"] == "completed" and store.events(old["id"])
    assert user_file.read_text() == "X = 1\n"


def test_selected_environment_dependency_versions_are_recorded(tmp_path):
    from contract_driven_ai_flow.research.service import ResearchService
    import numpy

    script = tmp_path / "analysis.py"
    script.write_text("import numpy as np\nX = np.ones(4)\n")
    with ResearchService(tmp_path) as service:
        run = service.wait(service.start_analysis(script).run_id, 10)
    assert run["environment"]["dependencies"]["numpy"] == numpy.__version__


def test_entrypoint_adapter_is_an_explicit_cli_opt_in(tmp_path):
    from contract_driven_ai_flow.cli import app
    from contract_driven_ai_flow.research.store import ExperimentStore

    module = tmp_path / "pointcloud_plugin.py"
    example = Path(__file__).parents[2] / "examples/research/custom-adapter.py"
    module.write_text(example.read_text(), encoding="utf-8")
    distribution = tmp_path / "pointcloud_fixture-1.0.dist-info"
    distribution.mkdir()
    (distribution / "METADATA").write_text("Name: pointcloud-fixture\nVersion: 1.0\n")
    (distribution / "entry_points.txt").write_text("[cdaf.research.adapters]\npointcloud-fixture = pointcloud_plugin:PointCloudAdapter\n")
    script = tmp_path / "analysis.py"
    script.write_text("from pointcloud_plugin import PointCloud\npoints = PointCloud(((1.0, 2.0), (3.0, 4.0)))\n")
    runner = CliRunner()
    first = runner.invoke(app, ["--json", "observe", str(script), "--project", str(tmp_path)])
    assert first.exit_code == 0, first.output
    first_id = json.loads(first.stdout)["id"]
    second = runner.invoke(app, ["--json", "observe", str(script), "--project", str(tmp_path), "--adapter", "pointcloud-fixture"])
    assert second.exit_code == 0, second.output
    store = ExperimentStore(tmp_path)
    original = next(s for s in store.snapshots(first_id) if s.name == "points")
    registered = next(s for s in store.snapshots(json.loads(second.stdout)["id"]) if s.name == "points")
    assert original.descriptor.backend == "unknown" and original.sample == {}
    assert registered.descriptor.backend == "example.pointcloud"
    assert registered.sample["values"] == [[1.0, 2.0], [3.0, 4.0]]


def test_snapshot_pagination_is_complete_and_version_stable(tmp_path):
    from contract_driven_ai_flow.research.models import ObservationEvent, SnapshotRef, ValueDescriptor
    from contract_driven_ai_flow.research.store import ExperimentStore

    store = ExperimentStore(tmp_path)
    run = store.create_run("analysis.py", interpreter=sys.executable, source_digest="a")
    for i in range(7):
        snapshot = SnapshotRef(id=str(i), run_id=run["id"], binding_id="X", name="X", scope_id="main", version=i+1,
            descriptor=ValueDescriptor(kind="scalar", backend="python", type_name="int"))
        store.append([ObservationEvent(run_id=run["id"], kind="value.observed", snapshot_id=snapshot.id, payload={"snapshot": snapshot.model_dump(mode="json")})])
    first = store.snapshots(run["id"], latest=False, limit=3)
    second = store.snapshots(run["id"], latest=False, limit=3, after=first[-1].id)
    tail = store.snapshots(run["id"], latest=False, limit=3, after=second[-1].id)
    assert [s.version for s in [*first, *second, *tail]] == list(range(1, 8))


def test_runner_plugin_reuses_the_same_evidence_protocol(tmp_path):
    from contract_driven_ai_flow.research.runners import RunnerRegistry, PythonRunner
    from contract_driven_ai_flow.research.service import ResearchService

    class CustomRunner(PythonRunner):
        backend = "example.research-python"
        launched = False

        def launch(self, job, job_file):
            self.launched = True
            return super().launch(job, job_file)

    plugin = CustomRunner()
    registry = RunnerRegistry()
    registry.register(plugin)
    script = tmp_path / "analysis.py"
    script.write_text("X = 42\n")
    with ResearchService(tmp_path, runner_registry=registry) as service:
        run = service.wait(service.start_analysis(script, runner=plugin.backend).run_id, 10)
        snapshot = next(s for s in service.store.snapshots(run["id"]) if s.name == "X")
    assert plugin.launched and run["status"] == "completed"
    assert snapshot.sample["values"] == [[42]]


def test_existing_workspace_exposes_the_same_scientific_service(tmp_path):
    from fastapi.testclient import TestClient
    from contract_driven_ai_flow.workspace import create_workspace_app

    with TestClient(create_workspace_app(tmp_path, token="test")) as client:
        response = client.get("/api/v1/research/runs", headers={"Authorization": "Bearer test"})
    assert response.status_code == 200 and response.json() == []
