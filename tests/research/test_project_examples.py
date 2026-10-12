"""Own acceptance for the multifile research examples in ``examples/research/projects``.

Every fixture is copied into an isolated temporary directory first: the checked-in
examples are never run in place and never written to. Native subprocess results are
compared against the project workbench's observed snapshots, and the failure path is
verified to be a real error inside ``compute.py`` rather than an observer assertion.

The subprocess launches preserve ``PYTHONDONTWRITEBYTECODE`` so importing a project
never leaves ``__pycache__`` behind.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from contract_driven_ai_flow.research.projects.application import ProjectApplication
from contract_driven_ai_flow.research.workbench.models import RunConfiguration

EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "research" / "projects"
MAX_FIXTURE_LINES = 100
TIMEOUT = 30


def _copy_example(tmp_path, name):
    root = tmp_path / name
    shutil.copytree(
        EXAMPLES / name,
        root,
        ignore=shutil.ignore_patterns("__pycache__", ".cdaf"),
    )
    return root


def _run_native(root, kind, target, args=(), environment=None):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    if environment:
        env.update({key: str(value) for key, value in environment.items()})
    command = [sys.executable, "-B", "-X", "utf8"]
    command += ["-m", target] if kind == "module" else [target]
    command += list(args)
    return subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=TIMEOUT)


def _run_observed(tmp_path, root, kind, target, args=(), environment=None):
    environment = environment or {}
    host = tmp_path / ("host-" + target.replace(".", "-"))
    if environment:
        private = host / ".cdaf/runtime.json"
        private.parent.mkdir(parents=True, exist_ok=True)
        private.write_text(
            json.dumps({"environment": {key: str(value) for key, value in environment.items()}}),
            encoding="utf-8",
        )
    app = ProjectApplication(host)
    try:
        project = app.open(root)
        revision = app.index(project.id)
        config = app.configuration(project.id)
        app.save_entries(
            project.id,
            [
                RunConfiguration(
                    id="demo",
                    name="Demo",
                    kind=kind,
                    target=target,
                    arguments=list(args),
                    environment=list(environment),
                )
            ],
            expected_revision=config.revision,
        )
        plan = app.plan(project.id, "demo", revision_id=revision.id)
        task = app.execute(project.id, plan.id)
        done = app.workbench(project.id).jobs.wait(task.id, TIMEOUT)
        run = app.research(project.id).store.run(done.run_id)
        snapshots = app.research(project.id).store.snapshots(done.run_id, limit=1000)
        return done, run, snapshots
    finally:
        app.close()


def _text(raw):
    return raw.decode("utf-8", errors="replace")


def test_flat_lab_native_and_observed_scores_agree(tmp_path):
    root = _copy_example(tmp_path, "flat-lab")
    native = _run_native(root, "script", "main.py")
    assert native.returncode == 0, _text(native.stderr)

    done, run, snapshots = _run_observed(tmp_path, root, "script", "main.py")
    assert done.status == "completed", done.message
    assert run["status"] == "completed"

    score = next(s for s in reversed(snapshots) if s.name == "score")
    assert str(score.sample["value"]) in _text(native.stdout)

    # ``X`` is reused in two different files with distinct lexical scopes.
    x_files = {s.source.file_id for s in snapshots if s.name == "X" and s.source.file_id}
    assert len(x_files) >= 2

    # At least three distinct source files were executed and captured.
    assert len({s.source.file_id for s in snapshots if s.source.file_id}) >= 3


def test_flat_lab_failure_is_real_and_not_observer_only(tmp_path):
    root = _copy_example(tmp_path, "flat-lab")
    native = _run_native(root, "script", "main.py", ["--fail"])
    assert native.returncode != 0
    assert "ValueError" in _text(native.stderr)

    done, run, snapshots = _run_observed(tmp_path, root, "script", "main.py", ["--fail"])
    assert done.status == "failed", done.message
    assert run["status"] == "failed"
    assert any(s.source.path.endswith("compute.py") for s in snapshots)


def test_src_lab_module_entry_requires_authored_import_path(tmp_path):
    root = _copy_example(tmp_path, "src-lab")
    environment = {"PYTHONPATH": root / "src"}

    # Without the authored import path the module entry cannot resolve.
    bare = {k: v for k, v in os.environ.items() if k.upper() != "PYTHONPATH"}
    bare["PYTHONDONTWRITEBYTECODE"] = "1"
    missing = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", "-m", "research_lab.main"],
        cwd=root,
        env=bare,
        capture_output=True,
        timeout=TIMEOUT,
    )
    assert missing.returncode != 0

    native = _run_native(root, "module", "research_lab.main", environment=environment)
    assert native.returncode == 0, _text(native.stderr)
    done, run, snapshots = _run_observed(
        tmp_path, root, "module", "research_lab.main", environment=environment
    )
    assert done.status == "completed", done.message
    assert any(s.source.path.endswith("compute.py") for s in snapshots)
    assert run["environment"]["project_id"]
    assert run["environment"]["project_revision_id"]


def test_src_lab_import_runs_package_initializer_once(tmp_path):
    root = _copy_example(tmp_path, "src-lab")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(root / "src"))
    proc = subprocess.run(
        [
            sys.executable,
            "-B",
            "-X",
            "utf8",
            "-c",
            "import research_lab, research_lab; print(research_lab.INITIALIZATIONS)",
        ],
        cwd=root,
        env=env,
        capture_output=True,
        timeout=TIMEOUT,
    )
    assert proc.returncode == 0, _text(proc.stderr)
    assert _text(proc.stdout).strip() == "1"


def test_example_source_fixtures_stay_small():
    for path in sorted(EXAMPLES.rglob("*.py")):
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) <= MAX_FIXTURE_LINES, (path.name, len(lines))