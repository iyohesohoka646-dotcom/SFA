"""P1 index/IO performance tests.

These assert connection scoping, bulk compact reads and atomic publication
semantics. They deliberately avoid timing-only assertions; the single benchmark
test records timings but never asserts on them.
"""

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from contract_driven_ai_flow.research.projects.service import ProjectService
from contract_driven_ai_flow.research.projects.store import ProjectStore


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_project(root, count=40, lines=3):
    root.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        body = "".join(f"V{j} = {j}\n" for j in range(lines))
        write(root, f"mod_{i:03}.py", f"def f_{i}():\n    return {i}\n{body}")
    return root


def count_project_connections(monkeypatch):
    counter = {"n": 0}
    real = sqlite3.connect

    def counting(database, *args, **kwargs):
        if str(database).endswith("projects.sqlite3"):
            counter["n"] += 1
        return real(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", counting)
    return counter


def test_index_write_uses_scoped_connection_not_per_file(tmp_path, monkeypatch):
    root = make_project(tmp_path / "lab", count=40)
    service = ProjectService(tmp_path / "host")
    project = service.open(root)
    counter = count_project_connections(monkeypatch)
    try:
        revision = service.index(project.id)
        assert revision.files_count == 40
        # One scoped connection for the whole write phase, not one per file.
        assert counter["n"] <= 6, counter["n"]
        assert counter["n"] < revision.files_count
    finally:
        service.close()


def test_incremental_reuse_uses_bulk_compact_read(tmp_path, monkeypatch):
    root = make_project(tmp_path / "lab", count=30)
    service = ProjectService(tmp_path / "host")
    project = service.open(root)
    service.index(project.id)

    def forbidden(self, analysis_id):
        raise AssertionError("per-file facts/symbol read on reuse")

    monkeypatch.setattr(ProjectStore, "get_facts", forbidden)
    monkeypatch.setattr(ProjectStore, "get_symbols", forbidden)
    counter = count_project_connections(monkeypatch)
    try:
        second = service.index(project.id)
        assert second.parsed_files == 0 and second.reused_files == 30
        assert counter["n"] <= 6, counter["n"]
    finally:
        service.close()


def test_graph_bulk_reads_compact_records(tmp_path, monkeypatch):
    root = make_project(tmp_path / "lab", count=40)
    service = ProjectService(tmp_path / "host")
    project = service.open(root)
    service.index(project.id)

    def forbidden(self, analysis_id):
        raise AssertionError("per-file read during graph")

    monkeypatch.setattr(ProjectStore, "get_facts", forbidden)
    monkeypatch.setattr(ProjectStore, "get_symbols", forbidden)
    counter = count_project_connections(monkeypatch)
    try:
        sliced = service.graph(project.id)
        assert sliced.graph.blocks
        assert counter["n"] <= 4, counter["n"]
    finally:
        service.close()


def test_cancel_rolls_back_uncommitted_caches(tmp_path, monkeypatch):
    root = make_project(tmp_path / "lab", count=25)
    service = ProjectService(tmp_path / "host")
    project = service.open(root)
    r1 = service.index(project.id)
    for i in range(0, 25, 3):
        write(root, f"mod_{i:03}.py", f"def f_{i}():\n    return {i}\nCHANGED = {i}\n")

    store_path = root / ".cdaf" / "research" / "projects.sqlite3"
    real_put = ProjectStore.put_analysis
    cancel = threading.Event()
    calls = {"n": 0}

    def hooked(self, analysis_id, digest, payload):
        calls["n"] += 1
        if calls["n"] >= 2:
            cancel.set()
        return real_put(self, analysis_id, digest, payload)

    monkeypatch.setattr(ProjectStore, "put_analysis", hooked)
    try:
        with pytest.raises((RuntimeError, InterruptedError)):
            service.index(project.id, cancel=cancel)
        assert calls["n"] >= 2
        assert service.revision(project.id).id == r1.id
        con = sqlite3.connect(store_path)
        try:
            rows = con.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
        finally:
            con.close()
        # The cancelled batch rolled back: only the published revision's rows remain.
        assert rows == 25, rows
    finally:
        service.close()


def test_concurrent_reader_sees_prior_revision_until_publish(tmp_path, monkeypatch):
    root = make_project(tmp_path / "lab", count=20)
    service = ProjectService(tmp_path / "host")
    project = service.open(root)
    r1 = service.index(project.id)
    for i in range(0, 20, 2):
        write(root, f"mod_{i:03}.py", f"def f_{i}():\n    return {i}\nNEW = {i}\n")

    reader = ProjectStore(root)
    gate = threading.Event()
    release = threading.Event()
    real_put = ProjectStore.put_analysis

    def hooked(self, analysis_id, digest, payload):
        result = real_put(self, analysis_id, digest, payload)
        if not gate.is_set():
            gate.set()
            release.wait(10)
        return result

    monkeypatch.setattr(ProjectStore, "put_analysis", hooked)
    outcome = {}

    def run():
        outcome["revision"] = service.index(project.id)

    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert gate.wait(10), "index never reached the write phase"
        header = reader.latest_revision(project.id)
        assert header["revision_id"] == r1.id
        assert len(reader.revision_files(r1.id)) == 20
    finally:
        release.set()
        worker.join(15)
        service.close()
    assert not worker.is_alive()
    assert outcome["revision"].id != r1.id


def test_unicode_and_space_paths(tmp_path):
    root = tmp_path / "my project ünïcode"
    root.mkdir(parents=True)
    write(root, "café/módulo.py", "def grüße():\n    return 1\n")
    write(root, "spaced name.py", "VALUE = 2\n")
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        revision = service.index(project.id)
        assert revision.files_count == 2
        units = {u.relative_path: u for u in service.files(project.id).items}
        assert set(units) == {"café/módulo.py", "spaced name.py"}
        assert "VALUE = 2" in service.source(project.id, units["spaced name.py"].id)["code"]
    finally:
        service.close()


def test_out_of_root_symlink_is_excluded(tmp_path):
    root = tmp_path / "lab"
    root.mkdir()
    write(root, "inside.py", "X = 1\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    write(outside, "secret.py", "Y = 2\n")
    try:
        (root / "link.py").symlink_to(outside / "secret.py")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable in this environment")
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        revision = service.index(project.id)
        assert revision.files_count == 1
        assert {u.relative_path for u in service.files(project.id).items} == {"inside.py"}
    finally:
        service.close()


def test_discovery_progress_precedes_each_file_and_cancel(tmp_path):
    root = make_project(tmp_path / "lab", count=12, lines=1)
    service = ProjectService(tmp_path / "host")
    project = service.open(root)
    seen = []
    cancel = threading.Event()

    def progress(rel):
        seen.append(rel)
        if len(seen) >= 3:
            cancel.set()

    try:
        with pytest.raises((RuntimeError, InterruptedError)):
            service.index(project.id, cancel=cancel, progress=progress)
        assert len(seen) >= 3
        assert all(name.endswith(".py") for name in seen)
        with pytest.raises(KeyError):
            service.revision(project.id)
    finally:
        service.close()


@contextmanager
def _no_borrow_session(self):
    """Legacy emulation: no borrowed connection, each method opens its own."""
    conn = sqlite3.connect(self.path, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def test_p1_benchmark_records_timings(tmp_path, monkeypatch, capsys):
    root = make_project(tmp_path / "bench", count=100, lines=100)
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        t0 = time.perf_counter(); cold = service.index(project.id); cold_t = time.perf_counter() - t0
        t0 = time.perf_counter(); warm = service.index(project.id); warm_t = time.perf_counter() - t0
        write(root, "mod_000.py", "def f_0():\n    return 0\nCHANGED = 1\n")
        t0 = time.perf_counter(); inc = service.index(project.id); inc_t = time.perf_counter() - t0
        t0 = time.perf_counter(); service.graph(project.id); query_t = time.perf_counter() - t0
        assert cold.parsed_files == 100 and warm.reused_files == 100
        assert inc.parsed_files == 1 and inc.reused_files == 99
    finally:
        service.close()

    legacy_root = make_project(tmp_path / "bench_legacy", count=100, lines=100)
    legacy_service = ProjectService(tmp_path / "host_legacy")
    try:
        legacy_project = legacy_service.open(legacy_root)
        monkeypatch.setattr(ProjectStore, "session", _no_borrow_session)
        t0 = time.perf_counter(); legacy_cold = legacy_service.index(legacy_project.id); legacy_t = time.perf_counter() - t0
        assert legacy_cold.parsed_files == 100
        t0 = time.perf_counter(); legacy_service.index(legacy_project.id); legacy_warm_t = time.perf_counter() - t0
    finally:
        legacy_service.close()

    capsys.readouterr()
    print(
        "\nP1 bench (100 files x 100 lines): "
        f"cold={cold_t:.3f}s warm={warm_t:.3f}s incremental={inc_t:.3f}s query={query_t:.3f}s | "
        f"legacy-connection-churn cold={legacy_t:.3f}s warm={legacy_warm_t:.3f}s"
    )
