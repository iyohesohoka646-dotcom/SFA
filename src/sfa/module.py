"""`sfa module add/remove/list` implementation.

Creates modules from elements.json entries, infers contracts, detects
owned elements via tree-sitter call analysis, and manages pipeline.yml.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import SFAError, find_project_root, load_config, sfa_dir
from .contract import contract_rel_path, infer_contract, summary_rel_path, write_contract, write_summary
from .extract import ELEMENTS_FILENAME, _PARSER
from . import probe as probe_mod
from . import topology

_VALID_VALIDATION = {"strict", "lenient", "none"}
_METHOD_KINDS = {"method"}
_FUNCTION_KINDS = {"function", "async_function"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def add_module(
    root: Path,
    name: str,
    entry: str,
    validation: str | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Create an atomic module from an entry element.

    1. Load elements.json, resolve *entry* to an element.
    2. Detect owned elements via tree-sitter call analysis.
    3. Infer and persist contract.json + summary.md.
    4. Append module to pipeline.yml.

    Idempotent: if a module with the same ID (derived from *name*) already
    exists, it is returned unchanged unless ``force`` is set, in which case
    the module entry is replaced in place (pipes/probes referencing the ID
    are preserved). Returns the module dict.
    """
    root = find_project_root(root)
    cfg = load_config(root)
    source_dir = str(cfg.get("source_dir", "src"))
    val_level = validation or str(cfg.get("validation", "strict"))
    if val_level not in _VALID_VALIDATION:
        raise SFAError(
            f"无效的校验级别：{val_level}\n"
            f"可操作建议：使用以下之一：{', '.join(sorted(_VALID_VALIDATION))}。"
        )

    module_id = topology.sanitize_id(name)
    existing = topology.get_module(root, module_id)
    parent = None
    if existing is not None:
        if not force:
            return existing
        parent = existing.get("parent")
        topology.remove_module(root, module_id)

    elements = _load_elements(root)
    entry_element = _find_entry_element(elements, entry)

    if entry_element["kind"] not in _FUNCTION_KINDS | _METHOD_KINDS:
        raise SFAError(
            f"入口元素 {entry} 的类型为 {entry_element['kind']}，不支持作为模块入口。\n"
            f"相关文件：{sfa_dir(root) / ELEMENTS_FILENAME}\n"
            "可操作建议：请选择 function、async_function 或 method 类型的元素。"
        )

    owned = _detect_owned_elements(entry_element, elements, root, source_dir)
    contract = infer_contract(entry_element, module_id)
    write_contract(root, module_id, contract)
    write_summary(root, module_id, contract["natural_summary"])

    module = {
        "id": module_id,
        "name": name,
        "type": "atomic",
        "path": f"{source_dir}/{entry_element['file']}",
        "entry": entry_element["qualified_name"],
        "method": entry_element["kind"],
        "owned_elements": sorted(owned),
        "contract": contract_rel_path(module_id),
        "summary": summary_rel_path(module_id),
        "validation": val_level,
        "parent": parent,
    }
    topology.add_module(root, module)
    return module


def remove_module(
    root: Path, module_id: str
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Remove a module and cascade-delete pipes and probes referencing it.

    Returns ``(removed_module, removed_pipes, removed_probes)``.
    """
    root = find_project_root(root)
    mod = topology.find_module(root, module_id)
    removed_pipes = topology.remove_pipes_referencing(root, module_id)
    removed_probes: list[dict[str, Any]] = []
    for pipe in removed_pipes:
        removed_probes.extend(probe_mod.remove_probes_for_pipe(root, pipe["id"]))
    removed_probes.extend(probe_mod.remove_probes_referencing_module(root, module_id))
    topology.remove_module(root, module_id)
    return mod, removed_pipes, removed_probes


def list_modules(root: Path) -> list[dict[str, Any]]:
    """Return all modules from pipeline.yml."""
    root = find_project_root(root)
    return topology.list_modules(root)


# ---------------------------------------------------------------------------
# Elements loading & lookup
# ---------------------------------------------------------------------------


def _load_elements(root: Path) -> list[dict[str, Any]]:
    path = sfa_dir(root) / ELEMENTS_FILENAME
    if not path.is_file():
        raise SFAError(
            f"elements.json 不存在：{path}\n"
            "可操作建议：请先执行 `sfa extract` 提取代码元素。"
        )
    doc = json.loads(path.read_text(encoding="utf-8"))
    elements = doc.get("elements", [])
    if not elements:
        raise SFAError(
            f"elements.json 中无元素：{path}\n"
            "可操作建议：请先在 source_dir 中创建源代码文件，再执行 `sfa extract`。"
        )
    return elements


def _find_entry_element(elements: list[dict[str, Any]], entry: str) -> dict[str, Any]:
    # Exact qualified_name match first
    for el in elements:
        if el["qualified_name"] == entry:
            return el
    # Fall back to unique name match
    matches = [el for el in elements if el["name"] == entry]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        qnames = [m["qualified_name"] for m in matches]
        raise SFAError(
            f"多个元素名为 '{entry}'，请使用 qualified_name：{qnames}\n"
            "可操作建议：使用上述 qualified_name 之一作为 --entry 参数。"
        )
    raise SFAError(
        f"入口元素 '{entry}' 未找到。\n"
        f"相关文件：elements.json\n"
        "可操作建议：执行 `sfa extract` 后检查 elements.json 中的 qualified_name 字段。"
    )


# ---------------------------------------------------------------------------
# Owned-element detection (tree-sitter call analysis)
# ---------------------------------------------------------------------------


def _detect_owned_elements(
    entry_element: dict[str, Any],
    all_elements: list[dict[str, Any]],
    root: Path,
    source_dir: str,
) -> set[str]:
    """Determine which elements are owned by the module.

    The entry element is always owned.  Additionally:
    * If the entry is a method, all sibling methods of the same class are owned.
    * Any element called from within the entry's body (in the same file) is owned.
    """
    owned: set[str] = {entry_element["qualified_name"]}
    same_file = [el for el in all_elements if el["file"] == entry_element["file"]]

    # Methods of the same class
    if entry_element["kind"] in _METHOD_KINDS and entry_element.get("parent_class"):
        cls = entry_element["parent_class"]
        for el in same_file:
            if el["kind"] in _METHOD_KINDS and el.get("parent_class") == cls:
                owned.add(el["qualified_name"])

    # Called elements
    calls = _extract_calls_from_body(entry_element, root, source_dir)
    for call_kind, call_name in calls:
        for el in same_file:
            if el["qualified_name"] in owned:
                continue
            if call_kind == "simple" and el["kind"] in _FUNCTION_KINDS and el["parent_class"] is None:
                if el["name"] == call_name:
                    owned.add(el["qualified_name"])
            elif call_kind == "self_method" and el["kind"] in _METHOD_KINDS:
                if el["name"] == call_name and el.get("parent_class") == entry_element.get("parent_class"):
                    owned.add(el["qualified_name"])
    return owned


def _extract_calls_from_body(
    entry_element: dict[str, Any],
    root: Path,
    source_dir: str,
) -> list[tuple[str, str]]:
    """Parse the entry element's source file and collect call targets.

    Returns a list of ``(call_kind, name)`` where *call_kind* is
    ``"simple"`` (bare ``foo()``) or ``"self_method"`` (``self.bar()``).
    """
    src_path = (root / source_dir / entry_element["file"]).resolve()
    if not src_path.is_file():
        return []
    source = src_path.read_bytes()
    tree = _PARSER.parse(source)
    fn_node = _find_function_node(
        tree.root_node,
        source,
        entry_element["name"],
        entry_element["line_start"],
    )
    if fn_node is None:
        return []
    body = fn_node.child_by_field_name("body")
    if body is None:
        return []
    calls: list[tuple[str, str]] = []
    _collect_calls(body, source, calls)
    return calls


def _find_function_node(node: Any, source: bytes, name: str, line_start: int) -> Any | None:
    """Locate the ``function_definition`` node matching *name* and *line_start*."""
    for child in node.children:
        t = child.type
        if t == "function_definition":
            name_node = child.child_by_field_name("name")
            if name_node is not None:
                fn_name = source[name_node.start_byte : name_node.end_byte].decode("utf-8")
                if fn_name == name and child.start_point[0] + 1 == line_start:
                    return child
        elif t == "class_definition":
            body = child.child_by_field_name("body")
            if body is not None:
                found = _find_function_node(body, source, name, line_start)
                if found is not None:
                    return found
        else:
            found = _find_function_node(child, source, name, line_start)
            if found is not None:
                return found
    return None


def _collect_calls(node: Any, source: bytes, calls: list[tuple[str, str]]) -> None:
    """Recursively collect call targets from *node*."""
    for child in node.children:
        if child.type == "call":
            func_node = child.child_by_field_name("function")
            if func_node is not None:
                info = _extract_call_info(func_node, source)
                if info is not None:
                    calls.append(info)
        _collect_calls(child, source, calls)


def _extract_call_info(func_node: Any, source: bytes) -> tuple[str, str] | None:
    if func_node.type == "identifier":
        name = source[func_node.start_byte : func_node.end_byte].decode("utf-8")
        if name not in {"print", "len", "range", "int", "float", "str", "bool", "list", "dict", "set", "tuple", "type", "isinstance", "super"}:
            return ("simple", name)
        return None
    if func_node.type == "attribute":
        attr_node = func_node.child_by_field_name("attribute")
        obj_node = func_node.child_by_field_name("object")
        if attr_node is not None:
            attr_name = source[attr_node.start_byte : attr_node.end_byte].decode("utf-8")
            if obj_node is not None and obj_node.type == "identifier":
                obj_name = source[obj_node.start_byte : obj_node.end_byte].decode("utf-8")
                if obj_name == "self":
                    return ("self_method", attr_name)
            return None
    return None
