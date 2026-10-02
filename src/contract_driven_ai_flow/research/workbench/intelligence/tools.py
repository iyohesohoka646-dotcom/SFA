from pathlib import Path

from ...agent.privacy import sanitize_json
from ..analysis import analyze_source

READ_TOOLS = {
    "analysis.list": (
        "Page source objects and candidate relationships; reads remain separately authorized",
        {},
    ),
    "source.read": (
        "Read a scoped symbol/assignment at the frozen source digest",
        {"object_id": "string"},
    ),
    "snapshot.describe": (
        "Describe an authorized snapshot without raw values",
        {"snapshot_id": "string"},
    ),
    "sample.read": (
        "Read a bounded sanitized sample if policy allows it",
        {"snapshot_id": "string"},
    ),
    "relations.read": (
        "Read direct snapshot relationships and provenance",
        {"snapshot_id": "string"},
    ),
    "outputs.list": ("Read selected evidence’s probe outputs", {}),
    "tools.catalog": ("Public drawing tools, availability and adapter contracts", {}),
    "tools.describe": (
        "Explicit isolated introspection of an installed public plotting adapter",
        {"tool_id": "string"},
    ),
    "skill.read": (
        "Read an explicitly registered Skill snapshot",
        {"skill_id": "string"},
    ),
}


class HarnessToolRegistry:
    def __init__(self, workbench, context, skills):
        self.workbench, self.context, self.skills = workbench, context, skills

    def describe(self, request):
        definitions = dict(READ_TOOLS)
        if not request.policy.include_samples:
            definitions.pop("sample.read")
        if request.policy.role in ("parse", "probe", "code"):
            definitions["plan.prepare"] = (
                "Prepare a frozen plan without running it",
                {},
            )
            definitions["resource.propose"] = (
                "Stage a validated declarative probe/adapter manifest for human review; cannot enable or execute it",
                {"manifest": "string"},
            )
        if request.policy.allow_execute and request.policy.role in ("probe", "code"):
            definitions["plan.execute"] = (
                "Execute one prepared frozen plan and record its task",
                {"plan_id": "string"},
            )
        if request.policy.role == "code":
            definitions["code.propose"] = (
                "Propose a scoped inert code fragment for human review",
                {"object_id": "string", "candidate": "string"},
            )
        result = [
            {
                "name": name,
                "description": description,
                "arguments": {
                    "type": "object",
                    "properties": {k: {"type": v} for k, v in fields.items()},
                    "required": list(fields),
                    "additionalProperties": False,
                },
            }
            for name, (description, fields) in definitions.items()
        ]
        next(d for d in result if d["name"] == "analysis.list")["arguments"][
            "properties"
        ] = {
            "offset": {"type": "integer", "minimum": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 32},
        }
        return result

    def call(self, name, arguments, request):
        import jsonschema

        definitions = {tool["name"]: tool for tool in self.describe(request)}
        if name not in definitions:
            raise ValueError("Tool is not registered for this task role")
        jsonschema.validate(arguments, definitions[name]["arguments"])
        analysis = self.context.validate_source(request.analysis_id)
        reference = name
        if name == "source.read":
            key = arguments["object_id"]
            if key not in self.context.authorized_objects(analysis, request):
                raise ValueError("Object is outside this task’s source scope")
            obj = next(
                (
                    obj
                    for obj in analysis.objects
                    if obj.id == key and obj.kind != "class"
                ),
                None,
            )
            if obj is None:
                raise ValueError("Source object is unavailable")
            data = obj.model_dump(mode="json")
            reference = "source:" + key
        elif name == "analysis.list":
            offset = arguments.get("offset", 0)
            limit = arguments.get("limit", 16)
            page = analysis.objects[offset : offset + limit]
            ids = {o.id for o in page}
            allowed = self.context.authorized_objects(analysis, request)
            data = {
                "objects": [
                    {
                        **o.model_dump(exclude={"code"}, mode="json"),
                        "readable": o.id in allowed,
                    }
                    for o in page
                ],
                "relations": [
                    r.model_dump(mode="json")
                    for r in analysis.relations
                    if r.source in ids or r.target in ids
                ][:64],
                "partial": offset + limit < len(analysis.objects),
                "total": len(analysis.objects),
                "next_offset": (
                    offset + limit if offset + limit < len(analysis.objects) else None
                ),
            }
            reference = "analysis:" + analysis.id
        elif name.startswith("snapshot.") or name in ("sample.read", "relations.read"):
            key = arguments["snapshot_id"]
            if not request.snapshot_id:
                raise ValueError("This task has no authorized snapshot focus")
            neighbors = self.workbench.relationships(request.snapshot_id).data
            allowed = {
                request.snapshot_id,
                *(s["id"] for s in neighbors["parents"]),
                *(s["id"] for s in neighbors["consumers"]),
            }
            if key not in allowed:
                raise ValueError("Snapshot is outside this task’s evidence scope")
            snapshot = self.workbench.research.store.snapshot(key)
            if name == "relations.read":
                data = self.workbench.relationships(key).model_dump(mode="json")
                reference = "relations:" + key
            elif name == "sample.read":
                data = {
                    "id": key,
                    "sample": snapshot.sample,
                    "fidelity": snapshot.fidelity,
                    "coverage": snapshot.coverage,
                    "redacted": snapshot.redacted,
                }
                reference = "sample:" + key
            else:
                data = snapshot.model_dump(mode="json", exclude={"sample"})
                reference = "snapshot:" + key
        elif name == "outputs.list":
            data = (
                self.workbench.outputs(
                    run_id=request.run_id, snapshot_id=request.snapshot_id
                )[:32]
                if request.run_id or request.snapshot_id
                else []
            )
        elif name == "tools.catalog":
            data = self.workbench.tools.catalog()
        elif name == "tools.describe":
            data = self.workbench.tools.describe(arguments["tool_id"])
            reference = "drawing-methods:" + arguments["tool_id"]
        elif name == "resource.propose":
            import json

            data = self.workbench.resources.import_manifest(
                json.loads(arguments["manifest"])
            ).model_dump(mode="json")
            reference = "resource-draft:" + data["id"]
        elif name == "skill.read":
            data = self.skills.load(arguments["skill_id"])
            reference = "skill:" + data["id"]
        elif name == "plan.prepare":
            data = self.workbench.plan(analysis.id).model_dump(mode="json")
            reference = "plan:" + data["id"]
        elif name == "plan.execute":
            plan = self.workbench.store.get("plans", arguments["plan_id"])
            if plan["analysis_id"] != request.analysis_id:
                raise ValueError("Plan belongs to another analysis")
            data = self.workbench.execute(arguments["plan_id"]).model_dump(mode="json")
            reference = "task:" + data["id"]
        elif name == "code.propose":
            if arguments["object_id"] not in self.context.authorized_objects(
                analysis, request
            ):
                raise ValueError("Proposal target is outside task scope")
            data = self.workbench.changes.propose(
                analysis.id, arguments["object_id"], arguments["candidate"]
            ).model_dump(mode="json")
            reference = "proposal:" + data["id"]
        else:
            raise ValueError("Tool implementation unavailable")
        return sanitize_json({"reference": reference, "result": data})
