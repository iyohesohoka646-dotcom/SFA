"""Version 1 bounded expression language. No eval, imports or method calls."""
from __future__ import annotations

import ast
import io
import math
import operator
import tokenize
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from .compiler import select
from .models import ProbeResult, ProbeSpec, canonical


def translate(expression: str) -> str:
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(expression).readline))
        result = []
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token.string == "$" and token.type == tokenize.ERRORTOKEN:
                index += 1
                if index >= len(tokens) or tokens[index].type != tokenize.NAME or tokens[index].string not in ("input", "output"):
                    raise ValueError("Only $input and $output are supported")
                token = tokens[index]._replace(string="_" + tokens[index].string)
            result.append((token.type, token.string))
            index += 1
        return tokenize.untokenize(result)
    except (tokenize.TokenError, IndentationError) as exc:
        raise ValueError(f"Invalid expression: {exc}") from exc


ALLOWED = (ast.Expression, ast.Constant, ast.Name, ast.Load, ast.Attribute, ast.Subscript, ast.List, ast.Tuple,
           ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.USub, ast.UAdd, ast.BinOp, ast.Add, ast.Sub,
           ast.Mult, ast.Div, ast.Mod, ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
           ast.Is, ast.IsNot, ast.In, ast.NotIn, ast.Call)
FUNCTIONS = {"len", "sum", "min", "max", "abs", "all", "any"}


def _path_exists(schema: dict, parts: list[str]) -> bool:
    if not schema or not parts:
        return True
    if "anyOf" in schema or "oneOf" in schema:
        return any(_path_exists(s, parts) for s in schema.get("anyOf", schema.get("oneOf", [])))
    if schema.get("type") == "null":
        return False
    key = parts[0]
    if key in schema.get("properties", {}):
        return _path_exists(schema["properties"][key], parts[1:])
    if schema.get("type") == "array" and key.isdigit():
        return _path_exists(schema.get("items", {}), parts[1:])
    return schema.get("additionalProperties") is not False and schema.get("type") in (None, "object")


def _attribute_path(node):
    parts = []
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        if isinstance(node, ast.Attribute):
            parts.insert(0, node.attr)
            node = node.value
        elif isinstance(node.slice, ast.Constant):
            parts.insert(0, str(node.slice.value))
            node = node.value
        else:
            return None, []
    return node.id if isinstance(node, ast.Name) else None, parts


@dataclass(frozen=True)
class Expression:
    tree: ast.Expression
    source: str

    def evaluate(self, input_value: Any, output_value: Any, budget: int = 2048) -> Any:
        gas = [budget]

        def spend(cost=1):
            gas[0] -= cost
            if gas[0] < 0:
                raise ValueError("Expression evaluation budget exhausted")

        def number(value):
            if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e100:
                raise ValueError("Arithmetic requires finite numbers within 1e100")
            return value

        def boolean(value):
            if type(value) is not bool:
                raise ValueError("Boolean operators require boolean operands")
            return value

        def visit(node):
            spend()
            if isinstance(node, ast.Constant):
                return node.value
            if isinstance(node, ast.Name):
                return {"_input": input_value, "_output": output_value}[node.id]
            if isinstance(node, (ast.List, ast.Tuple)):
                return [visit(n) for n in node.elts]
            if isinstance(node, ast.Attribute):
                return visit(node.value)[node.attr]
            if isinstance(node, ast.Subscript):
                return visit(node.value)[visit(node.slice)]
            if isinstance(node, ast.BoolOp):
                for child in node.values:
                    value = boolean(visit(child))
                    if isinstance(node.op, ast.And) and not value:
                        return False
                    if isinstance(node.op, ast.Or) and value:
                        return True
                return value
            if isinstance(node, ast.UnaryOp):
                operand = visit(node.operand)
                if isinstance(node.op, ast.Not):
                    return not boolean(operand)
                return number(-number(operand) if isinstance(node.op, ast.USub) else number(operand))
            if isinstance(node, ast.BinOp):
                left, right = number(visit(node.left)), number(visit(node.right))
                ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Mod: operator.mod}
                return number(ops[type(node.op)](left, right))
            if isinstance(node, ast.Compare):
                left = visit(node.left)
                ops = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge, ast.Is: operator.is_, ast.IsNot: operator.is_not}
                for op, child in zip(node.ops, node.comparators):
                    right = visit(child)
                    if isinstance(op, (ast.In, ast.NotIn)):
                        spend(len(right))
                        result = left in right
                        if isinstance(op, ast.NotIn):
                            result = not result
                    else:
                        spend(len(canonical(left)) // 64 + len(canonical(right)) // 64)
                        result = ops[type(op)](left, right)
                    if not result:
                        return False
                    left = right
                return True
            if isinstance(node, ast.Call):
                value = visit(node.args[0])
                name = node.func.id
                if name == "len":
                    return len(value)
                if name == "abs":
                    return abs(number(value))
                if not isinstance(value, (list, tuple)):
                    raise ValueError(f"{name} requires an array")
                spend(len(value))
                values = [boolean(v) for v in value] if name in ("all", "any") else [number(v) for v in value]
                result = {"sum": sum, "min": min, "max": max, "all": all, "any": any}[name](values)
                return result if type(result) is bool else number(result)
            raise ValueError("Unsupported expression")

        try:
            return visit(self.tree.body)
        except Exception as exc:
            raise ValueError(f"Expression error: {type(exc).__name__}: {exc}") from exc


@lru_cache(maxsize=512)
def _compile(expression: str, output_schema: str, input_schema: str) -> Expression:
    import json
    if len(expression) > 2048:
        raise ValueError("Expression exceeds 2048 characters")
    try:
        tree = ast.parse(translate(expression), mode="eval")
    except (SyntaxError, RecursionError) as exc:
        raise ValueError("Invalid expression syntax") from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > 256:
        raise ValueError("Expression exceeds 256 AST nodes")

    def depth(node):
        return 1 + max((depth(c) for c in ast.iter_child_nodes(node)), default=0)
    if depth(tree) > 24:
        raise ValueError("Expression exceeds 24 AST levels")
    schemas = {"_input": json.loads(input_schema), "_output": json.loads(output_schema)}
    for node in nodes:
        if not isinstance(node, ALLOWED):
            raise ValueError(f"Forbidden syntax: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id not in {"_input", "_output"} | FUNCTIONS:
            raise ValueError(f"Unknown name: {node.id}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ValueError("Private attributes are forbidden")
        if isinstance(node, ast.Constant) and (type(node.value) not in (str, int, float, bool, type(None)) or isinstance(node.value, str) and len(node.value) > 512):
            raise ValueError("Unsupported or oversized literal")
        if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS or len(node.args) != 1 or node.keywords):
            raise ValueError("Only len/sum/min/max/abs/all/any with one argument are allowed")
        if isinstance(node, (ast.Attribute, ast.Subscript)):
            name, parts = _attribute_path(node)
            if name in schemas and not _path_exists(schemas[name], parts):
                raise ValueError(f"Unknown contract path: {name}.{'.'.join(parts)}")
    return Expression(tree, expression)


def compile_expression(expression: str, output_schema: dict | None = None, input_schema: dict | None = None) -> Expression:
    return _compile(expression, canonical(output_schema or {}), canonical(input_schema or {}))


def evaluate_probe(probe: ProbeSpec, input_value: Any, output_value: Any, *, input_schema=None, output_schema=None, sensitive_fields=None) -> ProbeResult:
    if not probe.enabled:
        return ProbeResult(probe=probe.id, kind=probe.kind, status="skipped", policy=probe.policy)
    try:
        redacted = []
        if probe.kind in ("assertion", "branch_observer"):
            value = compile_expression(probe.expression, output_schema, input_schema).evaluate(input_value, output_value)
            if type(value) is not bool:
                raise ValueError("Assertion and branch conditions must return a boolean")
            status = "pass" if value or probe.kind == "branch_observer" else "fail"
            if probe.kind == "branch_observer":
                value = {"condition": value, "hypothetical_target": probe.true_target if value else probe.false_target}
        else:
            boundary = output_value if probe.boundary == "output" else input_value
            if sensitive_fields is not None:
                from .privacy import sanitize
                boundary = sanitize(boundary, sensitive_fields, redacted=redacted)
            selected = select(boundary, probe.pointer)
            if probe.kind == "metric":
                numbers = [v for v in selected if type(v) in (int, float)] if isinstance(selected, list) else []
                value = {"type": type(selected).__name__, "bytes": len(canonical(selected).encode("utf-8")), "count": len(selected) if isinstance(selected, (list, dict, str)) else 1}
                if numbers:
                    value.update(min=min(numbers), max=max(numbers), mean=sum(numbers) / len(numbers))
            else:
                value = selected
            status = "pass"
        return ProbeResult(probe=probe.id, kind=probe.kind, status=status, value=value, policy=probe.policy, redacted=redacted[:64])
    except Exception as exc:
        return ProbeResult(probe=probe.id, kind=probe.kind, status="error", message=str(exc), policy=probe.policy)
