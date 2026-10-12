"""P2 durable actual-loaded-file receipt tests (own tests; frozen acceptance untouched)."""

import hashlib
import importlib.machinery
import importlib.util
import sys
from pathlib import Path

from contract_driven_ai_flow.research.agent.sdk import TraceSession
from contract_driven_ai_flow.research.agent.transport import EventTransport


def run_project():
    from contract_driven_ai_flow.research.agent.project_runner import run_project as runner

    return runner


def build_manifest(root, project_id="project-test", revision_id="revision-test"):
    return {
        str(p.resolve()): {
            "file_id": p.relative_to(root).as_posix(),
            "digest": hashlib.sha256(p.read_bytes()).hexdigest(),
            "project_id": project_id,
            "project_revision_id": revision_id,
        }
        for p in root.rglob("*.py")
    }


def write(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def execute(root, kind="script", target="main.py", manifest=None):
    events = []
    session = TraceSession("project", EventTransport(sink=events))
    status = run_project()(
        root,
        {"kind": kind, "target": target},
        session=session,
        manifest=build_manifest(root) if manifest is None else manifest,
    )
    finished = next(e for e in events if e["kind"] == "run.finished")
    return status, events, finished["payload"]


def receipt_of(payload):
    return payload["project_execution"]


def test_loaded_ledger_counts_empty_module_and_excludes_unused(tmp_path):
    write(tmp_path, "empty.py", "# imported but creates no values\n")
    write(tmp_path, "unused.py", "NEVER = 1\n")
    write(tmp_path, "calc.py", "def double(v):\n    return v * 2\n")
    write(tmp_path, "main.py", "import empty\nfrom calc import double\nY = double(7)\n")
    status, events, payload = execute(tmp_path)
    assert status == 0
    receipt = receipt_of(payload)
    loaded = {f["path"]: f for f in receipt["loaded_files"]}
    assert set(loaded) == {"main.py", "empty.py", "calc.py"}
    assert all(f["state"] == "completed" and f["file_id"] and f["digest"] for f in loaded.values())
    assert receipt["loaded_count"] == 3 and receipt["complete"] is True
    assert receipt["omitted_count"] == 0
    packets = [e for e in events if e["kind"] == "project.files"]
    assert packets and sum(len(p["payload"]["files"]) for p in packets) == 3
    assert all(len(p["payload"]["files"]) <= 16 for p in packets)


def test_failed_module_and_entry_are_failed(tmp_path):
    write(tmp_path, "calc.py", 'raise RuntimeError("module failed")\n')
    write(tmp_path, "main.py", "from calc import double\nY = double(1)\n")
    status, events, payload = execute(tmp_path)
    assert status == 1
    receipt = receipt_of(payload)
    loaded = {f["path"]: f for f in receipt["loaded_files"]}
    assert loaded["calc.py"]["state"] == "failed"
    assert loaded["main.py"]["state"] == "failed"
    assert receipt["complete"] is True


def test_unindexed_in_root_load_is_a_coverage_gap(tmp_path):
    write(tmp_path, "helper.py", "def value():\n    return 1\n")
    write(tmp_path, "main.py", "import helper\nY = helper.value()\n")
    manifest = build_manifest(tmp_path)
    manifest.pop(str((tmp_path / "helper.py").resolve()))
    status, events, payload = execute(tmp_path, manifest=manifest)
    assert status == 0
    receipt = receipt_of(payload)
    loaded = {f["path"]: f for f in receipt["loaded_files"]}
    helper = loaded["helper.py"]
    assert helper["file_id"] == "" and helper["digest"]
    assert helper["coverage"] == "unsupported"
    assert loaded["main.py"]["coverage"] == "supported"
    assert receipt["coverage"]["unsupported"] >= 1


def test_custom_loader_boundary_is_recorded_unsupported(tmp_path):
    write(tmp_path, "custmod.py", "VALUE = 5\n")
    write(tmp_path, "main.py", "import custmod\nY = custmod.VALUE\n")

    class CustomLoader(importlib.machinery.SourceFileLoader):
        executed = False

        def exec_module(self, module):
            CustomLoader.executed = True
            return super().exec_module(module)

    origin = str((tmp_path / "custmod.py").resolve())

    class Finder:
        def find_spec(self, name, path=None, target=None):
            if name == "custmod":
                return importlib.util.spec_from_file_location(
                    "custmod", origin, loader=CustomLoader("custmod", origin)
                )
            return None

    finder = Finder()
    sys.meta_path.insert(0, finder)
    try:
        status, events, payload = execute(tmp_path)
    finally:
        sys.meta_path.remove(finder)
    assert status == 0 and CustomLoader.executed is True
    receipt = receipt_of(payload)
    loaded = {f["path"]: f for f in receipt["loaded_files"]}
    assert loaded["custmod.py"]["coverage"] == "unsupported"


def test_receipt_pages_more_than_summary_with_bounded_batches(tmp_path):
    imports = []
    for index in range(20):
        name = "mod%02d" % index
        write(tmp_path, name + ".py", "VALUE_%d = %d\n" % (index, index))
        imports.append("import " + name)
    write(tmp_path, "main.py", "\n".join(imports) + "\n")
    status, events, payload = execute(tmp_path)
    assert status == 0
    receipt = receipt_of(payload)
    loaded = receipt["loaded_files"]
    assert len(loaded) == 21
    assert receipt["loaded_count"] == 21
    assert receipt["omitted_from_summary"] == 0
    packets = [e for e in events if e["kind"] == "project.files"]
    assert sum(len(p["payload"]["files"]) for p in packets) == 21
    assert all(len(p["payload"]["files"]) <= 16 for p in packets)
    assert len(packets) == 2


def test_store_merges_environment_preserving_project_reference(tmp_path):
    from contract_driven_ai_flow.research.models import ObservationEvent
    from contract_driven_ai_flow.research.store import ExperimentStore

    store = ExperimentStore(tmp_path / "host")
    run = store.create_run(
        str(tmp_path / "main.py"),
        interpreter=sys.executable,
        source_digest="0" * 64,
        environment={"project_id": "p1", "project_revision_id": "r1"},
    )
    store.append([ObservationEvent(run_id=run["id"], kind="run.started", payload={"name": "x"})])
    store.append(
        [
            ObservationEvent(
                run_id=run["id"],
                kind="environment.observed",
                payload={"executable": sys.executable, "python": "3"},
            )
        ]
    )
    record = store.run(run["id"])
    assert record["environment"]["project_id"] == "p1"
    assert record["environment"]["project_revision_id"] == "r1"
    assert record["environment"]["python"] == "3"


def test_store_environment_replace_unchanged_for_legacy_runs(tmp_path):
    from contract_driven_ai_flow.research.models import ObservationEvent
    from contract_driven_ai_flow.research.store import ExperimentStore

    store = ExperimentStore(tmp_path / "host2")
    run = store.create_run(
        str(tmp_path / "main.py"), interpreter=sys.executable, source_digest="0" * 64
    )
    store.append([ObservationEvent(run_id=run["id"], kind="run.started", payload={})])
    store.append(
        [
            ObservationEvent(
                run_id=run["id"],
                kind="environment.observed",
                payload={"executable": "python", "python": "3"},
            )
        ]
    )
    assert store.run(run["id"])["environment"] == {"executable": "python", "python": "3"}

def test_transport_fault_marks_incomplete_and_still_cleans_up(tmp_path, monkeypatch):
    import os

    write(tmp_path, "calc.py", "def double(v):\n    return v * 2\n")
    write(tmp_path, "main.py", "from calc import double\nY = double(2)\n")
    events = []
    session = TraceSession("project", EventTransport(sink=events))
    real_emit = session.emit

    def faulty(kind, payload, **kwargs):
        # Only the durable loaded-file packet is down; the real session keeps its
        # full TraceSession protocol so ordinary observation still works.
        if kind == "project.files":
            raise RuntimeError("observer down")
        return real_emit(kind, payload, **kwargs)

    monkeypatch.setattr(session, "emit", faulty)

    before = os.getcwd()
    status = run_project()(
        tmp_path,
        {"kind": "script", "target": "main.py"},
        session=session,
        manifest=build_manifest(tmp_path),
    )
    assert status == 0
    assert os.getcwd() == before
    finished = next(e for e in events if e["kind"] == "run.finished")
    receipt = finished["payload"]["project_execution"]
    assert receipt["loaded_count"] == 2
    assert receipt["complete"] is False


def test_control_finished_fault_still_restores_state_and_emits_loaded(tmp_path, monkeypatch):
    import os

    write(tmp_path, "calc.py", "def double(v):\n    return v * 2\n")
    write(tmp_path, "main.py", "from calc import double\nY = double(2)\n")
    events = []
    session = TraceSession("project", EventTransport(sink=events))
    real_emit = session.emit

    def faulty(kind, payload, **kwargs):
        if kind == "control.finished":
            raise RuntimeError("control observer down")
        return real_emit(kind, payload, **kwargs)

    monkeypatch.setattr(session, "emit", faulty)

    before = (os.getcwd(), list(sys.path), list(sys.argv), sys.modules.get("__main__"))
    status = run_project()(
        tmp_path,
        {"kind": "script", "target": "main.py"},
        session=session,
        manifest=build_manifest(tmp_path),
    )
    assert status == 0
    # A faulting control observer must not skip process-state restoration.
    assert (os.getcwd(), sys.path, sys.argv, sys.modules.get("__main__")) == before
    assert "calc" not in sys.modules
    # The durable loaded receipt is still emitted independently of controls.
    packets = [e for e in events if e["kind"] == "project.files"]
    assert sum(len(p["payload"]["files"]) for p in packets) == 2
    finished = next(e for e in events if e["kind"] == "run.finished")
    receipt = finished["payload"]["project_execution"]
    assert receipt["loaded_count"] == 2
    assert receipt["complete"] is False


def test_execution_count_counts_enters_not_state_transitions(tmp_path):
    write(tmp_path, "calc.py", "def double(v):\n    return v * 2\n")
    write(tmp_path, "main.py", "import calc\nimport calc\nY = calc.double(2)\n")
    status, events, payload = execute(tmp_path)
    assert status == 0
    receipt = receipt_of(payload)
    counts = {f["path"]: f["count"] for f in receipt["loaded_files"]}
    # The import cache means calc executes once; states must not inflate it.
    assert counts == {"main.py": 1, "calc.py": 1}


def test_repeated_real_execution_increments_count(tmp_path):
    write(tmp_path, "calc.py", "def double(v):\n    return v * 2\n")
    write(
        tmp_path,
        "main.py",
        "import importlib\nimport calc\nimportlib.reload(calc)\nY = calc.double(2)\n",
    )
    status, events, payload = execute(tmp_path)
    assert status == 0
    receipt = receipt_of(payload)
    counts = {f["path"]: f["count"] for f in receipt["loaded_files"]}
    assert counts == {"main.py": 1, "calc.py": 2}