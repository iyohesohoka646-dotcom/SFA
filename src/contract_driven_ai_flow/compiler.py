"""Compile authored boundaries to explicit executable bindings; never infer fan-in."""
from __future__ import annotations

from collections import Counter
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .models import Diagnostic, ExecutionPlan, ProjectSpec, Source, canonical

Compatibility = Literal["compatible", "incompatible", "unknown"]


def pointer_parts(pointer: str) -> list[str]:
    return [p.replace("~1", "/").replace("~0", "~") for p in pointer.split("/")[1:]] if pointer else []


def select(value: Any, pointer: str) -> Any:
    for part in pointer_parts(pointer):
        if isinstance(value, list):
            value = value[int(part)]
        elif isinstance(value, dict):
            value = value[part]
        else:
            raise KeyError(pointer)
    return value


def schema_at(schema: dict, pointer: str) -> dict:
    parts = pointer_parts(pointer)
    if not parts:
        return schema
    part, tail = parts[0], "/" + "/".join(p.replace("~", "~0").replace("/", "~1") for p in parts[1:]) if len(parts) > 1 else ""
    if "anyOf" in schema or "oneOf" in schema:
        choices = [schema_at(s, pointer) for s in schema.get("anyOf", schema.get("oneOf", []))]
        if any(not c for c in choices):
            return {}
        return {"anyOf": choices}
    if schema.get("type") == "array" and part.isdigit():
        return schema_at(schema.get("items", {}), tail)
    props = schema.get("properties", {})
    if part in props and part in schema.get("required", []):
        return schema_at(props[part], tail)
    return {}


def compatible(source: dict, target: dict) -> Compatibility:
    """Conservative subset proof. Unsupported constraints stay explicitly unknown."""
    if source is False or target is True:
        return "compatible"
    if target is False:
        return "incompatible"
    if source is True:
        return "unknown"
    if not target or canonical(source) == canonical(target):
        return "compatible"
    if not source:
        return "unknown"
    annotations = {"title", "description", "examples", "default", "$schema", "$id"}
    known = {"type", "properties", "required", "additionalProperties", "items", "enum", "const", "anyOf"} | annotations
    if (set(source) | set(target)) - known:
        return "unknown"
    if "anyOf" in source:
        results = [compatible(s, target) for s in source["anyOf"]]
        return "compatible" if all(r == "compatible" for r in results) else "incompatible" if "incompatible" in results else "unknown"
    if "anyOf" in target:
        results = [compatible(source, t) for t in target["anyOf"]]
        return "compatible" if "compatible" in results else "incompatible" if all(r == "incompatible" for r in results) else "unknown"
    st, tt = source.get("type"), target.get("type")
    if isinstance(st, list):
        return compatible({"anyOf": [{**source, "type": t} for t in st]}, target)
    if isinstance(tt, list):
        return compatible(source, {"anyOf": [{**target, "type": t} for t in tt]})
    if "const" in source or "enum" in source:
        values = [source["const"]] if "const" in source else source["enum"]
        return "compatible" if all(Draft202012Validator(target).is_valid(v) for v in values) else "incompatible"
    if "enum" in target or "const" in target:
        return "unknown"
    if st is None or tt is None:
        return "unknown"
    if st != tt and not (st == "integer" and tt == "number"):
        return "incompatible"
    if tt == "array":
        return compatible(source.get("items", {}), target.get("items", {}))
    if tt == "object":
        if not set(target.get("required", [])).issubset(source.get("required", [])):
            return "incompatible"
        sp, tp = source.get("properties", {}), target.get("properties", {})
        if target.get("additionalProperties") is False and (source.get("additionalProperties") is not False or set(sp) - set(tp)):
            return "incompatible"
        checks = [compatible(sp[k], tp[k]) for k in sp.keys() & tp.keys()]
        if source.get("additionalProperties") is not False:
            extra = source.get("additionalProperties", {})
            checks += [compatible(extra if isinstance(extra, dict) else {}, tp[k]) for k in tp.keys() - sp.keys()]
        if isinstance(target.get("additionalProperties"), dict):
            return "unknown"
        return "incompatible" if "incompatible" in checks else "unknown" if "unknown" in checks else "compatible"
    return "compatible"


def compile_project(project: ProjectSpec) -> ExecutionPlan:
    diagnostics: list[Diagnostic] = []

    def issue(code, message, module=None, binding=None, severity="error"):
        diagnostics.append(Diagnostic(code=code, message=message, module=module, binding=binding, severity=severity))

    modules = {m.id: m for m in project.modules}
    for kind, ids in (("module", [m.id for m in project.modules]), ("binding", [b.id for b in project.bindings]), ("probe", [p.id for p in project.probes])):
        for name, count in Counter(ids).items():
            if count > 1:
                issue("duplicate_id", f"Duplicate {kind} id: {name}")
    schemas = [(None, project.input_schema)]
    for module in project.modules:
        schemas += [(module.id, module.contract.input), (module.id, module.contract.output)]
        if module.parent and (module.parent not in modules or modules[module.parent].kind != "composite"):
            issue("parent", "Parent must reference a composite", module.id)
        seen = {module.id}
        parent = module.parent
        while parent in modules:
            if parent in seen:
                issue("hierarchy_cycle", "Composite hierarchy contains a cycle", module.id)
                break
            seen.add(parent)
            parent = modules[parent].parent
        if module.contract.input.get("type") != "object":
            issue("input_shape", "Python keyword inputs and composite inputs require an object schema", module.id)
        if module.guard and (module.guard.decision not in modules or modules[module.guard.decision].kind != "decision"):
            issue("guard", "Guard must reference a Decision module", module.id)
        if module.kind == "decision":
            from .probes import compile_expression
            try:
                compile_expression(module.condition or "", input_schema=module.contract.input)
            except ValueError as exc:
                issue("decision_expression", str(exc), module.id)
    for mid, schema in schemas:
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            issue("schema", exc.message, mid)

    targets: dict[tuple[str, str], Any] = {}
    for binding in project.bindings:
        if binding.target not in modules:
            issue("reference", f"Missing target {binding.target}", binding=binding.id)
            continue
        target = modules[binding.target]
        key = (binding.target, binding.port)
        if key in targets:
            issue("multiple_writers", f"Input {binding.port} has multiple writers; introduce an explicit merge module", target.id, binding.id)
        targets[key] = binding
        if binding.port not in target.contract.input.get("properties", {}):
            issue("port", f"Undeclared input port {binding.port}", target.id, binding.id)
        source = binding.source
        if source.kind == "module":
            if source.module not in modules:
                issue("reference", f"Missing source {source.module}", target.id, binding.id)
            else:
                sm = modules[source.module]
                if sm.parent != target.parent and sm.id != target.parent:
                    issue("boundary", "Connection crosses a composite boundary; use public ports", target.id, binding.id)
        elif source.kind == "project" and target.parent:
            issue("boundary", "Project inputs must enter a composite through its public ports", target.id, binding.id)
    for module in project.modules:
        for port in module.contract.input.get("required", []):
            if (module.id, port) not in targets:
                issue("unbound_input", f"Required port {port} needs an explicit binding (including defaults)", module.id)
        if module.kind == "composite":
            declared = module.contract.output.get("properties", {})
            if set(module.outputs) != set(declared):
                issue("composite_output", "Every public output needs exactly one internal mapping", module.id)
            for port, source in module.outputs.items():
                if source.kind == "module" and (source.module not in modules or modules[source.module].parent != module.id):
                    issue("boundary", f"Composite output {port} must map an immediate child", module.id)

    def resolve(source: Source, target_id: str, seen: frozenset = frozenset()) -> Source:
        if source.kind != "module" or source.module not in modules or modules[source.module].kind != "composite":
            return source
        composite = modules[source.module]
        parts = pointer_parts(source.pointer)
        if not parts:
            raise ValueError("Composite bindings require a named public port (/port)")
        port = parts[0]
        marker = (composite.id, port, target_id)
        if marker in seen:
            raise ValueError("Composite mapping cycle")
        if modules.get(target_id) and modules[target_id].parent == composite.id:
            binding = targets.get((composite.id, port))
            if binding is None:
                raise ValueError(f"Unbound composite input {composite.id}.{port}")
            inner, next_target = binding.source, composite.id
        else:
            if port not in composite.outputs:
                raise ValueError(f"Unknown composite output {composite.id}.{port}")
            inner, next_target = composite.outputs[port], composite.id
        suffix = "/" + "/".join(p.replace("~", "~0").replace("/", "~1") for p in parts[1:]) if len(parts) > 1 else ""
        expanded = inner.model_copy(update={"pointer": inner.pointer + suffix})
        return resolve(expanded, next_target, seen | {marker})

    def source_schema(source: Source, target_id: str) -> dict:
        if source.kind == "literal":
            return {"const": select(source.value, source.pointer)}
        if source.kind == "project":
            base = project.input_schema
        else:
            owner = modules[source.module]
            base = owner.contract.input if owner.kind == "composite" and modules[target_id].parent == owner.id else owner.contract.output
        return schema_at(base, source.pointer)

    flat, composite_inputs, composite_outputs = [], [], {}
    for binding in project.bindings:
        if binding.target not in modules:
            continue
        try:
            resolved = resolve(binding.source, binding.target)
            result = compatible(source_schema(binding.source, binding.target), modules[binding.target].contract.input.get("properties", {}).get(binding.port, {}))
            if result != "compatible":
                issue("contract_" + result, f"Binding schema is {result}" + ("; dynamic boundary validated at runtime" if binding.dynamic else "; refine contracts or explicitly mark dynamic"), binding.target, binding.id, "warning" if result == "unknown" and binding.dynamic else "error")
            if modules[binding.target].kind != "composite":
                flat.append(binding.model_copy(update={"source": resolved}))
            else:
                composite_inputs.append(binding.model_copy(update={"source": resolved}))
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            issue("binding_resolution", str(exc), binding.target, binding.id)
    for module in project.modules:
        if module.kind == "composite":
            composite_outputs[module.id] = {}
        for port, source in module.outputs.items():
            try:
                composite_outputs[module.id][port] = resolve(source, module.id)
                result = compatible(source_schema(source, module.id), module.contract.output.get("properties", {}).get(port, {}))
                if result != "compatible":
                    issue("composite_contract", f"Output {port}: {result}; refine public/internal schemas", module.id)
            except (ValueError, KeyError, TypeError) as exc:
                issue("composite_output", str(exc), module.id)

    atomic = [m for m in project.modules if m.kind != "composite"]
    dependencies = {m.id: set() for m in atomic}
    for binding in flat:
        if binding.source.kind == "module" and binding.source.module in dependencies:
            dependencies[binding.target].add(binding.source.module)
    for module in atomic:
        if module.guard:
            dependencies[module.id].add(module.guard.decision)

    def boundary_sources(source, target_id, seen=frozenset()):
        """All public fields must be ready before a whole-object boundary check."""
        resolved = resolve(source, target_id)
        required = {resolved.module} if resolved.kind == "module" else set()
        if source.kind != "module" or source.module not in modules or modules[source.module].kind != "composite":
            return required
        composite = modules[source.module]
        if composite.id in seen:
            return required
        if modules[target_id].parent == composite.id:
            port = pointer_parts(source.pointer)[0]
            public = targets.get((composite.id, port))
            if public:
                required.update(boundary_sources(public.source, composite.id, seen | {composite.id}))
        else:
            for public in composite.outputs.values():
                required.update(boundary_sources(public, composite.id, seen | {composite.id}))
        return required

    for module in atomic:
        owners = {module.id}
        parent = module.parent
        while parent in modules and parent not in owners:
            owners.add(parent)
            parent = modules[parent].parent
        for owner in owners:
            if modules[owner].guard:
                dependencies[module.id].add(modules[owner].guard.decision)
        for binding in project.bindings:
            if binding.target in owners:
                try:
                    dependencies[module.id].update(boundary_sources(binding.source, binding.target))
                except (ValueError, KeyError, IndexError, TypeError):
                    pass  # The binding-resolution diagnostic above already blocks execution.
    order = []
    remaining = {k: v.copy() for k, v in dependencies.items()}
    while remaining:
        ready = [k for k, v in remaining.items() if not v]
        if not ready:
            issue("cycle", f"Execution cycle: {', '.join(sorted(remaining))}")
            break
        for mid in ready:
            order.append(mid)
            del remaining[mid]
        for deps in remaining.values():
            deps.difference_update(ready)
    for probe in project.probes:
        if probe.module not in modules:
            issue("probe_target", "Probe must observe a declared module boundary", probe.module)
            continue
        if probe.binding and not any(b.id == probe.binding and b.target == probe.module for b in [*flat, *composite_inputs]):
            issue("probe_binding", "Edge probe must name a binding into this module", probe.module, probe.binding)
        if probe.enabled and probe.kind in ("assertion", "branch_observer"):
            from .probes import compile_expression
            try:
                module = modules[probe.module]
                compile_expression(probe.expression, output_schema=module.contract.output, input_schema=module.contract.input)
            except ValueError as exc:
                issue("probe_expression", str(exc), probe.module)
    return ExecutionPlan(revision=project.revision, modules=atomic, bindings=flat, order=order,
                         hierarchy={m.id: m.parent for m in project.modules}, diagnostics=diagnostics,
                         composite_inputs=composite_inputs, composite_outputs=composite_outputs,
                         dependencies={k: sorted(v) for k, v in dependencies.items()})
