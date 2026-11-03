import numpy as np
import pandas as pd
import pytest


def test_full_table_retains_typed_cells_and_redacts_artifact(tmp_path):
    pytest.importorskip("pyarrow")
    from contract_driven_ai_flow.research.agent.budget import CapturePolicy
    from contract_driven_ai_flow.research.agent.sdk import TraceSession
    from contract_driven_ai_flow.research.agent.transport import EventTransport
    from contract_driven_ai_flow.research.artifacts import read_slice
    from contract_driven_ai_flow.research.models import SnapshotRef

    frame = pd.DataFrame({"email": ["name@example.org"], "time": pd.to_datetime(["2025-01-01"]), "value": [1 + 2j]})
    trace = TraceSession("table", EventTransport(), CapturePolicy(level="full"), artifact_root=tmp_path)
    observed = trace.watch("table", frame)
    assert observed["artifact_ref"] is not None, observed["truncation"]
    assert not list((tmp_path / "artifacts").glob("*.partial"))
    result = read_slice(tmp_path, SnapshotRef.model_validate(observed), [])
    assert result["values"] == [["[REDACTED]", {"type": "datetime", "value": "2025-01-01T00:00:00"}, {"type": "complex", "real": 1.0, "imag": 2.0}]]
    assert b"name@example.org" not in (tmp_path / observed["artifact_ref"]).read_bytes()


def test_object_array_full_capture_cannot_write_pickle(tmp_path):
    from contract_driven_ai_flow.research.agent.budget import CapturePolicy
    from contract_driven_ai_flow.research.agent.sdk import TraceSession

    observed = TraceSession("object", policy=CapturePolicy(level="full"), artifact_root=tmp_path).watch("objects", np.array([object()], dtype=object))
    assert observed["artifact_ref"] is None
    assert "materialization_unsupported" in observed["truncation"]


def test_full_string_table_never_claims_truncated_preview_as_complete(tmp_path):
    pytest.importorskip("pyarrow")
    from contract_driven_ai_flow.research.agent.budget import CapturePolicy
    from contract_driven_ai_flow.research.agent.sdk import TraceSession
    from contract_driven_ai_flow.research.artifacts import read_slice
    from contract_driven_ai_flow.research.models import SnapshotRef

    text = "word" * 400
    observed = TraceSession("full string", policy=CapturePolicy(level="full"), artifact_root=tmp_path).watch("table", pd.DataFrame({"text": [text]}))
    result = read_slice(tmp_path, SnapshotRef.model_validate(observed), [])
    assert result["values"][0][0] == text
    assert "preview_text_truncated" in observed["truncation"]
    assert observed["fidelity"] == "sampled"


def test_inline_sensitive_text_is_marked_redacted():
    from contract_driven_ai_flow.research.agent.sdk import TraceSession

    observed = TraceSession("privacy").watch("addresses", np.array(["person@example.org"]))
    assert "[REDACTED_EMAIL]" in str(observed["sample"])
    assert observed["redacted"]
