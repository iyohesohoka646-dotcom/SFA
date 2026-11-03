from pathlib import Path
import pytest

from contract_driven_ai_flow.examples import create_example
from contract_driven_ai_flow.models import RunEvent
from contract_driven_ai_flow.storage import Store, now


def test_archify_adapter_uses_typed_ir_and_keeps_relations(tmp_path):
    from contract_driven_ai_flow.adapters import archify_ir
    root = create_example(tmp_path / "demo")
    ir = archify_ir(root)
    assert ir["schema_version"] == 1 and ir["diagram_type"] == "architecture"
    assert len(ir["components"]) == 4 and len(ir["connections"]) == 3
    assert all(c["type"] == "backend" for c in ir["components"])
    assert "Design" in ir["meta"]["subtitle"]


def test_otel_attempts_have_causal_links_and_quality_events(tmp_path):
    from contract_driven_ai_flow.adapters import otel_payload
    root = create_example(tmp_path / "demo")
    store = Store(root)
    project = store.load()
    rid = store.create_run(project, {})
    upstream = store.event(RunEvent(run_id=rid, time=now(), kind="module.started", revision=project.revision, module="ingest", attempt=1), [])
    store.event(RunEvent(run_id=rid, time=now(), kind="module.completed", revision=project.revision, module="ingest", attempt=1), [])
    store.event(RunEvent(run_id=rid, time=now(), kind="module.started", revision=project.revision, module="normalize", attempt=1, links=[{"module": "ingest", "binding": "edge", "sequence": upstream.sequence}]), [])
    store.event(RunEvent(run_id=rid, time=now(), kind="probe.result", revision=project.revision, module="normalize", attempt=1, data={"status": "fail", "probe": "quality"}), [])
    store.event(RunEvent(run_id=rid, time=now(), kind="module.completed", revision=project.revision, module="normalize", attempt=1), [])
    store.finish(rid, "completed", "failed")
    spans = otel_payload(root, rid)["resourceSpans"][0]["scopeSpans"][0]["spans"]
    downstream = next(s for s in spans if s["name"] == "normalize")
    assert downstream["links"][0]["spanId"] == next(s for s in spans if s["name"] == "ingest")["spanId"]
    assert any(e["name"] == "probe.result" for e in downstream["events"])
    assert len(downstream["traceId"]) == 32 and len(downstream["spanId"]) == 16


def test_optional_sdk_export_preserves_recorded_time_and_status(tmp_path):
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from contract_driven_ai_flow.adapters import export_otel
    root = create_example(tmp_path / "sdk")
    store = Store(root)
    rid = store.create_run(store.load(), {})
    store.finish(rid, "completed", "failed")
    exporter = InMemorySpanExporter()
    export_otel(root, exporter, rid)
    exported = exporter.get_finished_spans()
    assert len(exported) == 1
    assert exported[0].attributes["cdaf.quality"] == "failed"
    assert exported[0].end_time >= exported[0].start_time
