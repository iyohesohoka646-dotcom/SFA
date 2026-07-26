"""`sfa extract` implementation: parse Python source with tree-sitter.

Scans ``source_dir`` (from sfa.yml) for ``*.py`` files and extracts functions,
async functions, classes and class methods into ``.sfa/elements.json``.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any

import tree_sitter_python as tspython
from tree_sitter import Language, Parser

from .config import SFAError, find_project_root, load_config, sfa_dir

ELEMENTS_FILENAME = "elements.json"
_PY_LANGUAGE = Language(tspython.language())
_PARSER = Parser(_PY_LANGUAGE)


def extract(root: Path | None = None) -> dict[str, Any]:
    """Run extraction and write ``.sfa/elements.json``. Returns the document."""
    root = find_project_root(root)
    cfg = load_config(root)
    source_dir = (root / str(cfg.get("source_dir", "src"))).resolve()

    if not source_dir.exists():
        raise SFAError(
            f"source_dir 不存在：{source_dir}\n"
            f"可操作建议：检查 sfa.yml 中 source_dir 配置，或在该路径下创建源代码目录。"
        )

    elements: list[dict[str, Any]] = []
    py_files = sorted(source_dir.rglob("*.py"))
    for file in py_files:
        try:
            elements.extend(_extract_file(file, source_dir))
        except SFAError:
            raise
        except Exception as exc:  # noqa: BLE001 - report and skip a bad file
            _warn(f"解析失败，已跳过 {file}: {exc}")

    doc = {
        "version": 1,
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "source_dir": str(cfg.get("source_dir", "src")),
        "elements": elements,
    }

    out = sfa_dir(root) / ELEMENTS_FILENAME
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc, out


def _extract_file(
    file: Path, source_root: Path, source: bytes | None = None
) -> list[dict[str, Any]]:
    if source is None:
        source = file.read_bytes()
    tree = _PARSER.parse(source)
    root_node = tree.root_node
    if root_node.has_error:
        _warn(f"文件含语法错误，仍尽力提取：{file}")
    rel = _to_posix(file.relative_to(source_root))
    elements: list[dict[str, Any]] = []
    _visit(root_node, source, rel, elements, parent_class=None)
    return elements


def _visit(
    node: Any,
    source: bytes,
    rel: str,
    out: list[dict[str, Any]],
    parent_class: str | None,
) -> None:
    for child in node.children:
        t = child.type
        if t == "function_definition":
            out.append(
                _func_element(child, source, rel, parent_class)
            )
            # Do not recurse into function bodies for nested defs.
        elif t == "class_definition":
            cls = _class_element(child, source, rel)
            out.append(cls)
            body = child.child_by_field_name("body")
            if body is not None:
                _visit(body, source, rel, out, parent_class=cls["name"])
        else:
            _visit(child, source, rel, out, parent_class=parent_class)


def _is_async(fn: Any) -> bool:
    for child in fn.children:
        if child.type == "async":
            return True
        if child.type == "def":
            break
    return False


def _func_element(
    fn: Any, source: bytes, rel: str, parent_class: str | None
) -> dict[str, Any]:
    name_node = fn.child_by_field_name("name")
    name = source[name_node.start_byte : name_node.end_byte].decode("utf-8")
    is_async = _is_async(fn)
    kind = "method" if parent_class else ("async_function" if is_async else "function")

    params = _extract_parameters(fn, source)
    return_node = fn.child_by_field_name("return_type")
    return_annotation = (
        source[return_node.start_byte : return_node.end_byte].decode("utf-8")
        if return_node is not None
        else None
    )
    body = fn.child_by_field_name("body")
    docstring = _extract_docstring(body, source)

    return {
        "kind": kind,
        "name": name,
        "qualified_name": f"{parent_class}.{name}" if parent_class else name,
        "file": rel,
        "line_start": fn.start_point[0] + 1,
        "line_end": fn.end_point[0] + 1,
        "parameters": params,
        "return_annotation": return_annotation,
        "docstring": docstring,
        "parent_class": parent_class,
    }


def _class_element(cls: Any, source: bytes, rel: str) -> dict[str, Any]:
    name_node = cls.child_by_field_name("name")
    name = source[name_node.start_byte : name_node.end_byte].decode("utf-8")
    body = cls.child_by_field_name("body")
    docstring = _extract_docstring(body, source)
    return {
        "kind": "class",
        "name": name,
        "qualified_name": name,
        "file": rel,
        "line_start": cls.start_point[0] + 1,
        "line_end": cls.end_point[0] + 1,
        "parameters": [],
        "return_annotation": None,
        "docstring": docstring,
        "parent_class": None,
    }


def _extract_parameters(fn: Any, source: bytes) -> list[dict[str, Any]]:
    params_node = fn.child_by_field_name("parameters")
    if params_node is None:
        return []
    result: list[dict[str, Any]] = []
    for child in params_node.children:
        t = child.type
        if t in {"(", ")", ","} or child.is_named is False:
            continue
        name_node = child.child_by_field_name("name")
        if name_node is None:
            # list_splat_pattern / dictionary_splat_pattern: identifier is a child
            name_node = _first_named_child_of_type(child, "identifier")
        if name_node is None:
            continue
        name = source[name_node.start_byte : name_node.end_byte].decode("utf-8")
        annotation_node = child.child_by_field_name("type")
        annotation = (
            source[annotation_node.start_byte : annotation_node.end_byte].decode("utf-8")
            if annotation_node is not None
            else None
        )
        has_default = "=" in {c.type for c in child.children}
        default = (
            source[child.children[-1].start_byte : child.children[-1].end_byte].decode("utf-8")
            if has_default and child.children
            else None
        )
        result.append(
            {
                "name": name,
                "annotation": annotation,
                "has_default": has_default,
                "default": default,
            }
        )
    return result


def _first_named_child_of_type(node: Any, type_: str) -> Any | None:
    for child in node.children:
        if child.is_named and child.type == type_:
            return child
    return None


def _extract_docstring(body: Any | None, source: bytes) -> str | None:
    if body is None:
        return None
    for child in body.children:
        if child.type == "expression_statement":
            inner = child.child_by_field_name("value") or (
                child.children[0] if child.children else None
            )
            if inner is not None and inner.type == "string":
                return _clean_docstring(
                    source[inner.start_byte : inner.end_byte].decode("utf-8")
                )
        if child.is_named and child.type not in {"expression_statement", "string"}:
            break
    return None


def _clean_docstring(raw: str) -> str:
    text = raw.strip()
    if text.startswith('"""') or text.startswith("'''"):
        text = text[3:]
    if text.endswith('"""') or text.endswith("'''"):
        text = text[:-3]
    return text.strip()


def _to_posix(p: Path) -> str:
    return p.as_posix()


def _warn(msg: str) -> None:
    import sys

    print(f"[sfa extract] WARNING: {msg}", file=sys.stderr)
