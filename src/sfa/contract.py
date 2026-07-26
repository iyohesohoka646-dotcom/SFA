"""Contract inference and persistence for SFA modules.

Infers a JSON-Schema skeleton from an entry element's parameter and return
annotations, writes ``.sfa/modules/{id}/contract.json`` and ``summary.md``.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import jsonschema

from .config import SFAError, sfa_dir

CONTRACT_FILENAME = "contract.json"
SUMMARY_FILENAME = "summary.md"

_VALID_VALIDATION = {"strict", "lenient", "none"}

_PLACEHOLDER_SUMMARY = "请编辑此文件补充模块的自然语言描述（输入什么、输出什么、做什么）。"

_BASIC_TYPES: dict[str, dict[str, Any]] = {
    "int": {"type": "integer"},
    "float": {"type": "number"},
    "str": {"type": "string"},
    "bool": {"type": "boolean"},
    "bytes": {"type": "string"},
    "None": {"type": "null"},
    "NoneType": {"type": "null"},
    "Path": {"type": "string"},
    "PosixPath": {"type": "string"},
    "PurePath": {"type": "string"},
    "Decimal": {"type": "number"},
    "Any": {},
}

_ARRAY_BASES = {"list", "List", "Sequence", "Iterable", "Iterator", "set", "Set", "frozenset", "FrozenSet"}
_OBJECT_BASES = {"dict", "Dict", "Mapping", "DefaultDict", "OrderedDict"}
_TUPLE_BASES = {"tuple", "Tuple"}

_SELF_PARAMS = {"self", "cls"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def infer_contract(entry_element: dict[str, Any], module_id: str) -> dict[str, Any]:
    """Build a contract dict from *entry_element* (an elements.json record).

    The contract has keys: ``module``, ``version_hash``, ``input_schema``,
    ``output_schema``, ``natural_summary``.
    """
    input_schema = _infer_input_schema(entry_element)
    output_schema = _infer_output_schema(entry_element)
    natural_summary = entry_element.get("docstring") or _PLACEHOLDER_SUMMARY
    version_hash = _compute_version_hash(input_schema, output_schema)
    return {
        "module": module_id,
        "version_hash": version_hash,
        "input_schema": input_schema,
        "output_schema": output_schema,
        "natural_summary": natural_summary,
    }


def write_contract(root: Path, module_id: str, contract: dict[str, Any]) -> Path:
    """Write *contract* to ``.sfa/modules/{module_id}/contract.json``.

    Returns the absolute path written.
    """
    mod_dir = sfa_dir(root) / "modules" / module_id
    mod_dir.mkdir(parents=True, exist_ok=True)
    out = mod_dir / CONTRACT_FILENAME
    out.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def write_summary(root: Path, module_id: str, summary: str) -> Path:
    """Write *summary* to ``.sfa/modules/{module_id}/summary.md``."""
    mod_dir = sfa_dir(root) / "modules" / module_id
    mod_dir.mkdir(parents=True, exist_ok=True)
    out = mod_dir / SUMMARY_FILENAME
    out.write_text(summary, encoding="utf-8")
    return out


def read_contract(root: Path, module_id: str) -> dict[str, Any]:
    """Load and return the contract dict for *module_id*."""
    path = sfa_dir(root) / "modules" / module_id / CONTRACT_FILENAME
    if not path.is_file():
        raise SFAError(
            f"模块契约文件不存在：{path}\n"
            f"相关模块：{module_id}\n"
            "可操作建议：重新执行 `sfa module add`，或检查 .sfa/modules 目录。"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def contract_rel_path(module_id: str) -> str:
    """Return the project-root-relative posix path for a module's contract."""
    return f".sfa/modules/{module_id}/{CONTRACT_FILENAME}"


def summary_rel_path(module_id: str) -> str:
    """Return the project-root-relative posix path for a module's summary."""
    return f".sfa/modules/{module_id}/{SUMMARY_FILENAME}"


def validate_against_schema(
    instance: Any, schema: dict[str, Any], level: str
) -> list[str]:
    """Validate *instance* against *schema* at the given *level*.

    Returns a list of human-readable error messages (empty => passed or
    skipped).  *level* is one of ``strict``/``lenient``/``none``:

    * ``none`` — validation is skipped, always returns ``[]``.
    * ``strict``/``lenient`` — both run the same checks; the caller decides
      whether to raise (strict) or warn (lenient) based on a non-empty result.

    An empty schema (``{}``) means "no constraint" and returns ``[]``.
    """
    if level == "none":
        return []
    if level not in _VALID_VALIDATION:
        raise SFAError(
            f"无效的校验级别：{level}\n"
            f"可操作建议：使用以下之一：{', '.join(sorted(_VALID_VALIDATION))}。"
        )
    if not schema:
        return []
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(schema)
    except jsonschema.SchemaError as exc:
        raise SFAError(
            f"契约 Schema 本身无效，无法校验：{exc.message}\n"
            "可操作建议：检查 contract.json 的 input_schema/output_schema。"
        ) from exc
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    messages: list[str] = []
    for err in errors:
        path = ".".join(str(p) for p in err.absolute_path)
        where = f"路径 '{path}': " if path else ""
        messages.append(f"{where}{err.message}")
    return messages


# ---------------------------------------------------------------------------
# Schema inference
# ---------------------------------------------------------------------------


def _infer_input_schema(element: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param in element.get("parameters", []):
        name = param["name"]
        if name in _SELF_PARAMS:
            continue
        properties[name] = _annotation_to_schema(param.get("annotation"))
        if not param.get("has_default"):
            required.append(name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _infer_output_schema(element: dict[str, Any]) -> dict[str, Any]:
    return _annotation_to_schema(element.get("return_annotation"))


def _compute_version_hash(input_schema: dict[str, Any], output_schema: dict[str, Any]) -> str:
    payload = json.dumps(
        {"input_schema": input_schema, "output_schema": output_schema},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Python annotation -> JSON Schema
# ---------------------------------------------------------------------------


def _annotation_to_schema(ann: str | None) -> dict[str, Any]:
    """Map a raw Python annotation string to a JSON-Schema fragment."""
    if ann is None:
        return {}
    ann = ann.strip()
    if not ann:
        return {}

    # Optional[X] / Union[X, Y, ...]
    opt = re.match(r"^(Optional)\[(.+)\]$", ann)
    if opt:
        return {"anyOf": [_annotation_to_schema(opt.group(2)), {"type": "null"}]}
    uni = re.match(r"^(Union)\[(.+)\]$", ann)
    if uni:
        parts = _split_top_level(uni.group(2), ",")
        return {"anyOf": [_annotation_to_schema(p) for p in parts]}

    # X | Y | ...  (PEP 604 union syntax, top-level only)
    if "|" in ann:
        parts = _split_top_level(ann, "|")
        if len(parts) > 1:
            return {"anyOf": [_annotation_to_schema(p) for p in parts]}

    # Parameterised containers types: X[...]
    bracket = _find_top_bracket(ann)
    if bracket is not None:
        base = ann[:bracket].strip()
        inner = ann[bracket + 1 : ann.rfind("]")].strip()
        if base in _ARRAY_BASES:
            return {"type": "array", "items": _annotation_to_schema(inner)}
        if base in _OBJECT_BASES:
            parts = _split_top_level(inner, ",")
            value = _annotation_to_schema(parts[1]) if len(parts) > 1 else {}
            return {"type": "object", "additionalProperties": value}
        if base in _TUPLE_BASES:
            parts = _split_top_level(inner, ",")
            return {"type": "array", "prefixItems": [_annotation_to_schema(p) for p in parts]}
        return {}

    # Bare basic types
    if ann in _BASIC_TYPES:
        return dict(_BASIC_TYPES[ann])

    # Bare container types (no parameters)
    if ann in _ARRAY_BASES:
        return {"type": "array"}
    if ann in _OBJECT_BASES:
        return {"type": "object"}
    if ann in _TUPLE_BASES:
        return {"type": "array"}

    # Unknown – accept anything
    return {}


# ---------------------------------------------------------------------------
# String parsing helpers
# ---------------------------------------------------------------------------


def _split_top_level(s: str, delim: str) -> list[str]:
    """Split *s* on *delim* respecting ``[]`` / ``()`` nesting."""
    parts: list[str] = []
    depth = 0
    buf: list[str] = []
    for ch in s:
        if ch in "[(":
            depth += 1
            buf.append(ch)
        elif ch in "])":
            depth -= 1
            buf.append(ch)
        elif ch == delim and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail or parts:
        parts.append(tail)
    return parts


def _find_top_bracket(s: str) -> int | None:
    """Return the index of the first top-level ``[`` in *s*, or None."""
    depth = 0
    for i, ch in enumerate(s):
        if ch == "[":
            if depth == 0:
                return i
            depth += 1
        elif ch == "]":
            depth -= 1
    return None
