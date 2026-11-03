"""Definition defaults seed new bindings; saved bindings retain their own parameters."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from jsonschema import Draft202012Validator


DEFAULT_PROBE_TASK = (
    "Explain the selected scientific evidence, its direct relationships and coverage."
)


def schema_defaults(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Materialize authored JSON Schema defaults without inventing required values."""
    result = {}
    for key, field in schema.get("properties", {}).items():
        if "default" in field:
            result[key] = deepcopy(field["default"])
        elif field.get("type") == "object":
            nested = schema_defaults(field)
            if nested:
                result[key] = nested
    return result


def probe_parameters(definition, saved_defaults=None) -> dict[str, Any]:
    return {
        **schema_defaults(definition.parameter_schema),
        **deepcopy(saved_defaults or {}),
    }


_CREDENTIAL_KEYS = {
    "apikey", "authorization", "accesstoken", "refreshtoken", "password",
    "clientsecret", "privatekey", "secret", "token", "credential",
}


def _reject_credentials(value, path=""):
    if isinstance(value, dict):
        for key, item in value.items():
            location = f"{path}.{key}" if path else str(key)
            normalized = "".join(c for c in str(key).lower() if c.isalnum())
            if normalized in _CREDENTIAL_KEYS:
                raise ValueError(
                    f"Probe defaults {location} cannot contain credentials; use model settings"
                )
            _reject_credentials(item, location)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_credentials(item, f"{path}[{index}]")


def validate_probe_defaults(defaults, definitions) -> None:
    known = {definition.id: definition for definition in definitions}
    for key, parameters in defaults.items():
        if key not in known:
            raise ValueError(f"Probe defaults {key}: definition is not registered")
        _reject_credentials(parameters, key)
        errors = sorted(
            Draft202012Validator(known[key].parameter_schema).iter_errors(parameters),
            key=lambda error: str(error.path),
        )
        if errors:
            error = errors[0]
            field = ".".join(str(part) for part in error.path) or "root"
            raise ValueError(f"Probe defaults {key} {field}: {error.message}")


def compose_probe_prompt(parameters, fallback=DEFAULT_PROBE_TASK) -> str:
    """Use every requirement field in the harness question, preserving old prompts."""
    def text(key):
        value = parameters.get(key)
        return value.strip() if isinstance(value, str) else ""

    task, legacy = text("task"), text("prompt")
    requirements = [
        ("关注重点", text("focus")),
        ("约束", text("constraints")),
        ("输出格式", text("output_format")),
    ]
    if not task and not any(value for _, value in requirements):
        # Keep an existing prompt intact, including intentional whitespace.
        return parameters.get("prompt") or fallback
    parts = ["任务：" + (task or legacy or fallback)]
    parts.extend(label + "：" + value for label, value in requirements if value)
    if task and legacy and legacy != task:
        parts.append("补充指令：" + legacy)
    return "\n\n".join(parts)
