"""Coordinator acceptance: public history, relocation and committed task truth."""

import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from contract_driven_ai_flow.research.projects.application import ProjectApplication
from contract_driven_ai_flow.research.routes import create_research_app
from contract_driven_ai_flow.research.workbench.models import RunConfiguration, ProbeInstance

TOKEN = "review-boundaries"
HEADERS = {"Authorization": "Bearer " + TOKEN}
PREFIX = "/api/v1/research/projects/"


def setup_project(application, root):
    root.mkdir()
    (root / "main.py").write_text("X=7\nY=X*2\n", encoding="utf-8")
    project = application.open(root)
    revision = application.index(project.id)
    config = application.configuration(project.id)
    application.save_entries(project.id, [RunConfiguration(id="main", name="Main", kind="script", target="main.py")], expected_revision=config.revision)
    return project, revision


@pytest.mark.parametrize("scope", ["replot", "probes"])
def test_public_historical_plan_uses_saved_entry_after_configuration_changes(tmp_path, scope):
    with TestClient(create_research_app(tmp_path / "host", token=TOKEN)) as client:
        app = client.app.state.projects
        project, revision = setup_project(app, tmp_path / "lab")
        plan = app.plan(project.id, "main", revision_id=revision.id)
        task = app.execute(project.id, plan.id)
        done = app.workbench(project.id).jobs.wait(task.id, 40)
        assert done.status == "completed", done.message
        config = app.configuration(project.id)
        app.save_entries(project.id, [], expected_revision=config.revision)
        (tmp_path / "lab/main.py").write_text("X=999\n", encoding="utf-8")
        newer = app.index(project.id)
        assert newer.id != revision.id
        direct = app.plan(project.id, 'main', revision_id=revision.id, scope=scope, run_id=done.run_id)
        assert direct.project_revision_id == revision.id
        response = client.post(PREFIX + project.id + "/plans", headers=HEADERS, json={"configuration_id": "main", "revision_id": revision.id, "scope": scope, "run_id": done.run_id})
        assert response.status_code == 200, response.text
        saved = response.json()
        assert saved["project_revision_id"] == revision.id
        assert saved["run_id"] == done.run_id
        assert saved["entry"]["configuration_id"] == "main"
        result = app.workbench(project.id).jobs.wait(app.execute(project.id, saved["id"]).id, 40)
        assert result.status == "completed", result.message
        assert len(app.research(project.id).store.runs()) == 1


def test_reopening_moved_project_rebinds_cached_stores_and_preserves_history(tmp_path):
    app = ProjectApplication(tmp_path / "host")
    try:
        old_root, new_root = tmp_path / "old", tmp_path / "moved"
        project, revision = setup_project(app, old_root)
        old_workbench = app.workbench(project.id)
        marker = {"value": "retained"}
        old_workbench.store.put("contexts", "relocation-proof", marker)
        old_root.rename(new_root)
        reopened = app.open(new_root)
        fresh = app.workbench(project.id)
        assert reopened.id == project.id
        assert fresh.project_root.resolve() == new_root.resolve()
        assert fresh.store.get("contexts", "relocation-proof") == marker
        assert app.configuration(project.id).run_configurations[0].id == "main"
        assert app.projects.revision(project.id, revision.id).id == revision.id
        assert not old_root.exists(), "opening a moved project must not recreate its old folder"
    finally:
        app.close()


def test_relocation_with_active_job_is_rejected_without_changing_registration(tmp_path):
    app = ProjectApplication(tmp_path / "host")
    entered, release = threading.Event(), threading.Event()
    try:
        old_root, new_root = tmp_path / "active", tmp_path / "moved"
        project, _ = setup_project(app, old_root)
        jobs = app.workbench(project.id).jobs
        task = jobs.submit("review.hold", lambda job, cancel: (entered.set(), release.wait(10), {})[-1])
        assert entered.wait(5)
        old_root.rename(new_root)
        with pytest.raises((ValueError, RuntimeError), match="(?i)(active|running|busy|relocat|move)"):
            app.open(new_root)
        assert Path(app.projects._lookup_root(project.id)).resolve() == old_root.resolve()
        assert app.workbench(project.id).store.path.parent == old_root / '.cdaf/research'
        assert app.research(project.id).store.root == old_root
        # Refusal leaves the active session untouched. Restore the externally
        # moved fixture before allowing its pending durable write to finish.
        new_root.rename(old_root)
        release.set()
        jobs.wait(task.id, 10)
    finally:
        release.set()
        app.close()


def test_cancel_after_change_commit_keeps_real_completion_and_revision_receipt(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    with TestClient(create_research_app(tmp_path / "host", token=TOKEN)) as client:
        app = client.app.state.projects
        project, revision = setup_project(app, tmp_path / "lab")
        base = PREFIX + project.id
        proposed = client.post(base + "/changes", headers=HEADERS, json={"base_revision": revision.id, "edits": [{"path": "main.py", "content": "X=21\nY=X*2\n"}]})
        assert proposed.status_code == 200, proposed.text
        changes = client.app.state.project_changes
        original = changes.accept

        def pause_after_commit(*args, **kwargs):
            result = original(*args, **kwargs)
            entered.set()
            assert release.wait(10)
            return result

        monkeypatch.setattr(changes, "accept", pause_after_commit)
        response = client.post(base + "/changes/" + proposed.json()["id"] + "/accept", headers=HEADERS, json={"expected_revision": revision.id})
        assert response.status_code == 202, response.text
        jobs = app.workbench(project.id).jobs
        try:
            assert entered.wait(5)
            jobs.cancel(response.json()["id"])
        finally:
            release.set()
        done = jobs.wait(response.json()["id"], 20)
        assert done.status == "completed", done.message
        assert done.project_revision_id == app.projects.project(project.id).latest_revision_id
        assert done.receipt["project_revision_id"] == done.project_revision_id
        assert (tmp_path / "lab/main.py").read_text(encoding="utf-8").startswith("X=21")


def test_explicit_evidence_plan_uses_current_probes_and_freezes_them(tmp_path):
    app=ProjectApplication(tmp_path/'host')
    try:
        project,revision=setup_project(app,tmp_path/'lab')
        original=app.plan(project.id,'main',revision_id=revision.id)
        wb=app.workbench(project.id)
        done=wb.jobs.wait(app.execute(project.id,original.id).id,40)
        assert done.status=='completed',done.message
        config=app.configuration(project.id)
        changed=config.model_copy(deep=True,update={'probes':[ProbeInstance(id='new-check',definition_id='check.finite')]})
        wb.configure(changed,expected_revision=config.revision)
        planned=wb._evidence_plan(done.run_id,scope='probes',instance_ids=['new-check'])
        assert [probe.id for probe in planned.config.probes]==['new-check']
        config=app.configuration(project.id)
        wb.configure(config.model_copy(deep=True,update={'probes':[]}),expected_revision=config.revision)
        result=wb.jobs.wait(app.execute(project.id,planned.id).id,40)
        assert result.status=='completed',result.message
        assert any(output['instance_id']=='new-check' for output in wb.outputs(run_id=done.run_id))
        assert all(probe.id!='new-check' for probe in original.config.probes)
        assert len(app.research(project.id).store.runs())==1
    finally:
        app.close()
