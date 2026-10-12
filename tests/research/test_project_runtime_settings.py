"""Own CI tests: private machine runtime profiles and exact frozen references.

Covers the runtime settings API (auth, optimistic revision, validation), named
environment sets with deterministic merging, legacy compatibility, per-project
environment isolation, freeze-at-plan semantics and privacy of public output.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from contract_driven_ai_flow.research.projects import local_runtime
from contract_driven_ai_flow.research.projects.application import ProjectApplication
from contract_driven_ai_flow.research.routes import create_research_app
from contract_driven_ai_flow.research.workbench.models import RunConfiguration

TOKEN = "runtime-token"
HEADERS = {"Authorization": "Bearer " + TOKEN}
BASE = "/api/v1/research/runtime"
PYTHON = sys.executable


def client(tmp_path):
    return TestClient(create_research_app(tmp_path / "host", token=TOKEN))


def script(root: Path, text: str = "X=1\n") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "main.py").write_text(text, encoding="utf-8")


def prepare(app, root, *, environment=()):
    script(root)
    project = app.open(root)
    revision = app.index(project.id)
    config = app.configuration(project.id)
    app.save_entries(
        project.id,
        [
            RunConfiguration(
                id="main",
                name="Main",
                target="main.py",
                environment=list(environment),
            )
        ],
        expected_revision=config.revision,
    )
    plan = app.plan(project.id, "main", revision_id=revision.id)
    return project, plan


def run(app, project, plan, timeout=30):
    task = app.execute(project.id, plan.id)
    return app.workbench(project.id).jobs.wait(task.id, timeout)


def test_runtime_api_auth_revision_and_validation(tmp_path):
    with client(tmp_path) as c:
        assert c.get(BASE).status_code == 401
        initial = c.get(BASE, headers=HEADERS)
        assert initial.status_code == 200, initial.text
        assert initial.json() == {
            "revision": 0,
            "interpreters": [],
            "environments": [],
            "legacy_environment": [],
        }
        revision = initial.json()["revision"]
        # A malformed reference, a relative path and a missing file are refused.
        assert (
            c.put(
                BASE + "/interpreters/bad ref",
                headers=HEADERS,
                json={"expected_revision": revision, "path": PYTHON},
            ).status_code
            == 422
        )
        assert (
            c.put(
                BASE + "/interpreters/ok",
                headers=HEADERS,
                json={"expected_revision": revision, "path": "python"},
            ).status_code
            == 422
        )
        assert (
            c.put(
                BASE + "/interpreters/ok",
                headers=HEADERS,
                json={"expected_revision": revision, "path": str(tmp_path / "nope")},
            ).status_code
            == 422
        )
        good = c.put(
            BASE + "/interpreters/ok",
            headers=HEADERS,
            json={"expected_revision": revision, "path": PYTHON},
        )
        assert good.status_code == 200, good.text
        assert good.json()["revision"] > revision
        assert PYTHON not in good.text
        # A stale optimistic revision is a conflict.
        assert (
            c.put(
                BASE + "/interpreters/ok",
                headers=HEADERS,
                json={"expected_revision": revision, "path": PYTHON},
            ).status_code
            == 409
        )
        current = c.get(BASE, headers=HEADERS).json()["revision"]
        assert (
            c.put(
                BASE + "/environments/exp",
                headers=HEADERS,
                json={"expected_revision": current, "values": {"1BAD": "x"}},
            ).status_code
            == 422
        )
        assert (
            c.put(
                BASE + "/environments/exp",
                headers=HEADERS,
                json={"expected_revision": current, "values": {"OK": "a\x00b"}},
            ).status_code
            == 422
        )
        saved = c.put(
            BASE + "/environments/exp",
            headers=HEADERS,
            json={"expected_revision": current, "values": {"LAB_VALUE": "secret"}},
        )
        assert saved.status_code == 200, saved.text
        state = saved.json()
        assert "secret" not in saved.text
        assert {item["id"] for item in state["environments"]} == {"exp"}
        assert state["environments"][0]["keys"] == ["LAB_VALUE"]


def test_environment_resolution_merge_conflicts_and_legacy(tmp_path):
    host = tmp_path / "host"
    local_runtime.save_machine_settings(
        host,
        {
            "version": 5,
            "interpreters": {"keep": PYTHON},
            "environment": {"LEGACY_VAR": "legacy", "ambig": "one"},
            "environments": {
                "exp-A": {"PYTHONPATH": "/a", "SHARED": "same"},
                "exp-B": {"PYTHONPATH": "/b", "SHARED": "same"},
                "ambig": {"X": "profile"},
            },
        },
    )
    assert local_runtime.resolve_environment(host, ["exp-A"]) == {
        "PYTHONPATH": "/a",
        "SHARED": "same",
    }
    assert local_runtime.resolve_environment(host, ["exp-B", "LEGACY_VAR"]) == {
        "PYTHONPATH": "/b",
        "SHARED": "same",
        "LEGACY_VAR": "legacy",
    }
    # Conflicting duplicate values are an explicit error, never an override.
    with pytest.raises(ValueError, match="Conflicting"):
        local_runtime.resolve_environment(host, ["exp-A", "exp-B"])
    with pytest.raises(ValueError, match="Conflicting"):
        local_runtime.resolve_environment(host, ["exp-B", "exp-A"])
    with pytest.raises(ValueError, match="Unknown"):
        local_runtime.resolve_environment(host, ["missing"])
    with pytest.raises(ValueError, match="Ambiguous"):
        local_runtime.resolve_environment(host, ["ambig"])
    # Unrelated keys and the machine version survive profile writes.
    state = local_runtime.runtime_state(host)
    assert state["revision"] == 5
    assert state["legacy_environment"] == ["LEGACY_VAR", "ambig"]


def test_enroll_interpreter_is_stable_and_private(tmp_path):
    host = tmp_path / "host"
    assert local_runtime.enroll_interpreter(host, "chosen", PYTHON) == "chosen"
    assert local_runtime.resolve_interpreter(host, "chosen") == PYTHON
    legacy = local_runtime.legacy_interpreter_ref(PYTHON)
    assert legacy == local_runtime.legacy_interpreter_ref(PYTHON)
    assert local_runtime.enroll_interpreter(host, legacy, PYTHON) == legacy
    assert local_runtime.resolve_interpreter(host, legacy) == PYTHON
    # A blank reference defaults to the host interpreter (no config path).
    assert local_runtime.resolve_interpreter(host, "") == PYTHON
    state = local_runtime.runtime_state(host)
    assert {item["id"] for item in state["interpreters"]} == {"chosen", legacy}
    assert PYTHON not in str(state)


def test_unknown_environment_reference_fails_planning(tmp_path):
    app = ProjectApplication(tmp_path / "host")
    try:
        with pytest.raises(ValueError, match="Unknown environment"):
            prepare(app, tmp_path / "lab", environment=["nope"])
    finally:
        app.close()


def test_two_projects_choose_distinct_environment_sets(tmp_path):
    with client(tmp_path) as c:
        app = c.app.state.projects
        revision = c.get(BASE, headers=HEADERS).json()["revision"]
        for profile, value in (("experiment-A", "314159"), ("experiment-B", "271828")):
            revision = c.get(BASE, headers=HEADERS).json()["revision"]
            saved = c.put(
                BASE + "/environments/" + profile,
                headers=HEADERS,
                json={"expected_revision": revision, "values": {"LAB_VALUE": value}},
            )
            assert saved.status_code == 200, saved.text
        text = 'import os\nVALUE=int(os.environ["LAB_VALUE"])\n'
        observed = {}
        for name, profile in (("a", "experiment-A"), ("b", "experiment-B")):
            root = tmp_path / ("lab-" + name)
            root.mkdir()
            script(root, text)
            project = app.open(root)
            revision = app.index(project.id)
            config = app.configuration(project.id)
            app.save_entries(
                project.id,
                [
                    RunConfiguration(
                        id="main",
                        name="Main",
                        target="main.py",
                        environment=[profile],
                    )
                ],
                expected_revision=config.revision,
            )
            plan = app.plan(project.id, "main", revision_id=revision.id)
            public = plan.model_dump_json()
            assert "314159" not in public and "271828" not in public
            done = run(app, project, plan)
            assert done.status == "completed", done.message
            snapshots = app.research(project.id).store.snapshots(
                done.run_id, limit=1000
            )
            observed[name] = next(s for s in snapshots if s.name == "VALUE").sample[
                "value"
            ]
        assert observed == {"a": 314159, "b": 271828}


def test_selected_profile_change_blocks_but_unrelated_change_allowed(tmp_path):
    with client(tmp_path) as c:
        app = c.app.state.projects
        revision = c.get(BASE, headers=HEADERS).json()["revision"]
        c.put(
            BASE + "/environments/experiment-A",
            headers=HEADERS,
            json={"expected_revision": revision, "values": {"LAB_VALUE": "1"}},
        )
        revision = c.get(BASE, headers=HEADERS).json()["revision"]
        c.put(
            BASE + "/environments/experiment-B",
            headers=HEADERS,
            json={"expected_revision": revision, "values": {"OTHER": "x"}},
        )
        root = tmp_path / "lab"
        root.mkdir()
        script(root, text='import os\nVALUE=int(os.environ["LAB_VALUE"])\n')
        project = app.open(root)
        project_revision = app.index(project.id)
        config = app.configuration(project.id)
        app.save_entries(
            project.id,
            [
                RunConfiguration(
                    id="main",
                    name="Main",
                    target="main.py",
                    environment=["experiment-A"],
                )
            ],
            expected_revision=config.revision,
        )
        first = app.plan(project.id, "main", revision_id=project_revision.id)
        revision = c.get(BASE, headers=HEADERS).json()["revision"]
        assert (
            c.put(
                BASE + "/environments/experiment-B",
                headers=HEADERS,
                json={"expected_revision": revision, "values": {"OTHER": "y"}},
            ).status_code
            == 200
        )
        assert run(app, project, first).status == "completed"
        second = app.plan(project.id, "main", revision_id=project_revision.id)
        revision = c.get(BASE, headers=HEADERS).json()["revision"]
        assert (
            c.put(
                BASE + "/environments/experiment-A",
                headers=HEADERS,
                json={"expected_revision": revision, "values": {"LAB_VALUE": "2"}},
            ).status_code
            == 200
        )
        with pytest.raises((RuntimeError, ValueError), match="[Rr]untime|[Ee]nvironment"):
            app.execute(project.id, second.id)
        assert len(app.research(project.id).store.runs()) == 1


def test_frozen_interpreter_change_blocks_before_launch(tmp_path):
    app = ProjectApplication(tmp_path / "host")
    try:
        root = tmp_path / "lab"
        script(root)
        local_runtime.enroll_interpreter(app.host_root, "chosen", PYTHON)
        project = app.open(root)
        revision = app.index(project.id)
        config = app.configuration(project.id)
        app.save_entries(
            project.id,
            [
                RunConfiguration(
                    id="main", name="Main", target="main.py", interpreter_ref="chosen"
                )
            ],
            expected_revision=config.revision,
        )
        plan = app.plan(project.id, "main", revision_id=revision.id)
        assert "runtime_snapshot_id" in (plan.entry or {})
        assert PYTHON not in plan.model_dump_json()
        alternate = str(Path(sys.base_prefix) / "python.exe")
        assert alternate != PYTHON and Path(alternate).is_file()
        local_runtime.enroll_interpreter(app.host_root, "chosen", alternate)
        with pytest.raises((RuntimeError, ValueError), match="[Rr]untime|[Ii]nterpreter"):
            app.execute(project.id, plan.id)
        assert not app.research(project.id).store.runs()
    finally:
        app.close()

import hashlib

def test_public_snapshot_reference_is_not_a_hash_of_private_values(tmp_path):
    local_runtime.save_machine_settings(tmp_path, {"environments": {"lab": {"LAB_SECRET": "314159"}}})
    key = local_runtime.freeze_runtime(tmp_path, project_id="p", plan_id="plan", interpreter_ref="", environment_names=["lab"])
    private = local_runtime._snapshot_path(tmp_path, key).read_bytes()
    assert key != hashlib.sha256(private).hexdigest()[:32], "Public IDs must not encode private runtime values"

def test_disappeared_selected_reference_requires_replanning(tmp_path):
    local_runtime.save_machine_settings(tmp_path, {"interpreters": {"chosen": sys.executable}})
    key = local_runtime.freeze_runtime(tmp_path, project_id="p", plan_id="plan", interpreter_ref="chosen", environment_names=[])
    local_runtime.save_machine_settings(tmp_path, {"interpreters": {}})
    with pytest.raises(local_runtime.RuntimeConflict):
        local_runtime.verify_runtime_snapshot(tmp_path, key, project_id="p", plan_id="plan")
