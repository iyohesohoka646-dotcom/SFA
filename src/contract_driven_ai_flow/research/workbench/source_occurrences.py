"""Token spans resolved by Python lexical scope, without executing source.

The supplied text is the authorized display archive. Its columns may differ
from original source after redaction, so object IDs are joined by definition
order and line rather than replacing any persisted identity.
"""

from __future__ import annotations

import ast
import io
import tokenize
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .models import AnalysisDocument


class _Bindings(ast.NodeVisitor):
    def __init__(self):
        self.names, self.globals, self.nonlocals = set(), set(), set()

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)

    def visit_Global(self, node):
        self.globals.update(node.names)

    def visit_Nonlocal(self, node):
        self.nonlocals.update(node.names)

    def visit_FunctionDef(self, node):
        self.names.add(node.name)
        parameters = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs,
                      *([node.args.vararg] if node.args.vararg else []),
                      *([node.args.kwarg] if node.args.kwarg else []))
        # Header expressions run in the enclosing scope. Collect their
        # bindings without descending into the nested function body.
        for expression in (*node.decorator_list, *node.args.defaults, *node.args.kw_defaults,
                           *(parameter.annotation for parameter in parameters), node.returns):
            if expression is not None:
                self.visit(expression)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self.names.add(node.name)
        for expression in (*node.decorator_list, *node.bases, *(item.value for item in node.keywords)):
            self.visit(expression)

    def visit_Lambda(self, node):
        for expression in (*node.args.defaults, *node.args.kw_defaults):
            if expression is not None:
                self.visit(expression)

    def visit_Import(self, node):
        self.names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)

    visit_ImportFrom = visit_Import

    def visit_ExceptHandler(self, node):
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_MatchAs(self, node):
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)

    visit_MatchStar = visit_MatchAs

    def visit_MatchMapping(self, node):
        if node.rest:
            self.names.add(node.rest)
        self.generic_visit(node)

    def visit_ListComp(self, node):
        # Iteration targets are comprehension locals. A walrus in its
        # expressions still binds in the enclosing non-comprehension scope.
        for generator in node.generators:
            self.visit(generator.iter)
            for condition in generator.ifs:
                self.visit(condition)
        for expression in ((node.key, node.value) if isinstance(node, ast.DictComp) else (node.elt,)):
            self.visit(expression)

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp


@dataclass(eq=False)
class _Scope:
    name: str
    syntactic_name: str
    kind: str
    parent: _Scope | None = None
    names: set[str] = field(default_factory=set)
    globals: set[str] = field(default_factory=set)
    nonlocals: set[str] = field(default_factory=set)
    bound_names: set[str] = field(default_factory=set)


def _utf16(text):
    return len(text.encode("utf-16-le")) // 2


class _Occurrences(ast.NodeVisitor):
    def __init__(self, analysis, text, tree):
        self.analysis = analysis
        self.lines = text.splitlines()
        self.tokens = defaultdict(list)
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.NAME:
                self.tokens[token.start[0]].append(token)
        self.objects = defaultdict(list)
        for obj in sorted(analysis.objects, key=lambda obj: (obj.line, obj.column)):
            self.objects[(obj.scope, obj.name)].append(obj)
        self.claimed, self.records = set(), {}
        self.scope_counts = Counter()

        def count(body, scope):
            for node in body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    child = node.name if scope == "<module>" else scope + "." + node.name
                    self.scope_counts[child] += 1
                    count(node.body, child)
                else:
                    for field_name in ("body", "orelse", "finalbody"):
                        count(getattr(node, field_name, []), scope)
                    for handler in getattr(node, "handlers", []):
                        count(handler.body, scope)

        count(tree.body, "<module>")
        self.root = self.scope = self._scope("<module>", "<module>", "module", None, tree.body)

    @staticmethod
    def _scope(name, syntactic_name, kind, parent, body, args=None):
        bindings = _Bindings()
        for node in body:
            bindings.visit(node)
        if args:
            bindings.names.update(arg.arg for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs))
            bindings.names.update(arg.arg for arg in (args.vararg, args.kwarg) if arg)
        return _Scope(name, syntactic_name, kind, parent, bindings.names - bindings.globals - bindings.nonlocals, bindings.globals, bindings.nonlocals)

    def owner(self, scope, name, *, definition=False):
        if name in scope.globals:
            return self.root
        if name in scope.nonlocals:
            parent = scope.parent
            while parent:
                if parent.kind in ("function", "lambda") and name in parent.names:
                    return parent
                parent = parent.parent
            return None
        if scope.kind == "class" and (definition or name in scope.bound_names):
            return scope
        if scope.kind == "class" and name in scope.names:
            # A class-local LOAD_NAME with no current namespace binding falls
            # back to globals, even when a method captures an outer cell of
            # the same name. Undeclared class freevars use the parent below.
            return self.root
        if scope.kind != "class" and (name in scope.names or scope.kind == "module"):
            return scope
        parent = scope.parent
        while parent:
            # Methods/lambdas/comprehensions do not close over a class dict.
            if parent.kind != "class":
                return self.owner(parent, name)
            parent = parent.parent
        return self.root

    def token_span(self, token):
        line, column = token.start
        end_line, end_column = token.end
        return {"line": line, "end_line": end_line,
                "column": _utf16(self.lines[line - 1][:column]),
                "end_column": _utf16(self.lines[end_line - 1][:end_column])}

    def node_span(self, node, name=None):
        line, byte_column = node.lineno, node.col_offset
        prefix = self.lines[line - 1].encode("utf-8")[:byte_column].decode("utf-8")
        column = len(prefix)
        if name is not None:
            token = next((token for token in self.tokens[line] if token.start[1] == column), None)
            if token:
                return self.token_span(token)
        end_line = node.end_lineno
        end_prefix = self.lines[end_line - 1].encode("utf-8")[:node.end_col_offset].decode("utf-8")
        return {"line": line, "end_line": end_line, "column": _utf16(prefix), "end_column": _utf16(end_prefix)}

    def named_span(self, node, name, *, last=False):
        matches = [token for line in range(node.lineno, node.end_lineno + 1)
                   for token in self.tokens[line] if token.string == name]
        if not matches:
            return None
        return self.token_span(matches[-1] if last else matches[0])

    def emit(self, name, span, role, *, scope=None, kind=None, bind=True, read_owner=False):
        scope = scope or self.scope
        owner = self.owner(scope, name, definition=role == "definition" and not read_owner)
        if owner is None or span is None:
            return
        key = f"{self.analysis.path}::{owner.name}::{name}"
        record = self.records.setdefault(key, {"logical_key": key, "logical_keys": [key], "object_ids": [],
                                               "name": name, "scope": owner.name, "occurrences": []})
        occurrence = {**span, "role": role}
        if occurrence not in record["occurrences"]:
            record["occurrences"].append(occurrence)
        if role != "definition":
            return
        if bind and owner is scope and scope.kind == "class":
            scope.bound_names.add(name)
        for obj in self.objects.get((scope.syntactic_name, name), []):
            if obj.id in self.claimed or not obj.line <= span["line"] <= obj.end_line or kind and obj.kind != kind:
                continue
            self.claimed.add(obj.id)
            record["object_ids"].append(obj.id)
            if obj.logical_key and obj.logical_key not in record["logical_keys"]:
                record["logical_keys"].append(obj.logical_key)
            break

    def visit_Name(self, node):
        self.emit(node.id, self.node_span(node), "use" if isinstance(node.ctx, ast.Load) else "definition")
        if isinstance(node.ctx, ast.Del) and self.scope.kind == "class":
            self.scope.bound_names.discard(node.id)

    def assignment_target(self, node, *, bind=True):
        if isinstance(node, (ast.Attribute, ast.Subscript)):
            base = node
            while isinstance(base, (ast.Attribute, ast.Subscript)):
                if isinstance(base, ast.Subscript):
                    self.visit(base.slice)
                base = base.value
            if isinstance(base, ast.Name):
                # Mutating an outer object does not introduce a class member.
                self.emit(base.id, self.node_span(base), "definition", bind=False, read_owner=True)
            else:
                self.visit(base)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for child in node.elts:
                self.assignment_target(child, bind=bind)
        elif isinstance(node, ast.Starred):
            self.assignment_target(node.value, bind=bind)
        elif isinstance(node, ast.Name):
            self.emit(node.id, self.node_span(node), "definition", bind=bind)
        else:
            self.visit(node)

    def visit_Assign(self, node):
        # LOAD_NAME on the RHS precedes STORE_NAME in a class namespace.
        self.visit(node.value)
        for target in node.targets:
            self.assignment_target(target)

    def visit_AnnAssign(self, node):
        if node.value:
            self.visit(node.value)
        self.assignment_target(node.target, bind=node.value is not None)
        self.visit(node.annotation)

    def visit_AugAssign(self, node):
        if isinstance(node.target, ast.Name) and self.scope.kind == "class" and (
            self.owner(self.scope, node.target.id) is not self.owner(self.scope, node.target.id, definition=True)
        ):
            self.emit(node.target.id, self.node_span(node.target), "use")
        self.visit(node.value)
        self.assignment_target(node.target)

    def visit_For(self, node):
        self.visit(node.iter)
        self.assignment_target(node.target)
        for statement in (*node.body, *node.orelse):
            self.visit(statement)

    visit_AsyncFor = visit_For

    def visit_Global(self, node):
        for name in node.names:
            self.emit(name, self.named_span(node, name), "use")

    visit_Nonlocal = visit_Global

    def parameters(self, args):
        return [*args.posonlyargs, *args.args, *args.kwonlyargs, *([args.vararg] if args.vararg else []), *([args.kwarg] if args.kwarg else [])]

    def function_header(self, node):
        for expression in (*getattr(node, "decorator_list", []), *node.args.defaults, *node.args.kw_defaults):
            if expression is not None:
                self.visit(expression)
        for parameter in self.parameters(node.args):
            if parameter.annotation:
                self.visit(parameter.annotation)
        if getattr(node, "returns", None):
            self.visit(node.returns)

    def visit_FunctionDef(self, node):
        self.function_header(node)
        self.emit(node.name, self.named_span(node, node.name), "definition", kind="function")
        parent = self.scope
        syntactic = node.name if parent.syntactic_name == "<module>" else parent.syntactic_name + "." + node.name
        name = node.name if parent.name == "<module>" else parent.name + "." + node.name
        if self.scope_counts[syntactic] > 1:
            name += f"@{node.lineno}:{node.col_offset}"
        self.scope = self._scope(name, syntactic, "function", parent, node.body, node.args)
        for parameter in self.parameters(node.args):
            self.emit(parameter.arg, self.node_span(parameter, parameter.arg), "definition", kind="parameter")
        for statement in node.body:
            self.visit(statement)
        self.scope = parent

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        for expression in (*node.decorator_list, *node.bases, *(item.value for item in node.keywords)):
            self.visit(expression)
        self.emit(node.name, self.named_span(node, node.name), "definition", kind="class")
        parent = self.scope
        syntactic = node.name if parent.syntactic_name == "<module>" else parent.syntactic_name + "." + node.name
        name = node.name if parent.name == "<module>" else parent.name + "." + node.name
        if self.scope_counts[syntactic] > 1:
            name += f"@{node.lineno}:{node.col_offset}"
        self.scope = self._scope(name, syntactic, "class", parent, node.body)
        for statement in node.body:
            self.visit(statement)
        self.scope = parent

    def visit_Lambda(self, node):
        self.function_header(node)
        parent = self.scope
        name = f"{parent.name}.<lambda>@{node.lineno}:{node.col_offset}"
        self.scope = self._scope(name, name, "lambda", parent, [node.body], node.args)
        for parameter in self.parameters(node.args):
            self.emit(parameter.arg, self.node_span(parameter, parameter.arg), "definition")
        self.visit(node.body)
        self.scope = parent

    def visit_ListComp(self, node):
        # Only the first iterable is evaluated outside the comprehension.
        self.visit(node.generators[0].iter)
        parent = self.scope
        name = f"{parent.name}.<{type(node).__name__.lower()}>@{node.lineno}:{node.col_offset}"
        targets = _Bindings()
        for generator in node.generators:
            targets.visit(generator.target)
        self.scope = _Scope(name, name, "comprehension", parent, targets.names)
        for index, generator in enumerate(node.generators):
            if index:
                self.visit(generator.iter)
            self.visit(generator.target)
            for condition in generator.ifs:
                self.visit(condition)
        for expression in ((node.key, node.value) if isinstance(node, ast.DictComp) else (node.elt,)):
            self.visit(expression)
        self.scope = parent

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp

    def visit_NamedExpr(self, node):
        owner = self.scope
        while owner.kind == "comprehension":
            owner = owner.parent
        self.visit(node.value)
        self.emit(node.target.id, self.node_span(node.target), "definition", scope=owner)

    def visit_Import(self, node):
        for alias in node.names:
            name = alias.asname or alias.name.split(".")[0]
            self.emit(name, self.named_span(alias, name, last=bool(alias.asname)), "definition", kind="import")

    visit_ImportFrom = visit_Import

    def visit_ExceptHandler(self, node):
        if node.type:
            self.visit(node.type)
        if node.name:
            # Handler AST spans include its body; the binding token is in the header.
            tokens = [token for token in self.tokens[node.lineno] if token.string == node.name]
            if tokens:
                self.emit(node.name, self.token_span(tokens[-1]), "definition")
        for statement in node.body:
            self.visit(statement)

    def visit_MatchAs(self, node):
        if node.pattern:
            self.visit(node.pattern)
        if node.name:
            self.emit(node.name, self.named_span(node, node.name, last=True), "definition")

    def visit_MatchStar(self, node):
        if node.name:
            self.emit(node.name, self.named_span(node, node.name), "definition")

    def visit_MatchMapping(self, node):
        self.generic_visit(node)
        if node.rest:
            self.emit(node.rest, self.named_span(node, node.rest, last=True), "definition")


def source_occurrences(analysis: AnalysisDocument, source_text: str) -> list[dict]:
    """Return display spans and original object IDs for each lexical binding.

    Callers must supply the archived text for this analysis, never fresh source
    from an unverified path. Invalid/redacted syntax yields no inferred spans.
    Columns are zero-based UTF-16 offsets, directly usable by the source view.
    """
    try:
        tree = ast.parse(source_text, filename=analysis.path)
        projection = _Occurrences(analysis, source_text, tree)
        projection.visit(tree)
    except (SyntaxError, tokenize.TokenError):
        return []
    records = []
    for record in projection.records.values():
        if not record["object_ids"] and not any(span["role"] == "definition" for span in record["occurrences"]):
            continue
        record["occurrences"].sort(key=lambda span: (span["line"], span["column"], span["end_line"], span["end_column"], span["role"]))
        records.append(record)
    return records
