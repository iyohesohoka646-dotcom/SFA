"""A bounded AST projection. Importing a document never imports its code."""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from ..agent.privacy import clean_text
from .models import AnalysisDocument, Relation, SourceObject


def digest(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def base_name(node):
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def targets(node):
    if isinstance(node, (ast.Tuple, ast.List)):
        return [name for part in node.elts for name in targets(part)]
    name = base_name(node)
    return [name] if name else []


def analyze_source(path: Path) -> AnalysisDocument:
    path = path.expanduser().resolve()
    if path.suffix != '.py' or not path.is_file():
        raise ValueError('Select an existing Python source file')
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError('Source exceeds 10 MiB')
    text = path.read_text(encoding='utf-8-sig')
    source_digest = digest(text)
    doc = AnalysisDocument(path=str(path), source_digest=source_digest)
    try:
        tree = ast.parse(text)
    except SyntaxError as error:
        doc.diagnostics.append(f'Syntax diagnostic at line {error.lineno}: {error.msg}')
        return doc
    bindings: dict[tuple[str, str], str] = {}
    lines = text.splitlines(keepends=True)

    def resolve(scope, name):
        current = scope
        while current:
            if (current, name) in bindings:
                return bindings[(current, name)]
            current = current.rsplit('.', 1)[0] if '.' in current else ('<module>' if current != '<module>' else '')
        return None

    def add(node, name, scope, kind, mutation=False, reads=()):
        if len(doc.objects) >= 4096:
            if not doc.diagnostics:
                doc.diagnostics.append('Projection exceeds 4096 objects; select a smaller source')
            return None
        qualname = name if scope == '<module>' else scope + '.' + name
        start = min([node.lineno, *[d.lineno for d in getattr(node, 'decorator_list', [])]])
        end = getattr(node, 'end_lineno', node.lineno)
        code = ''.join(lines[start - 1:end])
        object_id = digest(f'{path}\0{qualname}\0{start}\0{source_digest}')[:24]
        dependencies = list(dict.fromkeys(reads))
        obj = SourceObject(id=object_id, path=str(path), qualname=qualname, name=name,
            scope=scope, kind=kind, line=start, end_line=end, source_digest=source_digest,
            code=clean_text(code, 16384), inputs=dependencies, mutation=mutation)
        for dep in dependencies:
            source_id = resolve(scope, dep)
            if source_id and source_id != object_id:
                doc.relations.append(Relation(source=source_id, target=object_id, label=dep))
        doc.objects.append(obj)
        bindings[(scope, name)] = object_id
        return obj

    def visit(body, scope):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                add(node, node.name, scope, 'class' if isinstance(node, ast.ClassDef) else 'function')
                child = node.name if scope == '<module>' else scope + '.' + node.name
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for parameter in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
                        add(parameter, parameter.arg, child, 'parameter')
                visit(node.body, child)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    add(node, alias.asname or alias.name.split('.')[0], scope, 'import')
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                writes = node.targets if isinstance(node, ast.Assign) else [node.target]
                reads = [part.id for part in ast.walk(node.value) if isinstance(part, ast.Name) and isinstance(part.ctx, ast.Load)] if node.value else []
                for target in writes:
                    mutating = isinstance(node, ast.AugAssign) or isinstance(target, (ast.Attribute, ast.Subscript))
                    for name in targets(target):
                        add(node, name, scope, 'assignment', mutating, [*reads, *([name] if mutating else [])])
            else:
                for child_body in ('body', 'orelse', 'finalbody'):
                    visit(getattr(node, child_body, []), scope)
                for handler in getattr(node, 'handlers', []):
                    visit(handler.body, scope)
    visit(tree.body, '<module>')
    return doc
