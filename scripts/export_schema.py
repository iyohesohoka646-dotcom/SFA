from pathlib import Path
import json
from contract_driven_ai_flow.models import ProjectSpec, ChangeSet, RunEvent
from pydantic import create_model
from contract_driven_ai_flow.research.models import SourceRef, ValueDescriptor, SnapshotRef, OperationRecord, ObservationEvent, ProbeSpec, ProbeResult, Explanation

root = Path(__file__).resolve().parents[1]
target = root / "src/contract_driven_ai_flow/schemas"
target.mkdir(parents=True, exist_ok=True)
for name, model in (("project", ProjectSpec), ("change", ChangeSet), ("event", RunEvent)):
    (target / f"{name}.json").write_text(json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
protocol = create_model("ResearchProtocol", **{model.__name__: (model, ...) for model in (SourceRef, ValueDescriptor, SnapshotRef, OperationRecord, ObservationEvent, ProbeSpec, ProbeResult, Explanation)})
(target / "research.json").write_text(json.dumps(protocol.model_json_schema(mode="serialization"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
from contract_driven_ai_flow.settings.models import ProviderProfile, PublicProviderProfile, ConnectionResult
model_protocol = create_model("ModelsProtocol", **{model.__name__: (model, ...) for model in (ProviderProfile, PublicProviderProfile, ConnectionResult)})
(target / "models.json").write_text(json.dumps(model_protocol.model_json_schema(mode="serialization"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
