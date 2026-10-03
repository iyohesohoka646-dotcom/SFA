import json
import threading
import time

import numpy as np
import pytest


def test_queue_overflow_records_drops_and_preserves_terminal_event():
    from contract_driven_ai_flow.research.agent.transport import EventTransport

    transport = EventTransport(max_queue_events=2)
    for i in range(10):
        transport.emit({"run_id": "r", "kind": "value.observed", "payload": {"index": i}})
    transport.emit({"run_id": "r", "kind": "run.finished", "payload": {"status": "completed"}}, critical=True)
    events = transport.drain()
    assert transport.dropped == 8
    assert sum(e["kind"] == "value.observed" for e in events) == 2
    assert any(e["kind"] == "run.finished" for e in events)
    assert any(e["kind"] == "capture.dropped" and e["payload"]["count"] == 8 for e in events)


def test_slow_sink_does_not_block_scientific_producer():
    from contract_driven_ai_flow.research.agent.transport import EventTransport

    gate = threading.Event()
    batches = []

    def sink(batch):
        gate.wait(2)
        batches.extend(batch)

    transport = EventTransport(sink, max_queue_events=2, publish_interval_ms=10)
    started = time.perf_counter()
    for i in range(100):
        transport.emit({"run_id": "r", "kind": "value.observed", "payload": {"i": i}})
    assert time.perf_counter() - started < 0.2
    transport.emit({"run_id": "r", "kind": "run.finished", "payload": {}}, critical=True)
    gate.set()
    assert transport.close(timeout=3)
    assert any(e["kind"] == "run.finished" for e in batches)


def test_full_capture_is_opt_in_bounded_and_immutable(tmp_path):
    from contract_driven_ai_flow.research.agent.sdk import TraceSession
    from contract_driven_ai_flow.research.agent.budget import CapturePolicy
    from contract_driven_ai_flow.research.agent.transport import EventTransport
    from contract_driven_ai_flow.research.models import ObservationEvent
    from contract_driven_ai_flow.research.store import ExperimentStore

    store = ExperimentStore(tmp_path)
    run = store.create_run("analysis.py", interpreter="python", source_digest="x")
    trace = TraceSession("full", EventTransport(), CapturePolicy(level="full"), run_id=run["id"], artifact_root=store.state)
    value = np.arange(12).reshape(3, 4)
    first = trace.watch("X", value)
    value[:] = 99
    second = trace.watch("X", value)
    store.append([ObservationEvent.model_validate(e) for e in trace.transport.drain()])
    old = store.slice(first["id"], [{"start": 0, "stop": 1}, {"start": 0, "stop": 2}])
    new = store.slice(second["id"], [{"start": 0, "stop": 1}, {"start": 0, "stop": 2}])
    assert old["available"] and old["values"] == [[0, 1]]
    assert new["values"] == [[99, 99]]
    too_large = TraceSession("bounded", EventTransport(), CapturePolicy(level="full", max_artifact_bytes=32), artifact_root=tmp_path)
    limited = too_large.watch("X", np.zeros((20, 20)))
    assert limited["artifact_ref"] is None
    assert "artifact_byte_limit" in limited["truncation"]


def test_slice_rejects_excessive_regions_and_path_escape(tmp_path):
    from contract_driven_ai_flow.research.artifacts import read_slice
    from contract_driven_ai_flow.research.models import SnapshotRef, ValueDescriptor

    np.save(tmp_path / "value.npy", np.zeros((100, 100)), allow_pickle=False)
    snapshot = SnapshotRef(id="s", run_id="r", binding_id="X", scope_id="main", name="X", version=1, descriptor=ValueDescriptor(kind="matrix", backend="numpy", type_name="numpy.ndarray", shape=[100, 100]), artifact_ref="value.npy")
    with pytest.raises(ValueError, match="4096|64"):
        read_slice(tmp_path, snapshot, [{"start": 0, "stop": 100}, {"start": 0, "stop": 100}])
    escaped = snapshot.model_copy(update={"artifact_ref": "../outside.npy"})
    with pytest.raises(ValueError, match="outside|path"):
        read_slice(tmp_path, escaped, [])


def test_capture_policies_reject_unbounded_values():
    from contract_driven_ai_flow.research.agent.budget import CapturePolicy

    with pytest.raises(ValueError):
        CapturePolicy(max_preview_cells=-1)
    with pytest.raises(ValueError):
        CapturePolicy(level="unknown")
    with pytest.raises(ValueError):
        CapturePolicy(max_stat_elements=10**10)


def test_registry_does_not_load_entry_points_until_enabled(monkeypatch):
    import importlib.metadata
    from contract_driven_ai_flow.research.agent.registry import AdapterRegistry

    def forbidden(*args, **kwargs):
        raise AssertionError("installed plugins were scanned implicitly")

    monkeypatch.setattr(importlib.metadata, "entry_points", forbidden)
    registry = AdapterRegistry()
    assert registry.resolve(object()).describe(object())["backend"] == "unknown"


def test_hostile_adapter_result_degrades_without_stopping_analysis():
    from contract_driven_ai_flow.research.agent.adapters import CaptureResult
    from contract_driven_ai_flow.research.agent.registry import AdapterRegistry
    from contract_driven_ai_flow.research.agent.sdk import TraceSession
    from contract_driven_ai_flow.research.agent.transport import EventTransport

    class Broken:
        protocol_version = 1
        backend = "broken"

        def supports(self, value):
            return True

        def describe(self, value):
            return {"kind": "custom", "backend": self.backend, "type_name": "custom"}

        def capture(self, value, policy):
            return CaptureResult(self.describe(value), sample={"secret": float("nan")})

    registry = AdapterRegistry()
    registry.register(Broken())
    transport = EventTransport()
    trace = TraceSession("bad", transport, registry=registry)
    observed = trace.watch("X", object())
    assert observed["fidelity"] == "metadata_only"
    events = transport.drain()
    assert any(e["kind"] == "capture.error" for e in events)
    json.dumps(events, allow_nan=False)


def test_flush_waits_for_inflight_publication():
    from contract_driven_ai_flow.research.agent.transport import EventTransport

    entered, release = threading.Event(), threading.Event()

    def sink(batch):
        entered.set()
        release.wait(2)

    transport = EventTransport(sink, publish_interval_ms=1)
    transport.emit({"run_id": "r", "kind": "run.started", "payload": {}}, critical=True)
    assert entered.wait(1)
    try:
        assert transport.flush(timeout=0.02) is False
    finally:
        release.set()
        assert transport.close(timeout=2)
