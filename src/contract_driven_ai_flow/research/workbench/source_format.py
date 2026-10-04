"""A model may improve writing, but cannot rewrite the computation."""

from __future__ import annotations

import ast
import io
import tokenize


def verify_format(original: str, candidate: str) -> None:
    def tree(text):
        parsed = ast.parse(text, type_comments=True)
        statements = []

        def visit(node, path=()):
            if isinstance(node, ast.stmt):
                statements.append((node, path))
            for field, value in ast.iter_fields(node):
                if isinstance(value, ast.AST):
                    visit(value, (*path, field))
                elif isinstance(value, list):
                    for index, item in enumerate(value):
                        if isinstance(item, ast.AST):
                            visit(item, (*path, field, index))

        visit(parsed)
        ignores = []
        # TypeIgnore.lineno is a field rather than an AST location attribute.
        for ignore in parsed.type_ignores:
            enclosing = [(node, path) for node, path in statements if node.lineno <= ignore.lineno <= node.end_lineno]
            smallest = min((node.end_lineno - node.lineno for node, _ in enclosing), default=None)
            ignores.append((ignore.tag, tuple(path for node, path in enclosing if node.end_lineno - node.lineno == smallest)))
            ignore.lineno = 0
        return ast.dump(parsed, include_attributes=False), ignores

    if tree(original) != tree(candidate):
        raise ValueError("Formatting must preserve the Python AST, expressions, declarations and statement order")
    def comments(text):
        return [t.string for t in tokenize.generate_tokens(io.StringIO(text).readline) if t.type == tokenize.COMMENT]
    if comments(original) != comments(candidate):
        raise ValueError("Formatting must preserve existing comments and research annotations")
    before, after = original.splitlines(), candidate.splitlines()
    for index, line in enumerate(before[:2]):
        if line.startswith('#!') or 'coding:' in line or 'coding=' in line:
            if len(after) <= index or line != after[index]:
                raise ValueError("Source interpreter and encoding headers must remain at their original positions")
