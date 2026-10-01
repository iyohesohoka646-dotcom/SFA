from pathlib import Path
import json
from contract_driven_ai_flow.models import ProjectSpec, ChangeSet, RunEvent

root = Path(__file__).resolve().parents[1]
target = root / "src/contract_driven_ai_flow/schemas"
target.mkdir(parents=True, exist_ok=True)
for name, model in (("project", ProjectSpec), ("change", ChangeSet), ("event", RunEvent)):
    (target / f"{name}.json").write_text(json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
