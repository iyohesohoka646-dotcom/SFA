import pytest


def test_scope_and_binding_versions_are_distinct():
    from contract_driven_ai_flow.research.models import SnapshotRef, ValueDescriptor

    descriptor = ValueDescriptor(kind="tensor", backend="third-party", type_name="Tensor", shape=[3, 4], dtype="float32", capabilities=["preview"])
    first = SnapshotRef(id="a", run_id="r", binding_id="scope-a:X", scope_id="scope-a", name="X", version=1, descriptor=descriptor)
    next_value = first.model_copy(update={"id": "b", "version": 2})
    other_scope = first.model_copy(update={"id": "c", "binding_id": "scope-b:X", "scope_id": "scope-b"})
    assert first.binding_id != other_scope.binding_id
    assert next_value.version == 2 and first.version == 1
    assert first.descriptor.backend == "third-party"


def test_event_pagination_survives_restart(tmp_path):
    from contract_driven_ai_flow.research.models import ObservationEvent
    from contract_driven_ai_flow.research.store import ExperimentStore

    store = ExperimentStore(tmp_path)
    run = store.create_run("analysis.py", interpreter="python", source_digest="abc", name="analysis")
    store.append([ObservationEvent(run_id=run["id"], kind="value.observed", payload={"index": i}) for i in range(7)])
    page = store.events(run["id"], limit=3)
    assert [e.payload["index"] for e in page] == [0, 1, 2]
    reopened = ExperimentStore(tmp_path)
    tail = reopened.events(run["id"], after=page[-1].sequence)
    assert [e.payload["index"] for e in tail] == [3, 4, 5, 6]
    assert len({e.sequence for e in [*page, *tail]}) == 7
    assert reopened.runs()[0]["source_digest"] == "abc"


def test_missing_full_snapshot_is_not_latest_value(tmp_path):
    from contract_driven_ai_flow.research.models import ObservationEvent, SnapshotRef, ValueDescriptor
    from contract_driven_ai_flow.research.store import ExperimentStore

    store = ExperimentStore(tmp_path)
    run = store.create_run("analysis.py", interpreter="python", source_digest="abc")
    descriptor = ValueDescriptor(kind="matrix", backend="numpy", type_name="ndarray", shape=[2, 2], dtype="float64")
    snap = SnapshotRef(id="one", run_id=run["id"], binding_id="X", scope_id="main", name="X", version=1, descriptor=descriptor,
                       sample={"values": [[1, 2], [3, 4]]}, fidelity="sampled")
    store.append([ObservationEvent(run_id=run["id"], kind="value.observed", snapshot_id="one", payload={"snapshot": snap.model_dump(mode="json")})])
    newer = snap.model_copy(update={"id": "two", "version": 2, "sample": {"values": [[9, 9], [9, 9]]}})
    store.append([ObservationEvent(run_id=run["id"], kind="value.observed", snapshot_id="two", payload={"snapshot": newer.model_dump(mode="json")})])
    assert store.snapshot("one").sample["values"][0][0] == 1
    assert store.slice("one", []).get("available") is False
    assert store.slice("one", []).get("reason") == "This observation did not save the complete value"


def test_unknown_fields_are_rejected_and_events_are_strict_json():
    from contract_driven_ai_flow.research.models import ObservationEvent, ValueDescriptor
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ValueDescriptor(kind="tensor", backend="custom", type_name="T", undocumented_field="x")
    with pytest.raises((ValueError, ValidationError)):
        ObservationEvent(run_id="r", kind="value.observed", payload={"mean": float("nan")})


def test_terminal_state_and_snapshots_persist_atomically(tmp_path):
    from contract_driven_ai_flow.research.models import ObservationEvent
    from contract_driven_ai_flow.research.store import ExperimentStore

    store = ExperimentStore(tmp_path)
    run = store.create_run("analysis.py", interpreter="python", source_digest="abc")
    store.append([ObservationEvent(run_id=run["id"], kind="run.finished", payload={"status": "failed", "error": {"type": "ValueError", "line": 12}})])
    restored = ExperimentStore(tmp_path).run(run["id"])
    assert restored["status"] == "failed" and restored["finished"]
    assert restored["summary"]["error"]["line"] == 12
    assert len(store.events(run["id"])) == 1


def test_unknown_snapshot_and_cross_run_envelope_are_rejected(tmp_path):
    from contract_driven_ai_flow.research.models import ObservationEvent
    from contract_driven_ai_flow.research.store import ExperimentStore

    store = ExperimentStore(tmp_path)
    with pytest.raises(LookupError):
        store.snapshot("../outside")
    with pytest.raises(ValueError):
        store.append([ObservationEvent(run_id="missing", kind="run.finished", payload={"status": "completed"})])
