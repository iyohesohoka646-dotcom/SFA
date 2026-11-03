"""Sanitize first, then encode. Never stringify unsupported Python objects."""
from __future__ import annotations

import re
from typing import Any

from .models import CapturePolicy, canonical


def sensitive_key(key: str, fields: list[str], path: str = "") -> bool:
    lowered = {f.casefold() for f in fields}
    return key.casefold() in lowered or path.casefold() in lowered or any(f in key.casefold() for f in ("password", "secret", "api_key", "access_token"))


def sanitize(value: Any, fields: list[str], path: str = "", redacted: list[str] | None = None) -> Any:
    redacted = redacted if redacted is not None else []
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            key = str(key)
            child = path + "/" + key
            if sensitive_key(key, fields, child):
                out[key] = "[REDACTED]"
                redacted.append(child)
            else:
                out[key] = sanitize(item, fields, child, redacted)
        return out
    if isinstance(value, list):
        return [sanitize(item, fields, path + f"/{i}", redacted) for i, item in enumerate(value)]
    if isinstance(value, str):
        # Defense in depth for exception messages and narrative fields.
        result = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[REDACTED_EMAIL]", value)
        names = "|".join([*(re.escape(f) for f in fields if "/" not in f), "api[_-]?key", "password", "token", "secret"])
        if names:
            result = re.sub(r"(?i)([\"']?(?:" + names + r")[\"']?\s*[:=]\s*)(\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')", lambda m: m.group(1) + '"[REDACTED]"', result)
        result = re.sub(r"(?i)(bearer\s+|(?:api[_-]?key|password|token|secret)\s*[:=]\s*)[^\s,;\"']+", r"\1[REDACTED]", result)
        if result != value:
            redacted.append(path)
        return result
    if value is None or type(value) in (bool, int, float):
        return value
    raise TypeError(f"Unsupported evidence type: {type(value).__name__}")


def summary(value: Any, samples: int = 0) -> Any:
    if isinstance(value, dict):
        return {"type": "object", "count": len(value), "fields": {k: summary(v, samples) for k, v in list(value.items())[:64]}, "omitted_fields": max(0, len(value) - 64)}
    if isinstance(value, list):
        result = {"type": "array", "count": len(value)}
        if samples:
            result["sample"] = value[:samples]
        return result
    if isinstance(value, str):
        return {"type": "string", "length": len(value), **({"sample": value[:256]} if samples or value.startswith("[REDACTED") else {})}
    return {"type": type(value).__name__, "value": value}


def capture(value: Any, policy: CapturePolicy) -> dict:
    redacted: list[str] = []
    safe = sanitize(value, policy.sensitive_fields, redacted=redacted)
    encoded = canonical(safe).encode("utf-8")
    if policy.level == "metadata":
        data = {"type": type(safe).__name__}
    elif policy.level == "summary":
        data = summary(safe)
    elif policy.level == "sample":
        data = summary(safe, policy.sample_items)
    else:
        data = safe
    truncated = len(canonical(data).encode("utf-8")) > policy.max_bytes
    if truncated:
        data = {"type": type(safe).__name__, "message": "Capture exceeds byte limit", "bytes": len(encoded)}
    return {"level": policy.level, "data": data, "bytes": len(encoded), "redacted": redacted[:64], "truncated": truncated, "dropped": int(truncated)}


def sanitize_schema(schema, fields, path="", private=False):
    """Preserve schema structure and property names, while masking authored data."""
    if not isinstance(schema, dict):
        return schema
    result = {}
    for key, value in schema.items():
        if key == "properties":
            result[key] = {name: sanitize_schema(child, fields, path + "/" + name,
                          private or sensitive_key(name, fields, path + "/" + name)) for name, child in value.items()}
        elif key in ("const", "default", "examples", "enum"):
            result[key] = (["[REDACTED]"] * len(value) if key in ("examples", "enum") and isinstance(value, list) else "[REDACTED]") if private else sanitize(value, fields)
        elif isinstance(value, dict):
            result[key] = sanitize_schema(value, fields, path, private)
        elif isinstance(value, list):
            result[key] = [sanitize_schema(child, fields, path, private) if isinstance(child, dict) else child for child in value]
        else:
            result[key] = sanitize(value, fields) if isinstance(value, str) else value
    return result


def sanitize_project(project) -> dict:
    """Keep schema property names intact; redact values, examples and literals."""
    value = project.model_dump(mode="json")
    fields = project.capture.sensitive_fields
    value["input_schema"] = sanitize_schema(value["input_schema"], fields)
    for module in value["modules"]:
        for boundary in ("input", "output"):
            module["contract"][boundary] = sanitize_schema(module["contract"][boundary], fields)
        module["contract"]["examples"] = sanitize(module["contract"]["examples"], fields)
        module["description"] = sanitize(module["description"], fields)
        for port, source in module["outputs"].items():
            if source["kind"] == "literal":
                source["value"] = sanitize({port: source["value"]}, fields)[port]
    for binding in value["bindings"]:
        if binding["source"]["kind"] == "literal":
            binding["source"]["value"] = sanitize({binding["port"]: binding["source"]["value"]}, fields)[binding["port"]]
    value["metadata"] = sanitize(value["metadata"], fields)
    return value


def sanitize_change(change, project) -> dict:
    """One public proposal representation for HTTP and CLI; raw files stay local."""
    value = change.model_dump(mode="json")
    value.pop("before", None)
    value.pop("after", None)
    if change.project:
        value["project"] = sanitize_project(change.project)
    for field in ("diff", "title", "diagnostics", "usage"):
        value[field] = sanitize(value[field], project.capture.sensitive_fields)
    return value


def sanitize_plan(plan, project) -> dict:
    """Compile original data first. Redaction must never change diagnostics or revision."""
    value, safe = plan.model_dump(mode="json"), sanitize_project(project)
    fields = project.capture.sensitive_fields
    modules = {m["id"]: m for m in safe["modules"]}
    value["modules"] = [modules[m["id"]] for m in value["modules"]]
    replacements = {}

    def remember(original, displayed):
        key = canonical(original)
        if key not in replacements or replacements[key] == original or displayed == "[REDACTED]":
            replacements[key] = displayed

    for original, displayed in zip(project.bindings, safe["bindings"]):
        if original.source.kind == "literal":
            remember(original.source.value, displayed["source"]["value"])
    for module in project.modules:
        for port, original in module.outputs.items():
            if original.kind == "literal":
                remember(original.value, modules[module.id]["outputs"][port]["value"])
    for binding in [*value["bindings"], *value["composite_inputs"]]:
        source = binding["source"]
        if source["kind"] == "literal":
            source["value"] = sanitize({binding["port"]: replacements.get(canonical(source["value"]), source["value"])}, fields)[binding["port"]]
    for ports in value["composite_outputs"].values():
        for port, source in ports.items():
            if source["kind"] == "literal":
                source["value"] = sanitize({port: replacements.get(canonical(source["value"]), source["value"])}, fields)[port]
    value["diagnostics"] = sanitize(value["diagnostics"], fields)
    return {**value, "valid": plan.valid}
