"""A third-party data type, integrated without edits to the core registry."""
from dataclasses import dataclass

from contract_driven_ai_flow.research.agent.adapters import CaptureResult


@dataclass(frozen=True)
class PointCloud:
    points: tuple[tuple[float, float], ...]


class PointCloudAdapter:
    protocol_version = 1
    backend = "example.pointcloud"

    def supports(self, value):
        return type(value) is PointCloud

    def describe(self, value):
        return {"schema_version": 1, "kind": "point-cloud", "backend": self.backend, "type_name": "example.PointCloud",
                "shape": [len(value.points), 2], "dtype": "float64", "axes": ["point", "coordinate"],
                "capabilities": ["preview"], "metadata": {"coordinates": ["x", "y"]}}

    def capture(self, value, policy):
        if policy.level == "metadata":
            return CaptureResult(self.describe(value))
        count = min(len(value.points), policy.max_preview_cells // 2)
        return CaptureResult(self.describe(value), sample={"values": [list(v) for v in value.points[:count]]},
                             fidelity="exact" if count == len(value.points) else "sampled")


if __name__ == "__main__":
    import json
    from contract_driven_ai_flow.research.agent.registry import AdapterRegistry
    from contract_driven_ai_flow.research.agent.sdk import TraceSession

    registry = AdapterRegistry()
    registry.register(PointCloudAdapter())
    with TraceSession("Extensible point cloud", registry=registry) as trace:
        print(json.dumps(trace.watch("points", PointCloud(((1.0, 2.0), (3.0, 4.0)))), indent=2))
