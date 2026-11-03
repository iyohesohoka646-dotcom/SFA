"""Independent review: an already-admitted index must not publish a half-change."""
from concurrent.futures import ThreadPoolExecutor
import threading

from contract_driven_ai_flow.research.projects.application import ProjectApplication
from contract_driven_ai_flow.research.projects import discovery


def test_index_and_reviewed_change_cannot_publish_half_transaction(tmp_path, monkeypatch):
    root = tmp_path / "lab"
    root.mkdir()
    for name in ("a.py", "b.py"):
        (root / name).write_text("value=1\n", encoding="utf-8")
    app = ProjectApplication(tmp_path / "host")
    project = app.open(root)
    old = app.index(project.id)
    changes = app.changes(project.id)
    proposal = changes.propose(project.id, old.id, [
        {"path": name, "content": "value=2\n", "operation": "modify"}
        for name in ("a.py", "b.py")
    ])
    scanning, release_index = threading.Event(), threading.Event()
    first_written, finish_change = threading.Event(), threading.Event()
    discover = discovery.discover_files
    write = changes._write_file

    def paused_discover(*args, **kwargs):
        scanning.set()
        assert release_index.wait(5)
        return discover(*args, **kwargs)

    def paused_write(path, data):
        write(path, data)
        if path.name == "a.py":
            first_written.set()
            assert finish_change.wait(5)

    monkeypatch.setattr(discovery, "discover_files", paused_discover)
    monkeypatch.setattr(changes, "_write_file", paused_write)
    try:
        with ThreadPoolExecutor(2) as pool:
            index = pool.submit(app.index, project.id)
            assert scanning.wait(3)
            change = pool.submit(changes.accept, project.id, proposal.id)
            writing = first_written.wait(0.3)
            release_index.set()
            try:
                if writing:
                    try:
                        index.result(timeout=2)
                    except RuntimeError:
                        pass  # A visible transaction conflict is acceptable.
                    except TimeoutError:
                        pass  # Waiting for the owned writer is acceptable.
                    else:
                        assert app.projects.revision(project.id).id == old.id, (
                            "Index published a new revision while only a.py was written "
                            "and the reviewed multi-file journal was still active"
                        )
            finally:
                finish_change.set()
            try:
                change.result(timeout=5)
            except ValueError as error:
                assert not writing, "A started writer must not be invalidated midway"
                assert "revision changed" in str(error).lower()
                assert changes.get(project.id, proposal.id).status == "conflict"
                assert all((root / name).read_text(encoding="utf-8") == "value=1\n" for name in ("a.py", "b.py"))
    finally:
        release_index.set()
        finish_change.set()
        app.close()


"""Independent cancellation and lock-ownership acceptance."""
from concurrent.futures import ThreadPoolExecutor
import os
import threading
import time

import pytest

from contract_driven_ai_flow.research.projects.application import ProjectApplication


def test_waiting_index_cancels_without_unlocking_change_holder(tmp_path, monkeypatch):
    root = tmp_path / "lab"
    root.mkdir()
    (root / "a.py").write_text("x=1\n", encoding="utf-8")
    app = ProjectApplication(tmp_path / "host")
    project = app.open(root)
    revision = app.index(project.id)
    changes = app.changes(project.id)
    attempted, cancel = threading.Event(), threading.Event()
    acquire = changes._lock_handle
    holder = threading.get_ident()

    def observed_acquire(handle, owned):
        if owned and threading.get_ident() != holder:
            attempted.set()
        return acquire(handle, owned)

    try:
        with changes._lock(root):
            monkeypatch.setattr(changes, "_lock_handle", observed_acquire)
            with ThreadPoolExecutor(1) as pool:
                waiter = pool.submit(app.index, project.id, cancel)
                try:
                    assert attempted.wait(1), "Index never attempted the project transaction lock"
                    started = time.monotonic()
                    cancel.set()
                    with pytest.raises(InterruptedError, match="cancel"):
                        waiter.result(timeout=1)
                    assert time.monotonic() - started < 1
                    assert app.projects.revision(project.id).id == revision.id
                    fd = os.open(root / ".cdaf/research/project-changes/project.lock", os.O_RDWR)
                    try:
                        with pytest.raises(OSError):
                            acquire(fd, True)
                    finally:
                        os.close(fd)
                finally:
                    cancel.set()
        with changes._lock(root):
            pass  # The original holder released its own lock normally.
    finally:
        app.close()
