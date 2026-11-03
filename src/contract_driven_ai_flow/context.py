from __future__ import annotations

from pathlib import Path

from .models import ProjectSpec, canonical
from .paths import FlowError
from .privacy import sanitize, sanitize_schema
from .source import read_symbol
from .storage import Store


def build_context(root: Path, module_id: str, level: str = "L2", project: ProjectSpec | None = None) -> dict:
    if level not in ("L1", "L2", "L3", "L4"):
        raise FlowError("Visibility must be L1, L2, L3 or L4")
    project = project or Store(root).load()
    modules = {m.id: m for m in project.modules}
    if module_id not in modules or modules[module_id].symbol is None:
        raise FlowError("Context requires a Python module")
    target = modules[module_id]
    entries = [{"role": "target", "module": module_id, "symbol": target.symbol.model_dump(), "contract": target.contract.model_dump(),
                "contract_revision": target.contract.revision, "source": read_symbol(root, target.symbol)}]
    upstream = {}
    for binding in project.bindings:
        if binding.target == module_id and binding.source.kind == "module":
            upstream.setdefault(binding.source.module, []).append(binding)
    for mid, bindings in sorted(upstream.items()):
        module = modules[mid]
        effective = min([level, *[b.visibility for b in bindings]])
        entry = {"role": "upstream", "module": mid, "contract": {"input": module.contract.input, "output": module.contract.output},
                 "description": module.description, "contract_revision": module.contract.revision,
                 "visibility": effective, "bindings": [b.id for b in bindings]}
        if effective in ("L2", "L3", "L4"):
            entry["examples"] = module.contract.examples
            entry["example_source"] = "contract fixtures; runtime samples require an explicit reviewed fixture promotion"
        if effective in ("L3", "L4") and module.symbol:
            entry["symbol"] = module.symbol.model_dump()
        if effective == "L4" and module.symbol:
            entry["source"] = read_symbol(root, module.symbol)
        entries.append(entry)
    if level in ("L3", "L4"):
        for dependency in target.dependencies:
            entries.append({"role": "explicit_dependency", "symbol": dependency.model_dump(), "source": read_symbol(root, dependency)})
    for entry in entries:
        if "description" in entry:
            entry["description"] = sanitize(entry["description"], project.capture.sensitive_fields)
        if "contract" in entry:
            for boundary in ("input", "output"):
                entry["contract"][boundary] = sanitize_schema(entry["contract"][boundary], project.capture.sensitive_fields)
        if "contract" in entry and "examples" in entry["contract"]:
            entry["contract"]["examples"] = sanitize(entry["contract"]["examples"], project.capture.sensitive_fields)
        if "examples" in entry:
            entry["examples"] = sanitize(entry["examples"], project.capture.sensitive_fields)
        if "source" in entry:
            entry["source"] = sanitize(entry["source"], project.capture.sensitive_fields)
    safe = {"level": level, "revision": project.revision, "target": module_id, "entries": entries,
            "policy": "Only the target function body may change. Preserve signature and decorators. Return one Python function. Allowed imports: " + ", ".join(target.allowed_imports)}
    text = canonical(safe)
    return {**safe, "bytes": len(text.encode("utf-8")), "estimated_tokens": (len(text) + 3) // 4}
