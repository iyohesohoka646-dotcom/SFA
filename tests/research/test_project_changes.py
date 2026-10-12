"""Reviewed multi-file project changes: inert proposals and private exact bytes."""

import os
import subprocess

import pytest

from contract_driven_ai_flow.research.projects.changes import ProjectChangeService
from contract_driven_ai_flow.research.projects.service import ProjectService


def example(tmp_path):
    root = tmp_path / "lab"; root.mkdir()
    (root / "main.py").write_text("from calc import double\nY=double(7)\n", encoding="utf-8")
    (root / "calc.py").write_text("def double(v):\n    return v*2\n", encoding="utf-8")
    projects = ProjectService(tmp_path / "host")
    project = projects.open(root)
    revision = projects.index(project.id)
    return root, projects, project, revision, ProjectChangeService(projects)


def test_proposal_is_inert_and_keeps_exact_private_bytes(tmp_path):
    root, projects, project, revision, changes = example(tmp_path)
    try:
        before = (root / "calc.py").read_bytes()
        change = changes.propose(project.id, revision.id, [
            {"path": "calc.py", "content": "def double(v):\n    return v*3\n", "operation": "modify"},
        ])
        assert change.status == "ready"
        assert (root / "calc.py").read_bytes() == before
        assert [v.status for v in change.validation if v.kind == "tests"] == ["not_run"]
        folder = root / ".cdaf/research/project-changes" / change.id
        assert (folder / "blobs/0.original").read_bytes() == before
        assert "v*3" in (folder / "blobs/0.candidate").read_text(encoding="utf-8")
        assert change.files[0].before_digest and change.files[0].after_digest
        assert change.files[0].before_digest != change.files[0].after_digest
    finally:
        projects.close()


def test_escape_duplicate_and_non_python_paths_rejected(tmp_path):
    root, projects, project, revision, changes = example(tmp_path)
    try:
        for bad in ("../outside.py", str(tmp_path / "outside.py"), "/abs/outside.py"):
            with pytest.raises(ValueError):
                changes.propose(project.id, revision.id, [{"path": bad, "content": "x=1\n", "operation": "create"}])
        with pytest.raises(ValueError):
            changes.propose(project.id, revision.id, [
                {"path": "calc.py", "content": "a=1\n", "operation": "modify"},
                {"path": "calc.py", "content": "a=2\n", "operation": "modify"},
            ])
        with pytest.raises(ValueError):
            changes.propose(project.id, revision.id, [{"path": "notes.txt", "content": "hi\n", "operation": "create"}])
    finally:
        projects.close()


def test_bad_syntax_is_invalid_and_no_write(tmp_path):
    root, projects, project, revision, changes = example(tmp_path)
    try:
        before = (root / "calc.py").read_bytes()
        broken = changes.propose(project.id, revision.id, [{"path": "calc.py", "content": "def (\n", "operation": "modify"}])
        assert broken.status == "invalid"
        assert any(v.status == "fail" for v in broken.validation)
        assert (root / "calc.py").read_bytes() == before
    finally:
        projects.close()


def test_format_invariant_violation_is_invalid_not_raised(tmp_path):
    root, projects, project, revision, changes = example(tmp_path)
    try:
        before = (root / "calc.py").read_bytes()
        change = changes.propose(project.id, revision.id, [{"path": "calc.py", "content": "def double(v):\n    return v*99\n", "operation": "format"}])
        assert change.status == "invalid"
        assert [v.status for v in change.validation if v.kind == "format"] == ["fail"]
        assert (root / "calc.py").read_bytes() == before
    finally:
        projects.close()


def test_create_requires_nonexistent_python_file(tmp_path):
    root, projects, project, revision, changes = example(tmp_path)
    try:
        created = changes.propose(project.id, revision.id, [{"path": "extra.py", "content": "X = 1\n", "operation": "create"}])
        assert created.status == "ready" and created.files[0].before_exists is False
        assert not (root / "extra.py").exists()
        clash = changes.propose(project.id, revision.id, [{"path": "calc.py", "content": "X = 1\n", "operation": "create"}])
        assert clash.status == "invalid"
    finally:
        projects.close()


def test_get_and_list_are_project_owned(tmp_path):
    root, projects, project, revision, changes = example(tmp_path)
    try:
        change = changes.propose(project.id, revision.id, [{"path": "calc.py", "content": "def double(v):\n    return v*4\n", "operation": "modify"}])
        assert changes.get(project.id, change.id).id == change.id
        assert [item.id for item in changes.list(project.id)] == [change.id]
        with pytest.raises(LookupError):
            changes.get("missing-project", change.id)
        with pytest.raises(LookupError):
            changes.get(project.id, "0" * 32)
    finally:
        projects.close()


def test_reject_persists_status_and_records_event(tmp_path):
    root, projects, project, revision, changes = example(tmp_path)
    try:
        change = changes.propose(project.id, revision.id, [{"path": "calc.py", "content": "def double(v):\n    return v*5\n", "operation": "modify"}])
        assert changes.reject(project.id, change.id).status == "rejected"
        assert changes.get(project.id, change.id).status == "rejected"
        events = (root / ".cdaf/research/project-changes/events.json").read_text(encoding="utf-8")
        assert "rejected" in events
    finally:
        projects.close()


def _crash_on_second(changes, monkeypatch):
    original = changes._write_file
    state = {"count": 0}

    def crash(path, data):
        state["count"] += 1
        if state["count"] == 2:
            raise OSError("simulated write interruption")
        return original(path, data)

    monkeypatch.setattr(changes, "_write_file", crash)


def test_whole_set_conflict_aborts_before_any_write(tmp_path):
    root, projects, project, revision, changes = example(tmp_path)
    try:
        change = changes.propose(project.id, revision.id, [
            {"path": "calc.py", "content": "def double(v):\n    return v*3\n", "operation": "modify"},
            {"path": "main.py", "content": "from calc import double\nY=double(9)\n", "operation": "modify"},
        ])
        before = (root / "calc.py").read_bytes()
        (root / "main.py").write_text("USER=1\n")
        with pytest.raises((ValueError, RuntimeError)):
            changes.accept(project.id, change.id)
        assert (root / "calc.py").read_bytes() == before
        assert (root / "main.py").read_text() == "USER=1\n"
        assert changes.get(project.id, change.id).status == "conflict"
        assert changes._journal_path(root).exists() is False
    finally:
        projects.close()


def test_interrupted_write_requires_explicit_recovery(tmp_path, monkeypatch):
    root, projects, project, revision, changes = example(tmp_path)
    try:
        change = changes.propose(project.id, revision.id, [
            {"path": "calc.py", "content": "def double(v):\n    return v*3\n", "operation": "modify"},
            {"path": "main.py", "content": "from calc import double\nY=double(9)\n", "operation": "modify"},
        ])
        _crash_on_second(changes, monkeypatch)
        with pytest.raises(OSError):
            changes.accept(project.id, change.id)
        assert changes.get(project.id, change.id).status == "recovery_required"
        with pytest.raises(RuntimeError):
            changes.assert_ready(project.id)
        changes.recover(project.id)
        changes.assert_ready(project.id)
        assert (root / "calc.py").read_text() == "def double(v):\n    return v*2\n"
        assert (root / "main.py").read_text() == "from calc import double\nY=double(7)\n"
        assert changes._journal_path(root).exists() is False
        assert changes.get(project.id, change.id).status == "rejected"
    finally:
        projects.close()


def test_user_edit_after_interruption_blocks_recovery_and_preserves_bytes(tmp_path, monkeypatch):
    root, projects, project, revision, changes = example(tmp_path)
    try:
        change = changes.propose(project.id, revision.id, [
            {"path": "calc.py", "content": "def double(v):\n    return v*3\n", "operation": "modify"},
            {"path": "main.py", "content": "from calc import double\nY=double(9)\n", "operation": "modify"},
        ])
        _crash_on_second(changes, monkeypatch)
        with pytest.raises(OSError):
            changes.accept(project.id, change.id)
        (root / "calc.py").write_text("USER=9\n")
        with pytest.raises((ValueError, RuntimeError)) as error:
            changes.recover(project.id)
        assert "calc.py" in str(error.value)
        assert (root / "calc.py").read_text() == "USER=9\n"
        assert (root / "main.py").read_text() == "from calc import double\nY=double(7)\n"
        assert changes._journal_path(root).exists() is True
        with pytest.raises(RuntimeError):
            changes.assert_ready(project.id)
    finally:
        projects.close()


def test_reviewed_rollback_is_ready_and_later_user_edit_blocks_it(tmp_path):
    root, projects, project, revision, changes = example(tmp_path)
    try:
        change = changes.propose(project.id, revision.id, [
            {"path": "calc.py", "content": "def double(v):\n    return v*3\n", "operation": "modify"},
            {"path": "main.py", "content": "from calc import double\nY=double(9)\n", "operation": "modify"},
        ])
        accepted = changes.accept(project.id, change.id)
        assert accepted.status == "accepted"
        rollback = changes.rollback(project.id, change.id)
        assert rollback.status == "ready" and rollback.rollback_of == change.id
        assert rollback.id != change.id
        assert not any(f.path.endswith(".tmp") for f in rollback.files)
        (root / "main.py").write_text("USER=2\n")
        with pytest.raises((ValueError, RuntimeError)):
            changes.accept(project.id, rollback.id)
        assert "v*3" in (root / "calc.py").read_text()
        assert (root / "main.py").read_text() == "USER=2\n"
    finally:
        projects.close()


def test_created_file_rollback_is_explicitly_unsupported(tmp_path):
    root, projects, project, revision, changes = example(tmp_path)
    try:
        change = changes.propose(project.id, revision.id, [{"path": "extra.py", "content": "X = 1\n", "operation": "create"}])
        accepted = changes.accept(project.id, change.id)
        assert accepted.status == "accepted" and (root / "extra.py").read_text() == "X = 1\n"
        with pytest.raises(ValueError):
            changes.rollback(project.id, change.id)
        errors = [v for v in changes.get(project.id, change.id).validation if v.status == "fail"]
        assert errors and "manual" in errors[0].detail
    finally:
        projects.close()



def _two_edits():
    return [
        {"path": "calc.py", "content": "def double(v):\n    return v*3\n", "operation": "modify"},
        {"path": "main.py", "content": "from calc import double\nY=double(9)\n", "operation": "modify"},
    ]


def test_pending_journal_cannot_be_replaced_by_another_accept(tmp_path, monkeypatch):
    root, projects, project, revision, changes = example(tmp_path)
    try:
        first = changes.propose(project.id, revision.id, _two_edits())
        second = changes.propose(project.id, revision.id, [{"path": "main.py", "content": "OTHER=3\n"}])
        write = changes._write_file
        state = {"count": 0}

        def crash(path, data):
            state["count"] += 1
            if state["count"] == 2:
                raise OSError("interrupted second file")
            write(path, data)

        with monkeypatch.context() as patch:
            patch.setattr(changes, "_write_file", crash)
            with pytest.raises(OSError):
                changes.accept(project.id, first.id)
        journal = root / ".cdaf/research/project-changes/journal.json"
        before = journal.read_bytes()
        with pytest.raises((ValueError, RuntimeError)):
            changes.accept(project.id, second.id)
        assert journal.read_bytes() == before
        assert "double(7)" in (root / "main.py").read_text()
    finally:
        projects.close()


def test_recovery_rechecks_each_file_before_restoring(tmp_path, monkeypatch):
    root, projects, project, revision, changes = example(tmp_path)
    try:
        change = changes.propose(project.id, revision.id, _two_edits())
        write = changes._write_file

        def fail_after_both(path, data):
            write(path, data)
            if path.name == "main.py":
                raise OSError("interrupted final receipt")

        with monkeypatch.context() as patch:
            patch.setattr(changes, "_write_file", fail_after_both)
            with pytest.raises(OSError):
                changes.accept(project.id, change.id)

        def concurrent_edit(path, data):
            write(path, data)
            if path.name == "calc.py":
                (root / "main.py").write_text("USER=99\n")

        with monkeypatch.context() as patch:
            patch.setattr(changes, "_write_file", concurrent_edit)
            with pytest.raises((ValueError, RuntimeError)):
                changes.recover(project.id)
        assert (root / "main.py").read_text() == "USER=99\n"
        with pytest.raises(RuntimeError):
            changes.assert_ready(project.id)
    finally:
        projects.close()


def test_replaced_parent_link_cannot_write_outside_project(tmp_path):
    from contract_driven_ai_flow.research.projects.changes import ProjectChangeService
    from contract_driven_ai_flow.research.projects.service import ProjectService

    root = tmp_path / "lab"; package = root / "pkg"; package.mkdir(parents=True)
    (package / "calc.py").write_text("X=1\n")
    projects = ProjectService(tmp_path / "host")
    try:
        project = projects.open(root); revision = projects.index(project.id)
        changes = ProjectChangeService(projects)
        proposal = changes.propose(project.id, revision.id, [{"path": "pkg/calc.py", "content": "X=2\n"}])
        package.rename(root / "original_pkg")
        outside = tmp_path / "outside"; outside.mkdir(); (outside / "calc.py").write_text("X=1\n")
        if os.name == "nt":
            linked = subprocess.run(["cmd", "/c", "mklink", "/J", str(package), str(outside)], capture_output=True)
            assert linked.returncode == 0, linked.stderr
        else:
            package.symlink_to(outside, target_is_directory=True)
        with pytest.raises((ValueError, RuntimeError)):
            changes.accept(project.id, proposal.id)
        assert (outside / "calc.py").read_text() == "X=1\n"
    finally:
        projects.close()
