from concurrent.futures import ThreadPoolExecutor
import threading
import time

from contract_driven_ai_flow.research.service import ResearchService


def test_concurrent_imports_preserve_a_readable_immutable_source_archive(tmp_path, monkeypatch):
    from contract_driven_ai_flow import storage
    from contract_driven_ai_flow.research.workbench import service as module

    script = tmp_path / "analysis.py"
    script.write_text("X = 1\n", encoding="utf-8")
    services = [ResearchService(tmp_path), ResearchService(tmp_path)]
    workbenches = [service.workbench for service in services]
    writes = []
    lock = threading.Lock()
    original = storage.atomic_write_private

    def observed_write(path, content):
        with lock:
            writes.append(path)
        time.sleep(.01)
        return original(path, content)

    monkeypatch.setattr(storage, "atomic_write_private", observed_write)
    monkeypatch.setattr(module, "atomic_write_private", observed_write, raising=False)
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            documents = list(pool.map(lambda i: workbenches[i % 2].import_source(script), range(8)))
        assert len(writes) == 1
        archive = writes[0]
        stamp = archive.stat().st_mtime_ns
        with archive.open("rb") as reader:
            again = services[0].workbench.import_source(script)
            assert reader.read() == script.read_bytes()
        assert archive.stat().st_mtime_ns == stamp
        assert all(d.source_digest == again.source_digest for d in documents)
    finally:
        for service in services:
            service.close()


def test_import_does_not_overwrite_conflicting_archived_evidence(tmp_path):
    import pytest
    service = ResearchService(tmp_path)
    script = tmp_path / "analysis.py"
    script.write_text("X = 1\n", encoding="utf-8")
    try:
        document = service.workbench.import_source(script)
        archive = service.store.state / "sources" / (document.source_digest + ".txt")
        archive.write_bytes(b"historical evidence")
        with pytest.raises(ValueError, match="archive"):
            service.workbench.import_source(script)
        assert archive.read_bytes() == b"historical evidence"
    finally:
        service.close()
