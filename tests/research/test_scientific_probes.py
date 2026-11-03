import numpy as np
import pytest


def observed(value):
    from contract_driven_ai_flow.research.agent.sdk import TraceSession
    from contract_driven_ai_flow.research.models import SnapshotRef
    return SnapshotRef.model_validate(TraceSession("probe").watch("X", value))


def test_sampled_finite_check_does_not_claim_full_pass():
    from contract_driven_ai_flow.research.probes import evaluate_probe
    from contract_driven_ai_flow.research.models import ProbeSpec

    result = evaluate_probe(ProbeSpec(id="finite"), observed(np.ones((100, 100))))
    assert result.status == "unknown" and result.fidelity == "sampled"
    assert result.evidence["sample_passed"] is True
    assert result.evidence["sample_count"] <= 4096


def test_full_finite_pass_and_sampled_invalid_witness_are_distinct():
    from contract_driven_ai_flow.research.probes import evaluate_probe
    from contract_driven_ai_flow.research.models import ProbeSpec

    rule = ProbeSpec(id="finite")
    assert evaluate_probe(rule, observed(np.ones((4, 4)))).status == "pass"
    value = np.ones((100, 100))
    value[0, 0] = np.inf
    result = evaluate_probe(rule, observed(value))
    assert result.status == "fail" and result.fidelity == "sampled"
    assert result.evidence["inf_count"] >= 1


def test_shape_and_broadcast_diagnostics_use_real_dimensions():
    from contract_driven_ai_flow.research.probes import evaluate_probe
    from contract_driven_ai_flow.research.models import ProbeSpec

    snapshot = observed(np.zeros((2, 3)))
    matched = evaluate_probe(ProbeSpec(id="shape", kind="shape", parameters={"expected": [None, 3]}), snapshot)
    assert matched.status == "pass" and matched.fidelity == "metadata_only"
    broadcast = evaluate_probe(ProbeSpec(id="broadcast", kind="broadcast", parameters={"other_shape": [4, 5]}), snapshot)
    assert broadcast.status == "fail" and broadcast.evidence["actual_shape"] == [2, 3]
    matmul = evaluate_probe(ProbeSpec(id="matmul", kind="dimensions", parameters={"other_shape": [3, 4], "operation": "matmul"}), snapshot)
    assert matmul.status == "pass" and matmul.evidence["output_shape"] == [2, 4]


def test_expensive_rank_probe_requires_explicit_enable():
    from contract_driven_ai_flow.research.probes import evaluate_probe
    from contract_driven_ai_flow.research.models import ProbeSpec

    result = evaluate_probe(ProbeSpec(id="rank", kind="rank"), observed(np.eye(4)))
    assert result.status == "skipped" and "explicit" in result.message.casefold()


@pytest.mark.parametrize("kind,parameters,value,status", [
    ("dtype", {"expected": "float64"}, np.ones(3), "pass"),
    ("range", {"min": 0, "max": 5}, np.array([1, 9]), "fail"),
    ("variance", {"min": 0.01}, np.ones(5), "fail"),
    ("missing", {"max_ratio": 0}, np.array([1.0, np.nan]), "fail"),
    ("symmetry", {}, np.eye(4), "pass"),
    ("symmetry", {}, np.array([[1, 2], [3, 4]]), "fail"),
    ("capture_size", {"max_bytes": 10}, np.ones((10, 10)), "fail"),
])
def test_builtin_scientific_diagnostics(kind, parameters, value, status):
    from contract_driven_ai_flow.research.probes import evaluate_probe
    from contract_driven_ai_flow.research.models import ProbeSpec

    result = evaluate_probe(ProbeSpec(id=kind, kind=kind, parameters=parameters), observed(value))
    assert result.status == status
    assert result.snapshot_id and result.duration_ms >= 0


def test_bad_probe_configuration_is_error_not_pass():
    from contract_driven_ai_flow.research.probes import evaluate_probe
    from contract_driven_ai_flow.research.models import ProbeSpec

    result = evaluate_probe(ProbeSpec(id="shape", kind="shape", parameters={"expected": "not a shape"}), observed(np.zeros((2, 3))))
    assert result.status == "error"


def test_control_policy_is_separate_and_unknown_gate_pauses():
    from contract_driven_ai_flow.research.probes import control_action
    from contract_driven_ai_flow.research.models import ProbeResult, ProbeSpec

    failure = ProbeResult(probe_id="x", snapshot_id="s", status="fail")
    unknown = failure.model_copy(update={"status": "unknown"})
    assert control_action(ProbeSpec(id="x", policy="continue"), failure) is None
    assert control_action(ProbeSpec(id="x", policy="cancel"), failure) == "cancel"
    assert control_action(ProbeSpec(id="x", policy="cancel"), unknown) == "pause"
