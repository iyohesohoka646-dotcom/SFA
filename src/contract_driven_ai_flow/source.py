from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import libcst as cst

from .models import SymbolRef
from .paths import FlowError, inside
from .storage import file_digest


def symbols(content: str):
    tree = ast.parse(content)
    found = {}

    def walk(nodes, prefix=""):
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + node.name
                if name in found:
                    raise FlowError(f"Duplicate symbol {name}")
                found[name] = node
                walk(node.body, name + ".")
    walk(tree.body)
    return found


def symbol_text(content: str, qualname: str) -> str:
    node = symbols(content).get(qualname)
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise FlowError(f"Callable symbol not found: {qualname}")
    start = min([node.lineno] + [d.lineno for d in node.decorator_list])
    return textwrap.dedent("".join(content.splitlines(keepends=True)[start - 1:node.end_lineno]))


def read_symbol(root: Path, symbol: SymbolRef) -> str:
    content = inside(root, symbol.path).read_text(encoding="utf-8")
    value = symbol_text(content, symbol.qualname)
    if symbol.digest and file_digest(value) != symbol.digest:
        raise FlowError(f"Symbol digest changed: {symbol.path}:{symbol.qualname}")
    return value


def signature(node):
    return (type(node).__name__, node.name, ast.dump(node.args, include_attributes=False),
            ast.dump(node.returns, include_attributes=False) if node.returns else None,
            [ast.dump(d, include_attributes=False) for d in node.decorator_list], node.type_comment)


def replace_body(content: str, qualname: str, candidate: str, allowed_imports: list[str]) -> str:
    tree = ast.parse(candidate)
    if len(tree.body) != 1 or not isinstance(tree.body[0], (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise FlowError("Candidate must contain exactly the target function; extra top-level code is forbidden")
    original = symbols(content).get(qualname)
    if not isinstance(original, (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise FlowError(f"Unknown function {qualname}")
    proposed = tree.body[0]
    if signature(original) != signature(proposed):
        raise FlowError("Function signature, async mode and decorators must remain unchanged")
    for node in ast.walk(proposed):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        if isinstance(node, ast.ImportFrom):
            if node.level:
                raise FlowError("Relative imports need an explicitly declared dependency")
            names = [(node.module or "").split(".")[0]]
        if set(names) - set(allowed_imports):
            raise FlowError("Disallowed import: " + ", ".join(sorted(set(names) - set(allowed_imports))))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec", "__import__", "compile"):
            raise FlowError("Dynamic code loading is outside the accepted patch policy")
    replacement = cst.parse_module(candidate).body[0]

    class Replace(cst.CSTTransformer):
        def __init__(self):
            self.stack = []
            self.count = 0

        def visit_ClassDef(self, node):
            self.stack.append(node.name.value)

        def leave_ClassDef(self, original_node, updated_node):
            self.stack.pop()
            return updated_node

        def visit_FunctionDef(self, node):
            self.stack.append(node.name.value)

        def leave_FunctionDef(self, original_node, updated_node):
            name = ".".join(self.stack)
            self.stack.pop()
            if name == qualname:
                self.count += 1
                return updated_node.with_changes(body=replacement.body)
            return updated_node
    visitor = Replace()
    updated = cst.parse_module(content).visit(visitor).code
    if visitor.count != 1:
        raise FlowError("Expected one target symbol")
    ast.parse(updated)
    return updated


def scan_candidates(root: Path, source_dir: str = "src") -> list[dict]:
    base = inside(root, source_dir)
    candidates = []
    for path in sorted(base.rglob("*.py")):
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            continue
        content = path.read_text(encoding="utf-8")
        try:
            found = symbols(content)
        except (SyntaxError, FlowError):
            continue
        for name, node in found.items():
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                candidates.append({"symbol": {"path": path.relative_to(root).as_posix(), "qualname": name, "digest": file_digest(symbol_text(content, name))},
                                   "line": node.lineno, "summary": ast.get_docstring(node) or "", "parameters": [a.arg for a in node.args.args],
                                   "candidate_dependencies": sorted({ast.unparse(c.func) for c in ast.walk(node) if isinstance(c, ast.Call)}), "confirmed": False})
    return candidates
