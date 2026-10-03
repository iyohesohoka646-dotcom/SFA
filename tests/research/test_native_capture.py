import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def session(**kwargs):
    from contract_driven_ai_flow.research.agent.sdk import TraceSession
    from contract_driven_ai_flow.research.agent.transport import EventTransport

    return TraceSession("test", EventTransport(), **kwargs)


def test_watch_preserves_array_identity_and_contents():
    value = np.arange(60, dtype="float32").reshape(10, 6)
    original = value.copy()
    pointer = value.__array_interface__["data"][0]
    trace = session()
    snapshot = trace.watch("X", value, axes=("sample", "feature"))
    assert snapshot["descriptor"]["shape"] == [10, 6]
    assert snapshot["descriptor"]["dtype"] == "float32"
    assert snapshot["descriptor"]["axes"] == ["sample", "feature"]
    assert value.__array_interface__["data"][0] == pointer
    np.testing.assert_array_equal(value, original)


def test_observed_view_sample_is_frozen():
    value = np.arange(12).reshape(3, 4)
    trace = session()
    first = trace.watch("view", value[:, ::2])
    original = json.dumps(first, allow_nan=False)
    value[:] = 99
    next_value = trace.watch("view", value[:, ::2])
    assert json.dumps(first, allow_nan=False) == original
    assert first["version"] == 1 and next_value["version"] == 2
    assert first["sample"]["values"] != next_value["sample"]["values"]


def test_large_strided_array_does_not_call_tolist_or_copy_full():
    class GuardedArray(np.ndarray):
        def tolist(self):
            raise AssertionError("whole-array JSON conversion")

        def copy(self, *args, **kwargs):
            raise AssertionError("whole-array copy")

        def ravel(self, *args, **kwargs):
            raise AssertionError("strided whole-array flatten")

    value = np.arange(1_000_000).reshape(1000, 1000).view(GuardedArray)[::2, ::3]
    trace = session()
    snapshot = trace.watch("strided", value)
    assert snapshot["descriptor"]["shape"] == [500, 334]
    assert snapshot["statistics"]["sample_count"] <= 4096
    assert snapshot["statistics"]["exact"] is False
    assert sum(map(len, snapshot["sample"]["values"])) <= 1024
    assert snapshot["fidelity"] == "sampled" and snapshot["artifact_ref"] is None


def test_complex_and_nullable_dataframe_have_typed_preview():
    trace = session()
    complex_value = trace.watch("z", np.array([1 + 2j, np.nan + 3j]))
    assert complex_value["sample"]["values"][0][0] == {"type": "complex", "real": 1.0, "imag": 2.0}
    frame = pd.DataFrame({"count": pd.Series([1, pd.NA], dtype="Int64"), "group": pd.Categorical(["a", "b"]), "time": pd.to_datetime(["2025-01-01", None])})
    observed = trace.watch("frame", frame)
    assert observed["descriptor"]["kind"] == "table"
    assert observed["descriptor"]["metadata"]["columns"][0]["dtype"] == "Int64"
    assert observed["sample"]["values"][1][0] is None
    assert observed["sample"]["values"][0][2]["type"] == "datetime"
    json.dumps(observed, allow_nan=False)


def test_zero_dimensional_empty_and_high_dimensional_values():
    trace = session()
    zero = trace.watch("scalar", np.array(7.0))
    empty = trace.watch("empty", np.zeros((0, 4)))
    tensor = trace.watch("tensor", np.zeros((2, 3, 4, 5)))
    assert zero["descriptor"]["shape"] == [] and zero["sample"]["values"] == [[7.0]]
    assert empty["statistics"]["population_count"] == 0
    assert empty["sample"]["values"] == []
    assert tensor["sample"]["fixed_axes"] == {"0": 0, "1": 0}


def test_observations_do_not_advance_user_random_generator():
    trace = session()
    np.random.seed(314)
    expected = np.random.random(4)
    np.random.seed(314)
    trace.watch("large", np.arange(50_000))
    np.testing.assert_array_equal(np.random.random(4), expected)


def test_unknown_lazy_value_does_not_compute_or_repr():
    class Lazy:
        @property
        def shape(self):
            raise AssertionError("shape property executed")

        def __repr__(self):
            raise AssertionError("repr executed")

        def __array__(self):
            raise AssertionError("lazy value computed")

    observed = session().watch("lazy", Lazy())
    assert observed["descriptor"]["backend"] == "unknown"
    assert observed["fidelity"] == "metadata_only"
    assert observed["sample"] == {} and not observed["descriptor"]["capabilities"]


def test_third_party_adapter_without_core_changes():
    from contract_driven_ai_flow.research.agent.registry import AdapterRegistry

    path = Path(__file__).parents[2] / "examples/research/custom-adapter.py"
    spec = importlib.util.spec_from_file_location("research_custom_adapter_example", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    registry = AdapterRegistry()
    registry.register(module.PointCloudAdapter())
    observed = session(registry=registry).watch("points", module.PointCloud(((1.0, 2.0), (3.0, 4.0))))
    assert observed["descriptor"]["backend"] == "example.pointcloud"
    assert observed["descriptor"]["kind"] == "point-cloud"
    assert observed["sample"]["values"] == [[1.0, 2.0], [3.0, 4.0]]
    assert "preview" in observed["descriptor"]["capabilities"]


def test_sensitive_values_are_redacted_before_transport(tmp_path):
    from contract_driven_ai_flow.research.agent.budget import CapturePolicy

    trace = session(policy=CapturePolicy(level="full"), artifact_root=tmp_path)
    private = trace.watch("api_secret", np.array([9012]))
    table = trace.watch("contacts", pd.DataFrame({"email": ["person@example.org"], "value": [4]}))
    assert private["sample"] == {} and private["statistics"] == {}
    assert private["artifact_ref"] is None and private["redacted"]
    assert table["sample"]["values"][0][0] == "[REDACTED]"
    encoded = json.dumps(trace.transport.drain())
    assert "person@example.org" not in encoded and "9012" not in encoded


def test_agent_imports_without_application_dependencies():
    import subprocess

    script = "import sys; sys.path.insert(0, 'src'); from contract_driven_ai_flow.research.agent.sdk import TraceSession; assert not any(x in sys.modules for x in ('pydantic', 'fastapi', 'typer', 'textual'))"
    result = subprocess.run([sys.executable, "-S", "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_explicit_operation_connects_inputs_and_outputs():
    trace = session()
    trace.watch("X", np.ones((2, 3)))
    with trace.operation("mean(axis=0)", inputs={"X": np.ones((2, 3))}) as operation:
        result = trace.watch("mean", np.ones(3), parents=("X",))
    events = trace.transport.drain()
    record = next(e["payload"]["operation"] for e in events if e["kind"] == "operation.finished")
    assert record["id"] == operation["id"]
    assert len(record["input_snapshots"]) == 1
    assert record["output_snapshots"] == [result["id"]]
    assert record["status"] == "completed" and record["duration_ms"] >= 0


def test_large_fixed_width_cells_use_metadata_without_copying_samples():
    value = np.zeros((4, 4), dtype="U100000")
    observed = session().watch("large_cells", value)
    assert observed["descriptor"]["shape"] == [4, 4]
    assert observed["fidelity"] == "metadata_only" and observed["sample"] == {}
    assert "cell_byte_limit" in observed["truncation"]


def test_complex_magnitude_overflow_does_not_invent_nonfinite_components():
    value = np.array([complex(1.7e308, 1.7e308)])
    observed = session().watch("large_complex", value)
    assert observed["statistics"]["finite_count"] == 1
    assert observed["statistics"]["inf_count"] == 0
    assert observed["statistics"]["numeric_metric"] == "magnitude"


def test_numeric_table_nonfinite_counts_do_not_become_a_finite_pass():
    from contract_driven_ai_flow.research.models import ProbeSpec, SnapshotRef
    from contract_driven_ai_flow.research.probes import evaluate_probe

    observed = session().watch("frame", pd.DataFrame({"measurement": [1.0, np.nan, np.inf]}))
    assert observed["statistics"]["finite_count"] == 1
    assert observed["statistics"]["nan_count"] == 1
    assert observed["statistics"]["inf_count"] == 1
    assert observed["statistics"]["exact"] is True
    result = evaluate_probe(ProbeSpec(id="finite", kind="finite"), SnapshotRef.model_validate(observed))
    assert result.status == "fail"


def test_mixed_table_statistics_cannot_certify_all_cells_as_numeric():
    observed = session().watch("frame", pd.DataFrame({"number": [1.0, 2.0], "label": ["a", "b"]}))
    assert observed["statistics"]["exact"] is False
    assert observed["statistics"]["numeric_sample_count"] == 2
