"""Candidates stay inert until an explicit reviewed accept with matching versions."""
from __future__ import annotations

import ast
import difflib
import json
import uuid
from pathlib import Path

from .compiler import compile_project
from .models import ChangeSet, Diagnostic, ProjectSpec, canonical
from .paths import Conflict, FlowError, inside
from .privacy import sanitize_project
from .source import replace_body, symbol_text
from .storage import Store, file_digest, now


def diff(before: str, after: str, path: str) -> str:
    return "".join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), fromfile=path + " (before)", tofile=path + " (proposed)"))


def propose_architecture(root: Path, project: ProjectSpec, base_revision: str, title="Architecture proposal") -> ChangeSet:
    store = Store(root)
    current = store.load()
    if base_revision != current.revision:
        raise Conflict("Architecture proposal was based on an older project")
    plan = compile_project(project)
    change = ChangeSet(id=uuid.uuid4().hex, kind="architecture", base_revision=base_revision, created=now(), title=title,
                       project=project, diagnostics=plan.diagnostics, status="proposed" if plan.valid else "invalid",
                       diff=diff(json.dumps(sanitize_project(current), ensure_ascii=False, indent=2) + "\n", json.dumps(sanitize_project(project), ensure_ascii=False, indent=2) + "\n", "flow.yaml"))
    store.write_change(change)
    return change


def propose_implementation(root: Path, module_id: str, candidate: str, title="Module implementation", usage=None) -> ChangeSet:
    store = Store(root)
    project = store.load()
    module = next((m for m in project.modules if m.id == module_id), None)
    if module is None or module.symbol is None:
        raise FlowError("Implementation requires a Python module")
    path = inside(root, module.symbol.path)
    before = path.read_text(encoding="utf-8")
    if candidate.strip().startswith("```python") and candidate.strip().endswith("```"):
        candidate = candidate.strip()[9:-3].strip() + "\n"
    diagnostics, after = [], before
    try:
        after = replace_body(before, module.symbol.qualname, candidate, module.allowed_imports)
    except (SyntaxError, ValueError, FlowError) as exc:
        diagnostics.append(Diagnostic(code="patch_rejected", message=str(exc), module=module_id))
    change = ChangeSet(id=uuid.uuid4().hex, kind="implementation", base_revision=project.revision, base_source_digest=file_digest(before),
                       created=now(), title=title, module=module_id, before=before, after=after, usage=usage or {},
                       diff=diff(before, after, module.symbol.path), diagnostics=diagnostics, status="invalid" if diagnostics else "proposed")
    store.write_change(change)
    return change


def scaffold(module) -> str:
    name = module.symbol.qualname
    if "." in name:
        raise FlowError("New class/nested symbols must be supplied in source before accepting architecture")
    params = list(module.contract.input.get("properties", {}))
    if not all(p.isidentifier() for p in [name, *params]):
        raise FlowError("Python symbol and input names must be valid identifiers")
    return f"def {name}({', '.join(params)}):\n    \"\"\"{module.id}: implement the reviewed contract.\"\"\"\n    raise NotImplementedError('Generate and review this module before running')\n"


def accept(root: Path, change_id: str, expected_revision: str) -> ChangeSet:
    store = Store(root)
    with store.lock():
        store._recover_files()
        current = store._load()
        change = store.change(change_id)
        if change.status != "proposed":
            raise Conflict("Only a validated, pending proposal can be accepted")
        if current.revision != expected_revision or current.revision != change.base_revision:
            raise Conflict("Project changed during review; create a newly validated proposal")
        writes = {}
        if change.kind == "architecture":
            plan = compile_project(change.project)
            if not plan.valid:
                raise FlowError("Architecture no longer compiles")
            writes.update(store.project_writes(change.project))
            for module in change.project.modules:
                if module.symbol:
                    path = inside(root, module.symbol.path)
                    if not path.exists():
                        writes[module.symbol.path] = writes.get(module.symbol.path, "") + scaffold(module) + "\n"
        else:
            module = next(m for m in current.modules if m.id == change.module)
            path = inside(root, module.symbol.path)
            content = path.read_text(encoding="utf-8")
            if file_digest(content) != change.base_source_digest:
                raise Conflict("Source changed during review; regenerate the diff before applying")
            verified = replace_body(content, module.symbol.qualname, symbol_text(change.after, module.symbol.qualname), module.allowed_imports)
            if verified != change.after:
                raise FlowError("Stored candidate attempts to change unrelated code")
            writes[module.symbol.path] = verified
            if module.symbol.digest:
                module.symbol.digest = file_digest(symbol_text(verified, module.symbol.qualname))
                writes.update(store.project_writes(current))
        change.status = "accepted"
        writes[f"flow/changes/{change.id}.json"] = change.model_dump_json(indent=2)
        store.write_transaction(writes)
    return change


def reject(root: Path, change_id: str) -> ChangeSet:
    store = Store(root)
    with store.lock():
        change = store.change(change_id)
        if change.status not in ("proposed", "invalid"):
            raise Conflict("Change already reviewed")
        change.status = "rejected"
        store.write_change(change)
    return change


def propose_rollback(root: Path, change_id: str) -> ChangeSet:
    store = Store(root)
    old = store.change(change_id)
    if old.status != "accepted" or old.kind == "architecture":
        raise FlowError("Code rollback requires an accepted implementation change; architecture rollback uses a new architecture proposal")
    project = store.load()
    module = next(m for m in project.modules if m.id == old.module)
    content = inside(root, module.symbol.path).read_text(encoding="utf-8")
    if ast.dump(ast.parse(symbol_text(content, module.symbol.qualname))) != ast.dump(ast.parse(symbol_text(old.after, module.symbol.qualname))):
        raise Conflict("Target symbol changed after acceptance; automatic inverse would overwrite it")
    new = propose_implementation(root, old.module, symbol_text(old.before, module.symbol.qualname), title=f"Rollback {change_id}")
    new.kind = "rollback"
    store.write_change(new)
    return new
