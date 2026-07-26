"""AI agent layer: context assembly and generated-code post-processing.

Assembles the prompt sent to the LLM strictly from the target module's
contract plus upstream information gated by pipe visibility (L1-L4).
Never includes downstream modules.  Provides static analysis of the
generated code (import whitelist + side-effect detection) and locates
the entry function's line range for surgical diff application.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from .config import SFAError, find_project_root, sfa_dir
from .extract import _extract_file
from .module import _find_entry_element, _load_elements
from .topology import load_pipeline

_CONTRACT_FILENAME = "contract.json"

_VISIBILITY_ORDER = {"L1": 1, "L2": 2, "L3": 3, "L4": 4}


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


def build_prompt(root: Path, module: dict[str, Any], cfg: dict[str, Any]) -> tuple[str, str]:
    """Return ``(system, user)`` for generating *module*'s entry function.

    *module* is a pipeline.yml module dict.  *cfg* is the loaded config.
    """
    root = find_project_root(root)
    contract = _load_contract(root, module)

    # Load elements.json and pipeline.yml once; thread through downstream.
    elements = _load_elements(root)
    pipeline = load_pipeline(root)

    entry_sig = _load_entry_signature(elements, module)
    upstreams = _collect_upstreams(pipeline, module, root)

    allowed = cfg.get("allowed_imports") or []

    system = _SYSTEM_PROMPT_TEMPLATE.format(
        allowed=", ".join(allowed) or "(未配置)",
    )

    user_parts: list[str] = []
    user_parts.append("# 目标模块契约\n")
    user_parts.append(f"- 模块 ID：`{module['id']}`\n")
    user_parts.append(f"- 自然语言摘要：{contract.get('natural_summary', '')}\n")
    user_parts.append("- 输入 Schema：\n```json\n")
    user_parts.append(json.dumps(contract.get("input_schema", {}), ensure_ascii=False, indent=2))
    user_parts.append("\n```\n- 输出 Schema：\n```json\n")
    user_parts.append(json.dumps(contract.get("output_schema", {}), ensure_ascii=False, indent=2))
    user_parts.append("\n```\n\n")

    if upstreams:
        user_parts.append("# 上游模块信息（按管道可见性级别提供）\n\n")
        for up in upstreams:
            user_parts.append(_render_upstream(root, up, elements))
        user_parts.append("\n")
    else:
        user_parts.append("# 上游模块信息\n本模块无上游管道。\n\n")

    user_parts.append("# 待实现的入口函数签名（必须保持签名不变）\n")
    user_parts.append("```python\n")
    user_parts.append(entry_sig)
    user_parts.append("\n```\n\n")

    user_parts.append(
        "请输出该入口函数的完整定义（签名 + docstring + 函数体），"
        "置于一个 ```python``` 代码块中。不得修改签名，不得新增顶层 import，"
        "不得包含任何下游模块的信息。\n"
    )

    return system, "".join(user_parts)


_SYSTEM_PROMPT_TEMPLATE = """\
你是 SFA 系统中的代码实现者。你的职责是在严格契约约束下为单个模块生成入口函数的实现代码。

核心约束：
1. 仅输出入口函数的完整定义（签名 + docstring + 函数体），置于一个 ```python``` 代码块中。
2. 必须保持入口函数签名不变（函数名、参数、返回注解）。
3. 只能使用以下库：{allowed}。如需其他库，先以注释说明理由并请求批准，不要直接 import。
4. 不得修改任何全局状态（如 os.environ、sys.modules），不得有模块级副作用。
5. 不得包含任何下游模块的信息；你只能看到上游信息和本模块契约。
6. 不要新增顶层 import 语句；如需工具函数，在函数体内定义嵌套局部函数。
7. 输出应只含该函数，不要多余解释文字。
"""


def _load_contract(root: Path, module: dict[str, Any]) -> dict[str, Any]:
    from .contract import read_contract

    return read_contract(root, module["id"])


def _load_entry_signature(elements: list[dict[str, Any]], module: dict[str, Any]) -> str:
    entry_element = _find_entry_element(elements, module["entry"])
    return _format_signature(entry_element)


def _format_signature(element: dict[str, Any]) -> str:
    """Render an element as a ``def ...:`` signature line + docstring."""
    prefix = "async " if element.get("kind") == "async_function" else ""
    name = element["name"]
    params = _format_params(element.get("parameters", []))
    ret = element.get("return_annotation")
    ret_part = f" -> {ret}" if ret else ""
    header = f"{prefix}def {name}({params}){ret_part}:"
    docstring = element.get("docstring")
    if docstring:
        return f'{header}\n    """{docstring}"""'
    return header


def _format_params(params: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for p in params:
        piece = p["name"]
        ann = p.get("annotation")
        if ann:
            piece += f": {ann}"
        if p.get("has_default"):
            default = p.get("default")
            piece += f" = {default}" if default is not None else " = None"
        parts.append(piece)
    return ", ".join(parts)


def _collect_upstreams(
    pipeline: dict[str, Any], module: dict[str, Any], root: Path
) -> list[dict[str, Any]]:
    """Return upstream descriptors for pipes whose target is *module*.

    *pipeline* is a pre-loaded ``{"modules": [...], "pipes": [...]}`` dict
    so pipeline.yml is parsed only once per generate call.
    """
    pipes = pipeline.get("pipes", [])
    modules = pipeline.get("modules", [])
    inbound = [p for p in pipes if p["target"] == module["id"]]
    inbound.sort(key=lambda p: _VISIBILITY_ORDER.get(p.get("visibility", "L2"), 2))
    result: list[dict[str, Any]] = []
    modules_by_id = {m["id"]: m for m in modules}
    for pipe in inbound:
        src_id = pipe["source"]
        src_mod = modules_by_id.get(src_id)
        if src_mod is None:
            continue
        result.append(
            {
                "pipe": pipe,
                "module": src_mod,
                "contract": _load_contract_safe(root, src_mod),
            }
        )
    return result


def _load_contract_safe(root: Path, module: dict[str, Any]) -> dict[str, Any] | None:
    contract_path = sfa_dir(root) / "modules" / module["id"] / _CONTRACT_FILENAME
    if not contract_path.is_file():
        return None
    try:
        return json.loads(contract_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _render_upstream(root: Path, up: dict[str, Any], elements: list[dict[str, Any]]) -> str:
    pipe = up["pipe"]
    src_mod = up["module"]
    contract = up["contract"] or {}
    vis = pipe.get("visibility", "L2")

    parts: list[str] = []
    parts.append(f"## 上游模块：`{src_mod['id']}`（可见性 {vis}）\n")
    # L1: only the upstream Output Schema (per architecture spec).
    # L2+: additionally include the natural-language summary.
    output_schema = contract.get("output_schema")
    if output_schema:
        parts.append("- 输出 Schema：\n```json\n")
        parts.append(json.dumps(output_schema, ensure_ascii=False, indent=2))
        parts.append("\n```\n")

    if vis == "L1":
        pass
    elif vis in ("L2", "L3", "L4"):
        natural = contract.get("natural_summary")
        if natural:
            parts.append(f"- 自然语言摘要：{natural}\n")
        parts.append("- 输入输出样例：（M4 快照引擎落地后自动提供）\n")
        if vis in ("L3", "L4"):
            parts.append("- 上游函数列表：\n")
            sigs = _upstream_function_signatures(elements, up)
            if sigs:
                for sig in sigs:
                    parts.append(f"  - `{sig}`\n")
            else:
                parts.append("  - (无)\n")
        if vis == "L4":
            parts.append("- 上游模块完整源代码：\n```python\n")
            src = _read_module_source(root, src_mod)
            parts.append(src if src else "(源文件不存在)")
            parts.append("\n```\n")
    return "".join(parts) + "\n"


def _upstream_function_signatures(
    elements: list[dict[str, Any]], up: dict[str, Any]
) -> list[str]:
    src_mod = up["module"]
    owned = src_mod.get("owned_elements") or [src_mod.get("entry")]
    by_qname = {el["qualified_name"]: el for el in elements}
    sigs: list[str] = []
    for qname in owned:
        if not qname:
            continue
        el = by_qname.get(qname)
        if el is None:
            continue
        sigs.append(_format_signature(el))
    return sigs


def _read_module_source(root: Path, module: dict[str, Any]) -> str:
    path = root / module["path"]
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Code extraction
# ---------------------------------------------------------------------------


def parse_fenced_blocks(text: str) -> list[list[str]]:
    """Return all fenced ```python code blocks in *text*, in order.

    Each block is a list of lines (without the fence markers).  Unclosed
    blocks are still returned.  Shared by extract_code_block and the mock
    LLM client to avoid divergent fence-parsing logic.
    """
    lines = text.splitlines()
    in_block = False
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```python") or stripped == "```python":
            in_block = True
            current = []
            continue
        if in_block and stripped == "```":
            blocks.append(current)
            in_block = False
            current = []
            continue
        if in_block:
            current.append(line)
    if in_block:
        blocks.append(current)
    return blocks


def extract_code_block(text: str) -> str:
    """Return the first fenced ```python block, else the stripped text."""
    blocks = parse_fenced_blocks(text)
    if blocks:
        code = "\n".join(blocks[0])
    else:
        code = text.strip()
    # Ensure single trailing newline.
    return code.rstrip("\n") + "\n"


# ---------------------------------------------------------------------------
# Post-processing: import scan & side-effect detection
# ---------------------------------------------------------------------------


def scan_imports(code: str, allowed: list[str]) -> list[str]:
    """Return top-level module names in *code* not present in *allowed*."""
    allowed_set = set(allowed or [])
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    violations: list[str] = []
    seen: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top not in allowed_set and top not in seen:
                    violations.append(top)
                    seen.add(top)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # relative import
            if node.module:
                top = node.module.split(".")[0]
                if top not in allowed_set and top not in seen:
                    violations.append(top)
                    seen.add(top)
    return violations


_SIDE_EFFECT_NAMES = {"exec", "eval", "globals", "setattr"}


def detect_side_effects(code: str) -> list[str]:
    """Return human-readable warnings for global side-effect patterns."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    warnings: list[str] = []

    class _Visitor(ast.NodeVisitor):
        def visit_Assign(self, node: ast.Assign) -> None:
            for target in node.targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Attribute)
                    and isinstance(target.value.value, ast.Name)
                    and target.value.value.id == "os"
                    and target.value.attr == "environ"
                ):
                    warnings.append("检测到 os.environ 赋值（全局副作用）。")
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "sys"
                    and target.attr == "modules"
                ):
                    warnings.append("检测到 sys.modules 赋值（全局副作用）。")
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            if isinstance(func, ast.Name) and func.id in _SIDE_EFFECT_NAMES:
                warnings.append(f"检测到危险调用 {func.id}()（全局副作用）。")
            self.generic_visit(node)

    _Visitor().visit(tree)
    return warnings


# ---------------------------------------------------------------------------
# Entry range location
# ---------------------------------------------------------------------------


def locate_entry_range(
    root: Path,
    module: dict[str, Any],
    source_dir: str,
    source_bytes: bytes | None = None,
) -> tuple[int, int]:
    """Return ``(line_start, line_end)`` (1-indexed) of the entry element.

    Re-parses the module's source file with tree-sitter to stay current
    with on-disk edits.  If *source_bytes* is provided, it is used
    directly instead of re-reading the file (avoids duplicate I/O).
    """
    root = find_project_root(root)
    file_path = (root / module["path"]).resolve()
    if source_bytes is None and not file_path.is_file():
        raise SFAError(
            f"模块源文件不存在：{file_path}\n"
            f"相关模块：{module['id']}\n"
            "可操作建议：检查 sfa.yml 的 source_dir 与模块 path 是否一致，"
            "或恢复被删除的源文件。"
        )
    source_root = (root / source_dir).resolve()
    elements = _extract_file(file_path, source_root, source=source_bytes)
    target_qname = module["entry"]
    target_name = target_qname.split(".")[-1]
    for el in elements:
        if el["qualified_name"] == target_qname:
            return el["line_start"], el["line_end"]
    # Fallback: unique name match
    matches = [el for el in elements if el["name"] == target_name]
    if len(matches) == 1:
        return matches[0]["line_start"], matches[0]["line_end"]
    raise SFAError(
        f"在源文件中未找到入口元素：{target_qname}\n"
        f"相关文件：{file_path}\n"
        "可操作建议：代码可能已变更，请重新执行 `sfa extract` 后核对模块 entry。"
    )


__all__ = [
    "build_prompt",
    "extract_code_block",
    "parse_fenced_blocks",
    "scan_imports",
    "detect_side_effects",
    "locate_entry_range",
]
