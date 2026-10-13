"""Preview-first, non-destructive SFA migration. Ambiguity requires explicit bindings."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml

from .compiler import compile_project
from .models import Contract, ModuleSpec, PortBinding, ProbeSpec, ProjectSpec, Source, SymbolRef
from .paths import FlowError, inside
from .privacy import sanitize, sanitize_project
from .storage import Store, atomic_write


def migrate(source: Path, destination: Path | None = None, resolutions: dict | None = None, apply=False) -> dict:
    source = source.resolve()
    destination = (destination or source.with_name(source.name + "-cdaf")).resolve()
    if destination == source or destination.is_relative_to(source):
        raise FlowError("Migration destination must be a separate directory outside the old project")
    if apply and destination.exists() and any(destination.iterdir()):
        raise FlowError("Migration never overwrites an existing project")
    topology = yaml.safe_load((source / ".sfa/pipeline.yml").read_text(encoding="utf-8"))
    resolutions = resolutions or {}
    issues, modules, bindings, probes, input_properties = [], [], [], [], {}
    old_modules = {m["id"]: m for m in topology.get("modules", []) if m.get("type") != "composite"}
    for mid, old in old_modules.items():
        path = inside(source, old.get("contract", f".sfa/modules/{mid}/contract.json"))
        contract = json.loads(path.read_text(encoding="utf-8"))
        inp = contract.get("input_schema", {"type": "object", "properties": {}})
        if not inp.get("properties") and inp.get("additionalProperties") is not False:
            issues.append({"code": "input_contract", "module": mid, "message": "Review input properties before migration"})
        modules.append(ModuleSpec(id=mid, name=old.get("name", mid), symbol=SymbolRef(path=old["path"], qualname=old["entry"]),
                                  description=contract.get("natural_summary", ""), contract=Contract(input=inp, output=contract.get("output_schema", {}))))
    by_id = {m.id: m for m in modules}
    for module in modules:
        incoming = [p for p in topology.get("pipes", []) if p["target"] == module.id]
        for port, schema in module.contract.input.get("properties", {}).items():
            key = module.id + "." + port
            dynamic = False
            if key in resolutions:
                setting = resolutions[key]
                src = Source.model_validate(setting.get("source", setting))
                dynamic = bool(setting.get("dynamic", False))
            elif not incoming:
                src = Source(kind="project", pointer="/" + port)
                input_properties[port] = schema
            else:
                candidates = [p for p in incoming if p["source"] in by_id and port in by_id[p["source"]].contract.output.get("properties", {})]
                unknown = [p for p in incoming if p["source"] not in by_id or not by_id[p["source"]].contract.output.get("properties")]
                if len(candidates) != 1 or unknown:
                    issues.append({"code": "ambiguous_binding", "module": module.id, "port": port, "resolution_key": key,
                                   "candidates": [p["source"] for p in incoming], "message": "Specify project/module/literal source and pointer; pipe order is not a binding policy"})
                    continue
                src = Source(kind="module", module=candidates[0]["source"], pointer="/" + port)
            if src.kind == "project":
                if src.pointer.count("/") == 1:
                    input_properties.setdefault(src.pointer[1:].replace("~1", "/").replace("~0", "~"), schema)
            visibility = incoming[0].get("visibility", "L2") if len(incoming) == 1 else "L2"
            bindings.append(PortBinding(id=f"migrated_{module.id}_{port}", target=module.id, port=port, source=src, dynamic=dynamic, visibility=visibility, provenance="migrated"))
    pipes = {p["id"]: p for p in topology.get("pipes", [])}
    for path in (source / ".sfa/probes").glob("*.yml"):
        old = yaml.safe_load(path.read_text(encoding="utf-8"))
        pipe = pipes.get(old.get("pipe"))
        if pipe is None:
            issues.append({"code": "probe_pipe", "path": path.name, "message": "Probe refers to an unknown pipe"})
            continue
        probes.append(ProbeSpec(id=old.get("id", old.get("name", path.stem)), module=pipe["source"], kind="branch_observer" if old["type"] == "router" else "assertion",
                                expression=old.get("condition", "True"), true_target=old.get("on_true"), false_target=old.get("on_false")))
    project = ProjectSpec(name="Migrated SFA flow", input_schema={"type": "object", "properties": input_properties, "required": list(input_properties)}, modules=modules, bindings=bindings, probes=probes,
                          metadata={"migration": {"format": "sfa-0.1", "original_topology": topology, "legacy_groups": "Retained here and in the backup. Public composite ports must be reviewed before restoring hierarchy.", "legacy_evidence": "Historical IDs retained; original graph/source versions are unknown."}})
    diagnostics = compile_project(project).diagnostics
    issues.extend(d.model_dump() for d in diagnostics if d.severity == "error")
    report = {"source": str(source), "destination": str(destination), "applied": False,
              "issues": sanitize(issues, project.capture.sensitive_fields),
              "diagnostics": sanitize([d.model_dump() for d in diagnostics], project.capture.sensitive_fields),
              "project": sanitize_project(project),
              "legacy_runs": [p.name for p in (source / ".sfa/snapshots").iterdir() if p.is_dir()] if (source / ".sfa/snapshots").exists() else []}
    if apply and not issues:
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source / ".sfa", destination / "legacy/.sfa")
        if (source / "sfa.yml").exists():
            shutil.copy2(source / "sfa.yml", destination / "legacy/sfa.yml")
        for relative in {m.symbol.path for m in modules}:
            target = inside(destination, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(inside(source, relative), target)
        store = Store(destination)
        store.save(project, None)
        for run_id in report["legacy_runs"]:
            for snapshot in (source / ".sfa/snapshots" / run_id).glob("*.json"):
                value = json.loads(snapshot.read_text(encoding="utf-8"))
                store.artifact({"legacy_run_id": run_id, "file": snapshot.name, "version_status": "legacy_unknown", "evidence": sanitize(value, project.capture.sensitive_fields)}, project.capture.sensitive_fields)
        report["applied"] = True
        atomic_write(destination / "flow/migration-report.json", json.dumps(report, ensure_ascii=False, indent=2))
        atomic_write(destination / ".gitignore", ".cdaf/\nlegacy/\n__pycache__/\n")
    return report
