"""Probe engine: DSL, persistence, validation, runtime evaluation.

M5 implements two probe types that attach to pipes:

* router  -- evaluates a condition on the source module's output and records
             which branch (on_true/on_false) was selected.  It does NOT
             alter data flow.
* assertion -- evaluates a condition and records a warning on failure.
               It does NOT stop the run.

The DSL is a restricted Python-expression subset parsed with the ``ast``
module and evaluated by a custom tree walker.  ``$output`` is the only
variable and is bound to the source module's actual output data.
"""
from __future__ import annotations

import ast
import operator as _op
import re
from pathlib import Path
from typing import Any

import yaml

from .config import SFAError, find_project_root, sfa_dir
from .contract import read_contract
from . import topology

OUTPUT_TOKEN = "$output"
_SENTINEL = "__sfa_output__"

PROBE_DIR = "probes"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ProbeDefinitionError(SFAError):
    """Invalid probe definition (DSL/validation)."""


class ProbeEvaluationError(SFAError):
    """Runtime DSL evaluation error."""


# ---------------------------------------------------------------------------
# DSL parsing & validation
# ---------------------------------------------------------------------------


def _translate(expr: str) -> str:
    """Replace ``$output`` with a valid Python identifier sentinel.

    Raises ProbeDefinitionError if any ``$`` remains after replacement.
    """
    translated = re.sub(r"\$output(?![A-Za-z0-9_])", _SENTINEL, expr)
    if "$" in translated:
        raise ProbeDefinitionError(
            f"DSL 表达式包含非法的 `$` 用法：{expr!r}\n"
            "可操作建议：仅允许使用 `$output` 作为唯一变量。"
        )
    return translated


def _parse(translated: str) -> ast.Expression:
    try:
        tree = ast.parse(translated, mode="eval")
    except SyntaxError as exc:
        raise ProbeDefinitionError(
            f"DSL 表达式语法错误：{exc.msg}\n"
            f"表达式：{translated!r}\n"
            "可操作建议：检查括号、操作符和 $output 用法。"
        ) from exc
    return tree


def _validate_ast(node: ast.AST) -> None:
    """Walk *node* and reject any AST construct outside the whitelist."""
    if isinstance(node, ast.Expression):
        _validate_ast(node.body)
        return

    if isinstance(node, ast.BoolOp):
        if not isinstance(node.op, (ast.And, ast.Or)):
            raise ProbeDefinitionError(f"DSL 不支持该布尔操作符：{type(node.op).__name__}")
        for v in node.values:
            _validate_ast(v)
        return

    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.Not, ast.USub, ast.UAdd)):
            raise ProbeDefinitionError(f"DSL 不支持该一元操作符：{type(node.op).__name__}")
        _validate_ast(node.operand)
        return

    if isinstance(node, ast.BinOp):
        if not isinstance(
            node.op,
            (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow),
        ):
            raise ProbeDefinitionError(f"DSL 不支持该二元操作符：{type(node.op).__name__}")
        _validate_ast(node.left)
        _validate_ast(node.right)
        return

    if isinstance(node, ast.Compare):
        _validate_ast(node.left)
        for op in node.ops:
            if not isinstance(
                op,
                (
                    ast.Eq,
                    ast.NotEq,
                    ast.Lt,
                    ast.LtE,
                    ast.Gt,
                    ast.GtE,
                    ast.Is,
                    ast.IsNot,
                    ast.In,
                    ast.NotIn,
                ),
            ):
                raise ProbeDefinitionError(f"DSL 不支持该比较操作符：{type(op).__name__}")
        for comp in node.comparators:
            _validate_ast(comp)
        return

    if isinstance(node, ast.Constant):
        return

    if isinstance(node, ast.List):
        for elt in node.elts:
            _validate_ast(elt)
        return

    if isinstance(node, ast.Tuple):
        for elt in node.elts:
            _validate_ast(elt)
        return

    if isinstance(node, ast.Name):
        if node.id != _SENTINEL:
            raise ProbeDefinitionError(
                f"DSL 中不允许使用除 `$output` 之外的变量：{node.id}\n"
                "可操作建议：仅使用 `$output` 作为数据源。"
            )
        return

    if isinstance(node, ast.Attribute):
        if node.attr.startswith("_"):
            raise ProbeDefinitionError(
                f"DSL 不允许访问以下划线开头的属性：{node.attr}\n"
                "可操作建议：使用正常的字段名，如 `$output.field`。"
            )
        _validate_ast(node.value)
        return

    if isinstance(node, ast.Subscript):
        _validate_ast(node.value)
        if isinstance(node.slice, ast.Constant):
            if not isinstance(node.slice.value, (int, str)):
                raise ProbeDefinitionError(
                    f"DSL 下标只支持整数或字符串常量：{node.slice.value!r}"
                )
        elif isinstance(node.slice, ast.UnaryOp) and isinstance(
            node.slice.op, ast.USub
        ):
            if not (
                isinstance(node.slice.operand, ast.Constant)
                and isinstance(node.slice.operand.value, int)
            ):
                raise ProbeDefinitionError("DSL 负下标只支持整数常量")
        else:
            raise ProbeDefinitionError(
                "DSL 下标必须是整数常量（如 `$output[0]`、`$output[-1]`）或字符串常量"
            )
        return

    raise ProbeDefinitionError(
        f"DSL 表达式包含不允许的语法：{type(node).__name__}\n"
        "可操作建议：仅使用字段访问、下标、比较、算术、布尔运算和常量。"
    )


def _extract_paths(node: ast.AST) -> list[list[str | int]]:
    """Return every ``$output.<path>`` access path found in *node*.

    Each path is a list of segments (str for attributes, int for subscripts)
    in root-to-leaf order, e.g. ``[0, 'id']`` for ``$output[0].id``.
    """

    def _slice_value(s: ast.AST) -> str | int:
        if isinstance(s, ast.Constant):
            return s.value  # type: ignore[return-value]
        if isinstance(s, ast.UnaryOp) and isinstance(s.op, ast.USub):
            operand = s.operand
            if isinstance(operand, ast.Constant) and isinstance(operand.value, int):
                return -operand.value
        raise ProbeDefinitionError("下标段提取失败")

    def _walk(n: ast.AST) -> list[list[str | int]]:
        if isinstance(n, ast.Name) and n.id == _SENTINEL:
            return [[]]
        if isinstance(n, ast.Attribute):
            return [p + [n.attr] for p in _walk(n.value)]
        if isinstance(n, ast.Subscript):
            key = _slice_value(n.slice)
            return [p + [key] for p in _walk(n.value)]
        # Recurse into other whitelisted nodes to find nested $output references.
        result: list[list[str | int]] = []
        for child in ast.iter_child_nodes(n):
            result.extend(_walk(child))
        return result

    return _walk(node)


def _is_object_schema(schema: dict[str, Any] | None) -> bool:
    if not isinstance(schema, dict):
        return False
    if "anyOf" in schema:
        return any(_is_object_schema(alt) for alt in schema["anyOf"])
    if "properties" in schema or "additionalProperties" in schema:
        return True
    t = schema.get("type")
    if t == "object":
        return True
    if isinstance(t, list) and "object" in t:
        return True
    return False


def _is_array_schema(schema: dict[str, Any] | None) -> bool:
    if not isinstance(schema, dict):
        return False
    if "anyOf" in schema:
        return any(_is_array_schema(alt) for alt in schema["anyOf"])
    t = schema.get("type")
    if t == "array":
        return True
    if isinstance(t, list) and "array" in t:
        return True
    return False


def _check_paths_against_schema(
    paths: list[list[str | int]], output_schema: dict[str, Any]
) -> None:
    """Validate extracted access paths against the source output schema.

    Unknown schemas (``{}``) are allowed.  Missing properties that are not
    explicitly forbidden by ``additionalProperties: false`` are allowed.
    """
    if not isinstance(output_schema, dict) or output_schema == {}:
        return

    for path in paths:
        _check_path(path, output_schema)


def _format_path(path: list[str | int]) -> str:
    """Render a path like ``[0, 'id']`` as ``$output[0].id``."""
    parts = ["$output"]
    for seg in path:
        if isinstance(seg, int):
            parts.append(f"[{seg}]")
        else:
            parts.append(f".{seg}")
    return "".join(parts)


def _check_path(path: list[str | int], schema: dict[str, Any]) -> None:
    current: Any = schema
    for i, segment in enumerate(path):
        if not isinstance(current, dict) or current == {}:
            # Unknown/open schema: cannot validate further.
            return

        path_so_far = _format_path(path[: i + 1])

        if isinstance(segment, str):
            if not _is_object_schema(current):
                raise ProbeDefinitionError(
                    f"路径 {path_so_far} 需要对象类型的输出，"
                    f"但当前 schema 为：{current}"
                )
            props = current.get("properties", {})
            if segment in props:
                current = props[segment]
                continue
            additional = current.get("additionalProperties")
            if additional is False:
                raise ProbeDefinitionError(
                    f"路径 {path_so_far} 在输出 schema 中未声明，"
                    f"且 additionalProperties 为 false"
                )
            if isinstance(additional, dict):
                current = additional
                continue
            # missing / true / {} -- cannot verify deeper, stop.
            return

        if isinstance(segment, int):
            if not _is_array_schema(current):
                raise ProbeDefinitionError(
                    f"路径 {path_so_far} 需要数组类型的输出，"
                    f"但当前 schema 为：{current}"
                )
            prefix_items = current.get("prefixItems")
            if prefix_items is not None and 0 <= segment < len(prefix_items):
                current = prefix_items[segment]
            else:
                items = current.get("items")
                if isinstance(items, dict):
                    current = items
                else:
                    return
            continue

        raise ProbeDefinitionError(f"不支持的 schema 路径段：{segment!r}")


def validate_condition(expr: str, output_schema: dict[str, Any]) -> ast.Expression:
    """Parse *expr*, validate AST whitelist and schema paths.

    Returns the AST for later evaluation.  Raises ProbeDefinitionError on
    any validation failure.
    """
    translated = _translate(expr)
    tree = _parse(translated)
    _validate_ast(tree)
    paths = _extract_paths(tree)
    _check_paths_against_schema(paths, output_schema)
    return tree


# ---------------------------------------------------------------------------
# DSL evaluator
# ---------------------------------------------------------------------------


def evaluate(tree: ast.Expression, output: Any) -> Any:
    """Evaluate a previously validated DSL expression against *output*."""
    return _eval_node(tree.body, output)


def _eval_node(node: ast.AST, output: Any) -> Any:
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Name):
        if node.id == _SENTINEL:
            return output
        raise ProbeEvaluationError(f"未知的 DSL 变量：{node.id}")

    if isinstance(node, ast.Attribute):
        value = _eval_node(node.value, output)
        if not isinstance(value, dict):
            raise ProbeEvaluationError(
                f"无法访问字段 {node.attr!r}：数据不是字典（得到 {type(value).__name__}）"
            )
        try:
            return value[node.attr]
        except KeyError as exc:
            raise ProbeEvaluationError(
                f"字段 {node.attr!r} 在输出中不存在。可用字段：{list(value.keys())}"
            ) from exc

    if isinstance(node, ast.Subscript):
        value = _eval_node(node.value, output)
        key = _eval_slice(node.slice, output)
        try:
            return value[key]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProbeEvaluationError(
                f"下标访问失败：{value!r}[{key!r}]"
            ) from exc

    if isinstance(node, ast.List):
        return [_eval_node(elt, output) for elt in node.elts]

    if isinstance(node, ast.Tuple):
        return tuple(_eval_node(elt, output) for elt in node.elts)

    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand, output)
        if isinstance(node.op, ast.Not):
            return not operand
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return +operand
        raise ProbeEvaluationError(f"不支持的一元操作符：{type(node.op).__name__}")

    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, output)
        right = _eval_node(node.right, output)
        op_map = {
            ast.Add: _op.add,
            ast.Sub: _op.sub,
            ast.Mult: _op.mul,
            ast.Div: _op.truediv,
            ast.FloorDiv: _op.floordiv,
            ast.Mod: _op.mod,
            ast.Pow: _op.pow,
        }
        op_type = type(node.op)
        if op_type not in op_map:
            raise ProbeEvaluationError(f"不支持的二元操作符：{op_type.__name__}")
        try:
            return op_map[op_type](left, right)
        except (TypeError, ValueError, ZeroDivisionError) as exc:
            raise ProbeEvaluationError(
                f"二元运算失败：{left!r} {op_type.__name__} {right!r}"
            ) from exc

    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result = True
            for v in node.values:
                result = _eval_node(v, output)
                if not result:
                    return result
            return result
        if isinstance(node.op, ast.Or):
            result = False
            for v in node.values:
                result = _eval_node(v, output)
                if result:
                    return result
            return result
        raise ProbeEvaluationError(f"不支持的布尔操作符：{type(node.op).__name__}")

    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, output)
        for op, comp in zip(node.ops, node.comparators):
            right = _eval_node(comp, output)
            try:
                if isinstance(op, ast.Eq):
                    ok = left == right
                elif isinstance(op, ast.NotEq):
                    ok = left != right
                elif isinstance(op, ast.Lt):
                    ok = left < right
                elif isinstance(op, ast.LtE):
                    ok = left <= right
                elif isinstance(op, ast.Gt):
                    ok = left > right
                elif isinstance(op, ast.GtE):
                    ok = left >= right
                elif isinstance(op, ast.Is):
                    ok = left is right
                elif isinstance(op, ast.IsNot):
                    ok = left is not right
                elif isinstance(op, ast.In):
                    ok = left in right
                elif isinstance(op, ast.NotIn):
                    ok = left not in right
                else:
                    raise ProbeEvaluationError(f"不支持的比较操作符：{type(op).__name__}")
            except TypeError as exc:
                raise ProbeEvaluationError(
                    f"比较运算失败：{left!r} {type(op).__name__} {right!r}"
                ) from exc
            if not ok:
                return False
            left = right
        return True

    raise ProbeEvaluationError(f"DSL 求值时遇到未支持的节点：{type(node).__name__}")


def _eval_slice(node: ast.AST, output: Any) -> str | int:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, str)):
            return node.value
        raise ProbeEvaluationError(f"下标必须是整数或字符串：{node.value!r}")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        operand = node.operand
        if isinstance(operand, ast.Constant) and isinstance(operand.value, int):
            return -operand.value
    raise ProbeEvaluationError("DSL 下标求值失败")


def _condition_text(tree: ast.Expression) -> str:
    """Reconstruct the original human-readable condition from the AST.

    The sentinel is translated back to ``$output``.
    """
    source = ast.unparse(tree)
    return source.replace(_SENTINEL, OUTPUT_TOKEN)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _probes_dir(root: Path) -> Path:
    return sfa_dir(root) / PROBE_DIR


def _probe_path(root: Path, probe_id: str) -> Path:
    return _probes_dir(root) / f"{probe_id}.yml"


def _load_probe(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data["id"] = path.stem
    return data


def list_probes(root: Path) -> list[dict[str, Any]]:
    root = find_project_root(root)
    base = _probes_dir(root)
    if not base.is_dir():
        return []
    probes: list[dict[str, Any]] = []
    for path in sorted(base.glob("*.yml")):
        probes.append(_load_probe(path))
    return probes


def get_probe(root: Path, probe_id: str) -> dict[str, Any] | None:
    root = find_project_root(root)
    path = _probe_path(root, probe_id)
    if not path.is_file():
        return None
    return _load_probe(path)


def find_probe(root: Path, probe_id: str) -> dict[str, Any]:
    probe = get_probe(root, probe_id)
    if probe is None:
        raise SFAError(
            f"探针不存在：{probe_id}\n"
            f"相关目录：{_probes_dir(root)}\n"
            "可操作建议：执行 `sfa probe list` 查看现有探针。"
        )
    return probe


def write_probe(root: Path, probe: dict[str, Any]) -> Path:
    root = find_project_root(root)
    probe_id = probe["id"]
    base = _probes_dir(root)
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{probe_id}.yml"
    payload = {k: v for k, v in probe.items() if k != "id"}
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path


def remove_probe(root: Path, probe_id: str) -> dict[str, Any]:
    root = find_project_root(root)
    probe = find_probe(root, probe_id)
    _probe_path(root, probe_id).unlink()
    return probe


def list_probes_for_pipe(root: Path, pipe_id: str) -> list[dict[str, Any]]:
    return [p for p in list_probes(root) if p.get("pipe") == pipe_id]


def remove_probes_for_pipe(root: Path, pipe_id: str) -> list[dict[str, Any]]:
    root = find_project_root(root)
    removed: list[dict[str, Any]] = []
    for probe in list_probes_for_pipe(root, pipe_id):
        _probe_path(root, probe["id"]).unlink()
        removed.append(probe)
    return removed


def remove_probes_referencing_module(root: Path, module_id: str) -> list[dict[str, Any]]:
    root = find_project_root(root)
    removed: list[dict[str, Any]] = []
    for probe in list_probes(root):
        if probe.get("on_true") == module_id or probe.get("on_false") == module_id:
            _probe_path(root, probe["id"]).unlink()
            removed.append(probe)
    return removed


# ---------------------------------------------------------------------------
# Definition-time validation
# ---------------------------------------------------------------------------


def _assert_pipe_and_source_target(
    root: Path, pipe_id: str
) -> tuple[dict[str, Any], str, str]:
    pipe = topology.find_pipe(root, pipe_id)
    source = pipe["source"]
    target = pipe["target"]
    source_mod = topology.find_module(root, source)
    target_mod = topology.find_module(root, target)
    if source_mod.get("type") != "atomic" or target_mod.get("type") != "atomic":
        raise ProbeDefinitionError(
            f"探针只能挂载在原子模块之间的管道上：{pipe_id}\n"
            "可操作建议：确认管道两端都是原子模块。"
        )
    return pipe, source, target


def _validate_router_branches(
    root: Path,
    pipe: dict[str, Any],
    source: str,
    target: str,
    on_true: str,
    on_false: str,
) -> None:
    if on_true != target:
        raise ProbeDefinitionError(
            f"路由器探针的 on_true 必须等于挂载管道的目标模块：{on_true} != {target}\n"
            "可操作建议：on_true 应为管道本身的 target。"
        )
    if on_true == on_false:
        raise ProbeDefinitionError(
            "路由器探针的 on_true 和 on_false 不能相同。\n"
            "可操作建议：指定两个不同的分支目标。"
        )
    topology.find_module(root, on_true)
    topology.find_module(root, on_false)
    if topology.find_pipe_by_endpoints(root, source, on_false) is None:
        raise ProbeDefinitionError(
            f"路由器 on_false 分支缺少管道：{source} -> {on_false}\n"
            "可操作建议：先执行 `sfa pipe add {src} {tgt}` 创建分支管道。".format(
                src=source, tgt=on_false
            )
        )


def _ensure_unique_probe_id(root: Path, probe_id: str) -> None:
    if get_probe(root, probe_id) is not None:
        raise ProbeDefinitionError(
            f"探针 ID 已存在：{probe_id}\n"
            "可操作建议：使用不同的名称，或先执行 `sfa probe remove {id}` 删除现有探针。".format(
                id=probe_id
            )
        )


def add_router_probe(
    root: Path,
    name: str,
    pipe_id: str,
    condition: str,
    on_true: str,
    on_false: str,
) -> dict[str, Any]:
    root = find_project_root(root)
    probe_id = topology.sanitize_id(name)
    _ensure_unique_probe_id(root, probe_id)

    pipe, source, target = _assert_pipe_and_source_target(root, pipe_id)
    _validate_router_branches(root, pipe, source, target, on_true, on_false)

    contract = read_contract(root, source)
    validate_condition(condition, contract.get("output_schema") or {})

    probe: dict[str, Any] = {
        "id": probe_id,
        "name": name,
        "type": "router",
        "pipe": pipe_id,
        "condition": condition,
        "on_true": on_true,
        "on_false": on_false,
    }
    write_probe(root, probe)
    return probe


def add_assertion_probe(
    root: Path,
    name: str,
    pipe_id: str,
    condition: str,
) -> dict[str, Any]:
    root = find_project_root(root)
    probe_id = topology.sanitize_id(name)
    _ensure_unique_probe_id(root, probe_id)

    pipe, source, _target = _assert_pipe_and_source_target(root, pipe_id)

    contract = read_contract(root, source)
    validate_condition(condition, contract.get("output_schema") or {})

    probe: dict[str, Any] = {
        "id": probe_id,
        "name": name,
        "type": "assertion",
        "pipe": pipe_id,
        "condition": condition,
    }
    write_probe(root, probe)
    return probe


# ---------------------------------------------------------------------------
# Runtime helpers
# ---------------------------------------------------------------------------


def load_probes_by_source(
    root: Path,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Return ``(probes_by_source, orphan_probe_results)``.

    Probes whose attached pipe no longer exists become orphan results and are
    reported directly in the run manifest.
    """
    root = find_project_root(root)
    by_source: dict[str, list[dict[str, Any]]] = {}
    orphans: list[dict[str, Any]] = []
    for probe in list_probes(root):
        pipe_id = probe.get("pipe")
        pipe = topology.get_pipe(root, pipe_id) if pipe_id else None
        if pipe is None:
            orphans.append(
                {
                    "probe_id": probe["id"],
                    "type": probe.get("type"),
                    "pipe": pipe_id,
                    "source": None,
                    "condition": probe.get("condition"),
                    "status": "orphan",
                    "error": f"管道不存在：{pipe_id}",
                }
            )
            continue
        source = pipe["source"]
        by_source.setdefault(source, []).append(probe)
    return by_source, orphans


def format_assertion_failure(
    tree: ast.Expression, output: Any, condition_text: str
) -> str:
    """Render a human-readable expected-vs-actual message for a failed assertion."""
    body = tree.body
    if isinstance(body, ast.Compare) and len(body.ops) == 1:
        left = evaluate(ast.Expression(body=body.left), output)
        right = evaluate(ast.Expression(body=body.comparators[0]), output)
        op_sym = _op_symbol(body.ops[0])
        return f"断言失败：{condition_text} → {left!r} {op_sym} {right!r} 为 False"
    return f"断言失败：{condition_text} 求值为 False"


def _op_symbol(op: ast.cmpop) -> str:
    mapping = {
        ast.Eq: "==",
        ast.NotEq: "!=",
        ast.Lt: "<",
        ast.LtE: "<=",
        ast.Gt: ">",
        ast.GtE: ">=",
        ast.Is: "is",
        ast.IsNot: "is not",
        ast.In: "in",
        ast.NotIn: "not in",
    }
    return mapping.get(type(op), type(op).__name__)


def evaluate_probe(probe: dict[str, Any], output: Any) -> dict[str, Any]:
    """Evaluate *probe* against *output* and return a result dict.

    Raises ProbeEvaluationError; callers should catch and record it.
    """
    condition = probe["condition"]
    tree = validate_condition(condition, {})  # already validated at definition time
    condition_text = _condition_text(tree)
    value = evaluate(tree, output)

    result: dict[str, Any] = {
        "probe_id": probe["id"],
        "type": probe["type"],
        "pipe": probe.get("pipe"),
        "condition": condition_text,
    }

    if probe["type"] == "router":
        condition_result = bool(value)
        branch = "on_true" if condition_result else "on_false"
        result.update(
            {
                "condition_result": condition_result,
                "branch": branch,
                "branch_target": probe[branch],
            }
        )
    else:
        passed = bool(value)
        result["passed"] = passed
        if not passed:
            result["message"] = format_assertion_failure(tree, output, condition_text)

    return result


__all__ = [
    "ProbeDefinitionError",
    "ProbeEvaluationError",
    "OUTPUT_TOKEN",
    "validate_condition",
    "evaluate",
    "format_assertion_failure",
    "evaluate_probe",
    "add_router_probe",
    "add_assertion_probe",
    "list_probes",
    "find_probe",
    "remove_probe",
    "list_probes_for_pipe",
    "remove_probes_for_pipe",
    "remove_probes_referencing_module",
    "load_probes_by_source",
    "write_probe",
]
