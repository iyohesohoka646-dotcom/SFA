import json
import time
from pathlib import Path

import numpy as np


PLUGIN = Path(__file__).parent / "fixtures/probe_plugins.py"


def snapshot(value):
    from contract_driven_ai_flow.research.agent.sdk import TraceSession
    from contract_driven_ai_flow.research.models import SnapshotRef
    return SnapshotRef.model_validate(TraceSession("plugin").watch("X", value))


def test_custom_probe_cannot_mutate_analysis_array():
    from contract_driven_ai_flow.research.probe_registry import ProbeRegistry
    from contract_driven_ai_flow.research.probes import ProbePool
    from contract_driven_ai_flow.research.models import ProbeSpec

    value = np.ones((2, 2))
    registry = ProbeRegistry()
    registry.register("test.mutate", str(PLUGIN) + ":MutationProbe")
    with ProbePool(registry) as pool:
        result = pool.evaluate(ProbeSpec(id="x", kind="test.mutate"), snapshot(value))
    assert result.status == "error"
    np.testing.assert_array_equal(value, np.ones((2, 2)))


def test_slow_probe_times_out_without_stopping_analysis():
    from contract_driven_ai_flow.research.probe_registry import ProbeRegistry
    from contract_driven_ai_flow.research.probes import ProbePool
    from contract_driven_ai_flow.research.models import ProbeSpec

    registry = ProbeRegistry()
    registry.register("test.slow", str(PLUGIN) + ":SlowProbe")
    registry.register("test.ok", str(PLUGIN) + ":SafeProbe")
    with ProbePool(registry) as pool:
        slow = pool.evaluate(ProbeSpec(id="slow", kind="test.slow", budget_ms=50), snapshot(np.ones(3)))
        healthy = pool.evaluate(ProbeSpec(id="ok", kind="test.ok", budget_ms=200), snapshot(np.ones(3)))
    assert slow.status == "error" and slow.evidence["reason"] == "timeout"
    assert healthy.status == "pass"
    assert np.sum(np.arange(10)) == 45


def test_worker_is_reused_and_plugin_output_is_redacted():
    from contract_driven_ai_flow.research.probe_registry import ProbeRegistry
    from contract_driven_ai_flow.research.probes import ProbePool
    from contract_driven_ai_flow.research.models import ProbeSpec

    registry = ProbeRegistry()
    registry.register("test.ok", str(PLUGIN) + ":SafeProbe")
    with ProbePool(registry, max_workers=1) as pool:
        first = pool.evaluate(ProbeSpec(id="first", kind="test.ok", budget_ms=200), snapshot(np.ones(3)))
        next_result = pool.evaluate(ProbeSpec(id="next", kind="test.ok", budget_ms=200), snapshot(np.ones(3)))
    assert first.evidence["pid"] == next_result.evidence["pid"]
    encoded = json.dumps(first.model_dump(mode="json"))
    assert "person@example.org" not in encoded and "hunter2" not in encoded


def test_bounded_probe_queue_never_blocks_producer():
    from contract_driven_ai_flow.research.probe_registry import ProbeRegistry
    from contract_driven_ai_flow.research.probes import ProbePool
    from contract_driven_ai_flow.research.models import ProbeSpec

    registry = ProbeRegistry()
    registry.register("test.slow", str(PLUGIN) + ":SlowProbe")
    with ProbePool(registry, max_workers=1, max_pending=2) as pool:
        value = snapshot(np.ones(3))
        started = time.perf_counter()
        futures = [pool.submit(ProbeSpec(id=str(i), kind="test.slow", budget_ms=50), value) for i in range(10)]
        assert time.perf_counter() - started < 0.2
        results = [f.result(timeout=5) for f in futures]
    assert any(r.status == "skipped" and r.evidence.get("reason") == "queue_full" for r in results)


def test_sample_plugin_registers_without_core_modification():
    from contract_driven_ai_flow.research.probe_registry import ProbeRegistry
    from contract_driven_ai_flow.research.probes import ProbePool
    from contract_driven_ai_flow.research.models import ProbeSpec

    registry = ProbeRegistry()
    example = Path(__file__).parents[2] / "examples/research/custom-probe.py"
    registry.register("example.nonempty", str(example) + ":NonEmptyProbe")
    with ProbePool(registry) as pool:
        result = pool.evaluate(ProbeSpec(id="nonempty", kind="example.nonempty"), snapshot(np.ones((2, 3))))
    assert result.status == "pass" and result.fidelity == "metadata_only"


def test_explicit_rank_uses_exact_saved_artifact_in_worker(tmp_path):
    from contract_driven_ai_flow.research.agent.budget import CapturePolicy
    from contract_driven_ai_flow.research.agent.sdk import TraceSession
    from contract_driven_ai_flow.research.models import ProbeSpec, SnapshotRef
    from contract_driven_ai_flow.research.probes import ProbePool

    value = np.eye(4)
    captured = SnapshotRef.model_validate(TraceSession("rank", policy=CapturePolicy(level="full"), artifact_root=tmp_path).watch("X", value))
    value[:] = 0
    with ProbePool(artifact_root=tmp_path) as pool:
        result = pool.evaluate(ProbeSpec(id="rank", kind="rank", parameters={"enable_expensive": True, "min": 4}, budget_ms=200), captured)
    assert result.status == "pass" and result.fidelity == "exact"
    assert result.evidence["rank"] == 4


def test_expensive_probe_refuses_unavailable_complete_history():
    from contract_driven_ai_flow.research.models import ProbeSpec
    from contract_driven_ai_flow.research.probes import ProbePool

    with ProbePool() as pool:
        result = pool.evaluate(ProbeSpec(id="rank", kind="rank", parameters={"enable_expensive": True}), snapshot(np.eye(3)))
    assert result.status == "unknown"


def test_expensive_probe_does_not_read_path_outside_store(tmp_path):
    from contract_driven_ai_flow.research.models import ProbeSpec
    from contract_driven_ai_flow.research.probes import ProbePool

    captured = snapshot(np.eye(3)).model_copy(update={"artifact_ref": "../outside.npy"})
    with ProbePool(artifact_root=tmp_path) as pool:
        result = pool.evaluate(ProbeSpec(id="rank", kind="rank", parameters={"enable_expensive": True}), captured)
    assert result.status == "error"
