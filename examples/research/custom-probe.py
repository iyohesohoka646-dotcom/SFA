"""Example third-party metadata probe; register explicitly in ProbeRegistry."""
from math import prod

from contract_driven_ai_flow.research.models import ProbeResult


class NonEmptyProbe:
    protocol_version = 1

    def evaluate(self, context):
        shape = context.descriptor.get("shape")
        return ProbeResult(probe_id=context.probe_id, snapshot_id=context.snapshot_id,
            status="unknown" if shape is None else "pass" if prod(shape) > 0 else "fail",
            fidelity="metadata_only", message="Checks observed dimensions; does not read data cells",
            evidence={"shape": list(shape) if shape is not None else None})
