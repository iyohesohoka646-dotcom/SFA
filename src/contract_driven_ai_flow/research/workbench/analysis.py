"""A bounded AST projection. Importing a document never imports its code."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from ..agent.privacy import clean_text
from ..agent.source import read_source, cached_source_segment
from .models import AnalysisDocument, Relation, SourceObject
from .semantics import read_names


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def base_name(node):
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def targets(node):
    if isinstance(node, (ast.Tuple, ast.List)):
        return [name for part in node.elts for name in targets(part)]
    name = base_name(node)
    return [name] if name else []


def analyze_source(
    path: Path, *, archived_text=None, expected_digest=None
) -> AnalysisDocument:
    path = path.expanduser().resolve()
    if path.suffix != ".py" or archived_text is None and not path.is_file():
        raise ValueError("Select an existing Python source file")
    if (
        path.stat().st_size
        if archived_text is None
        else len(archived_text.encode("utf-8"))
    ) > 10 * 1024 * 1024:
        raise ValueError("Source exceeds 10 MiB")
    source = read_source(path) if archived_text is None else None
    text = source.text if source else archived_text
    source_digest = source.digest if source else digest(text)
    if expected_digest is not None and source_digest != expected_digest:
        raise ValueError(
            "Archived source is redacted or incomplete; historical graph cannot be reconstructed"
        )
    doc = AnalysisDocument(path=str(path), source_digest=source_digest)
    try:
        tree = ast.parse(text)
    except SyntaxError as error:
        doc.diagnostics.append(f"Syntax diagnostic at line {error.lineno}: {error.msg}")
        return doc
    bindings: dict[tuple[str, str], set[str]] = {}
    local_names: dict[str, set[str]] = {}
    lines = text.splitlines(keepends=True)
    byte_lines = [line.encode("utf-8") for line in lines]

    def resolve(scope, name):
        current = scope
        while current:
            if (current, name) in bindings:
                return bindings[(current, name)]
            if name in local_names.get(current, set()):
                return set()
            current = (
                current.rsplit(".", 1)[0]
                if "." in current
                else ("<module>" if current != "<module>" else "")
            )
        return set()

    def add(node, name, scope, kind, mutation=False, reads=()):
        if len(doc.objects) >= 4096:
            if not doc.diagnostics:
                doc.diagnostics.append(
                    "Projection exceeds 4096 objects; select a smaller source"
                )
            return None
        qualname = name if scope == "<module>" else scope + "." + name
        start = min(
            [node.lineno, *[d.lineno for d in getattr(node, "decorator_list", [])]]
        )
        end = getattr(node, "end_lineno", node.lineno)
        code = (
            "".join(lines[start - 1 : end])
            if kind in ("function", "class")
            else cached_source_segment(byte_lines, node)
        )
        column, end_column = getattr(node, "col_offset", 0), getattr(
            node, "end_col_offset", 0
        )
        logical_key = f"{path}::{scope}::{name}"
        object_id = digest(
            f"{logical_key}\0{start}:{column}:{end}:{end_column}\0{source_digest}"
        )[:24]
        dependencies = list(dict.fromkeys(reads))
        obj = SourceObject(
            id=object_id,
            path=str(path),
            qualname=qualname,
            name=name,
            scope=scope,
            kind=kind,
            line=start,
            end_line=end,
            source_digest=source_digest,
            code=clean_text(code, 16384),
            inputs=dependencies,
            mutation=mutation,
            column=column,
            end_column=end_column,
            logical_key=logical_key,
        )
        for dep in dependencies:
            for source_id in sorted(resolve(scope, dep)):
                if source_id != object_id:
                    doc.relations.append(
                        Relation(source=source_id, target=object_id, label=dep)
                    )
        doc.objects.append(obj)
        bindings[(scope, name)] = {object_id}
        return obj

    def visit(body, scope):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                add(
                    node,
                    node.name,
                    scope,
                    "class" if isinstance(node, ast.ClassDef) else "function",
                )
                child = node.name if scope == "<module>" else scope + "." + node.name
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    from .semantics import lexical_bindings

                    local_names[child] = lexical_bindings(node)
                    for parameter in (
                        *node.args.posonlyargs,
                        *node.args.args,
                        *node.args.kwonlyargs,
                    ):
                        add(parameter, parameter.arg, child, "parameter")
                visit(node.body, child)
            elif isinstance(node, ast.If):
                before = {key: set(value) for key, value in bindings.items()}
                visit(node.body, scope)
                true_path = {key: set(value) for key, value in bindings.items()}
                bindings.clear()
                bindings.update(before)
                visit(node.orelse, scope)
                false_path = dict(bindings)
                bindings.clear()
                for key in true_path.keys() | false_path.keys():
                    bindings[key] = true_path.get(key, set()) | false_path.get(
                        key, set()
                    )
            elif isinstance(node, (ast.For, ast.While, ast.AsyncFor)):
                before = {key: set(value) for key, value in bindings.items()}
                if isinstance(node, (ast.For, ast.AsyncFor)):
                    for name in targets(node.target):
                        add(
                            node.target,
                            name,
                            scope,
                            "assignment",
                            reads=read_names(node.iter),
                        )
                visit(node.body, scope)
                for key, value in before.items():
                    bindings[key] = bindings.get(key, set()) | value
                visit(node.orelse, scope)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    add(node, alias.asname or alias.name.split(".")[0], scope, "import")
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    if item.optional_vars:
                        for name in targets(item.optional_vars):
                            add(
                                item.optional_vars,
                                name,
                                scope,
                                "assignment",
                                reads=read_names(item.context_expr),
                            )
                visit(node.body, scope)
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                writes = node.targets if isinstance(node, ast.Assign) else [node.target]
                reads = read_names(node.value)
                for target in writes:
                    mutating = isinstance(node, ast.AugAssign) or isinstance(
                        target, (ast.Attribute, ast.Subscript)
                    )
                    for name in targets(target):
                        add(
                            node,
                            name,
                            scope,
                            "assignment",
                            mutating,
                            [*reads, *([name] if mutating else [])],
                        )
            else:
                for child_body in ("body", "orelse", "finalbody"):
                    visit(getattr(node, child_body, []), scope)
                for handler in getattr(node, "handlers", []):
                    visit(handler.body, scope)

    visit(tree.body, "<module>")
    from .semantics import build_graph

    doc.graph = build_graph(tree, text, str(path), source_digest, doc.objects)
    return doc
