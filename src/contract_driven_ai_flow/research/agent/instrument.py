"""Selected-file AST instrumentation with explicit limitations and original lines."""
from __future__ import annotations

import ast
import hashlib
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from types import CodeType

from .budget import CapturePolicy


@dataclass(frozen=True)
class InstrumentPolicy:
    allowed_files: tuple[str, ...] = ()
    watched_names: tuple[str, ...] = ()
    watched_lines: tuple[int, ...] = ()
    capture_policy: CapturePolicy = field(default_factory=CapturePolicy)
    mode: str = "auto"

    def __post_init__(self):
        if self.mode not in ("auto", "explicit"):
            raise ValueError("Instrumentation mode must be auto or explicit")
        if any(type(n) is not int or n < 1 for n in self.watched_lines):
            raise ValueError("Watched source lines must be positive integers")


@dataclass
class CoverageReport:
    entries: list[dict] = field(default_factory=list)

    def add(self, kind, status, line=0, message=""):
        self.entries.append({"kind": kind, "status": status, "line": line, "message": message})


@dataclass
class InstrumentedCode:
    code: CodeType
    runtime_name: str
    references: list[dict]
    source_map: dict[int, int]
    coverage: CoverageReport
    filename: str

    def execute(self, session, namespace=None):
        from .runner import ObservationRuntime
        environment = {"__name__": "__main__", "__file__": self.filename} if namespace is None else namespace
        if self.references:
            environment[self.runtime_name] = ObservationRuntime(session, self.references)
        session.emit("coverage.report", {"entries": self.coverage.entries}, critical=True)
        try:
            exec(self.code, environment)
        finally:
            runtime = environment.get(self.runtime_name)
            if runtime is not None:
                runtime.controls.flush(final=True)
        return environment


def root_name(target):
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for item in target.elts for name in root_name(item)]
    if isinstance(target, ast.Starred):
        return root_name(target.value)
    if isinstance(target, (ast.Attribute, ast.Subscript)):
        return root_name(target.value)
    return []


class Dependencies(ast.NodeVisitor):
    def __init__(self):
        self.names = []

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load) and node.id not in self.names:
            self.names.append(node.id)

    def visit_Call(self, node):
        # Callee/module names are not data inputs. A receiver X.mean(), however,
        # uses X; no attributes are evaluated by this source inspection.
        if isinstance(node.func, ast.Attribute):
            self.visit(node.func.value)
        for arg in node.args:
            self.visit(arg)
        for keyword in node.keywords:
            self.visit(keyword.value)

    def visit_Lambda(self, node):
        # A lambda definition has not executed its body.
        return


class Transformer(ast.NodeTransformer):
    def __init__(self, source, filename, digest, runtime_name, policy, coverage):
        self.source, self.filename, self.digest = source, filename, digest
        self.runtime_name, self.policy, self.coverage = runtime_name, policy, coverage
        self.references = []
        self.qualname = []
        self.in_class = False

    def helper(self, name, *arguments):
        return ast.Call(func=ast.Attribute(value=ast.Name(id=self.runtime_name, ctx=ast.Load()), attr=name, ctx=ast.Load()), args=list(arguments), keywords=[])

    def source_ref(self, node):
        return {"path": self.filename, "qualname": ".".join(self.qualname), "line": node.lineno,
                "end_line": getattr(node, "end_lineno", node.lineno), "digest": self.digest,
                "column": getattr(node, 'col_offset', 0), "end_column": getattr(node, 'end_col_offset', 0),
                "code": (ast.get_source_segment(self.source, node) or "")[:16384]}

    def selected(self, node, outputs):
        return bool(outputs) and not self.in_class and (not self.policy.watched_lines or node.lineno in self.policy.watched_lines) and (not self.policy.watched_names or any(name in self.policy.watched_names for name in outputs))

    def wrap(self, node, outputs, inputs, kind="assignment"):
        if not self.selected(node, outputs):
            return node
        outputs = list(dict.fromkeys(name for name in outputs if not self.policy.watched_names or name in self.policy.watched_names))
        identifier = len(self.references)
        ref = self.source_ref(node)
        self.references.append({"source": ref, "kind": kind, "outputs": outputs})
        self.coverage.add(kind, "supported", node.lineno, "Binding observed; element dependency inferred from source")
        after = ast.Expr(value=self.helper("after", ast.Constant(identifier), ast.Tuple(elts=[ast.Constant(n) for n in outputs], ctx=ast.Load())))
        ast.copy_location(after, node)
        context = self.helper("step", ast.Constant(identifier), ast.Tuple(elts=[ast.Constant(n) for n in inputs], ctx=ast.Load()))
        wrapped = ast.With(items=[ast.withitem(context_expr=context)], body=[node, after], type_comment=None)
        return ast.copy_location(wrapped, node)

    @staticmethod
    def dependencies(expression):
        visitor = Dependencies()
        if expression is not None:
            visitor.visit(expression)
        return visitor.names

    @staticmethod
    def kind(expression):
        if isinstance(expression, ast.BinOp) and isinstance(expression.op, ast.MatMult):
            return "matmul"
        if isinstance(expression, ast.BinOp):
            return "binary"
        if isinstance(expression, ast.Subscript):
            return "slice"
        if isinstance(expression, ast.Attribute) and expression.attr == "T":
            return "transpose"
        if isinstance(expression, ast.Call) and isinstance(expression.func, ast.Attribute):
            if expression.func.attr in ("mean", "std", "var", "sum", "min", "max"):
                return "aggregate"
            if expression.func.attr == "reshape":
                return "reshape"
        return "assignment"

    def visit_Assign(self, node):
        outputs = [name for target in node.targets for name in root_name(target)]
        inputs = self.dependencies(node.value)
        mutation = any(isinstance(t, (ast.Subscript, ast.Attribute)) for t in node.targets)
        if mutation:
            inputs.extend(outputs)
        return self.wrap(node, outputs, list(dict.fromkeys(inputs)), "mutation" if mutation else self.kind(node.value))

    def visit_AnnAssign(self, node):
        if node.value is None:
            return node
        return self.wrap(node, root_name(node.target), self.dependencies(node.value), self.kind(node.value))

    def visit_AugAssign(self, node):
        outputs = root_name(node.target)
        return self.wrap(node, outputs, list(dict.fromkeys([*outputs, *self.dependencies(node.value)])), "inplace")

    def visit_Expr(self, node):
        call = node.value
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr in ("fill", "sort", "resize", "put", "itemset", "update"):
            outputs = root_name(call.func.value)
            return self.wrap(node, outputs, list(dict.fromkeys([*outputs, *self.dependencies(call)])), "mutation")
        return node

    def visit_FunctionDef(self, node):
        if any(isinstance(item, (ast.Yield, ast.YieldFrom)) for item in ast.walk(node)):
            self.coverage.add("generator", "unsupported", node.lineno, "Generator suspension is not automatically traced; use explicit watch")
            return node
        previous_class = self.in_class
        self.in_class = False
        self.qualname.append(node.name)
        qualname = ".".join(self.qualname)
        from .source import source_identity
        index = len(self.references)
        self.references.append({'source': self.source_ref(node), 'kind': 'function', 'outputs': [],
            'node_id': source_identity(self.filename, self.digest, node, 'block:function')})
        node = self.generic_visit(node)
        self.qualname.pop()
        self.in_class = previous_class
        # Pure-return/control-only functions still need invocation ownership.
        doc = node.body[:1] if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str) else []
        body = node.body[len(doc):]
        scope = ast.With(items=[ast.withitem(context_expr=self.helper("function_scope", ast.Constant(qualname), ast.Constant(index)))], body=body, type_comment=None)
        ast.copy_location(scope, body[0] if body else node)
        node.body = [*doc, scope]
        return node

    def control_ref(self, node, kind):
        from .source import source_identity
        from .privacy import clean_text
        index = len(self.references)
        source = self.source_ref(node)
        source['code'] = clean_text(ast.get_source_segment(self.source, getattr(node, 'test', None) or getattr(node, 'iter', node)) or '', 512)
        self.references.append({'source': source, 'kind': kind, 'outputs': [],
            'node_id': source_identity(self.filename, self.digest, node, 'block:' + ('condition' if kind == 'branch' else 'loop'))})
        self.coverage.add(kind, 'supported', node.lineno, 'Actual suite entry observed; predicate and iterator unchanged')
        return index

    def marker(self, node, name, index, *arguments):
        return ast.copy_location(ast.Expr(value=self.helper(name, ast.Constant(index), *arguments)), node)

    def visit_If(self, node):
        if self.in_class:
            return self.generic_visit(node)
        index = self.control_ref(node, 'branch')
        node = self.generic_visit(node)
        node.body.insert(0, self.marker(node, 'branch', index, ast.Constant(True)))
        node.orelse.insert(0, self.marker(node, 'branch', index, ast.Constant(False)))
        return node

    def control_loop(self, node):
        if self.in_class:
            return self.generic_visit(node)
        index = self.control_ref(node, 'loop')
        node = self.generic_visit(node)
        node.body.insert(0, self.marker(node, 'iteration_enter', index))
        node.orelse.insert(0, self.marker(node, 'natural_exit', index))
        wrapper = ast.With(items=[ast.withitem(context_expr=self.helper('loop_scope', ast.Constant(index)))],
            body=[node, self.marker(node, 'reached_after', index)], type_comment=None)
        return ast.copy_location(wrapper, node)

    visit_For = control_loop
    visit_While = control_loop

    def visit_AsyncFor(self, node):
        self.coverage.add('async-loop', 'unsupported', node.lineno, 'Async lifecycle adapter required')
        return node

    def visit_AsyncFunctionDef(self, node):
        self.coverage.add("async-function", "unsupported", node.lineno, "Use explicit SDK for asynchronous scopes")
        return node

    def visit_ClassDef(self, node):
        previous = self.in_class
        self.in_class = True
        self.qualname.append(node.name)
        node = self.generic_visit(node)
        self.qualname.pop()
        self.in_class = previous
        self.coverage.add("class-body", "partial", node.lineno, "Method scopes observed; metaclass namespace writes not instrumented")
        return node


def instrument(source: str, filename: str, policy: InstrumentPolicy | None = None, *, source_digest=None) -> InstrumentedCode:
    policy = policy or InstrumentPolicy()
    tree = ast.parse(source, filename=filename)
    coverage = CoverageReport()
    runtime_name = "_cdaf_observer_" + uuid.uuid4().hex
    digest = source_digest or hashlib.sha256(source.encode("utf-8")).hexdigest()
    allowed = not policy.allowed_files or str(Path(filename).resolve()) in {str(Path(p).resolve()) for p in policy.allowed_files}
    enabled = allowed and policy.mode == "auto"
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and (isinstance(node.func, ast.Name) and node.func.id in ("globals", "locals", "vars", "dir") or isinstance(node.func, ast.Attribute) and node.func.attr in ("_getframe", "currentframe")):
            enabled = False
            coverage.add("reflection", "unsupported", node.lineno, "Automatic hooks would change namespace/frame introspection; execute unchanged and use explicit SDK")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("exec", "eval", "compile"):
            coverage.add("dynamic-code", "unsupported", node.lineno, "Dynamically generated code is not instrumented")
        if isinstance(node, ast.NamedExpr):
            coverage.add("expression-binding", "partial", node.lineno, "Assignment expression retains evaluation order but is not independently observed")
        if isinstance(node, ast.Nonlocal):
            coverage.add("closure-binding", "partial", node.lineno, "Active outer scope is resolved; detached closure ownership is reported per invocation")
    coverage.add("hidden-mutation", "partial", message="Only visible selected assignments and common mutation calls are observed; opaque/native calls and subprocesses need explicit SDK")
    references = []
    if enabled:
        transformer = Transformer(source, filename, digest, runtime_name, policy, coverage)
        tree = transformer.visit(tree)
        references = transformer.references
        ast.fix_missing_locations(tree)
    else:
        coverage.add("file", "unsupported", message="File outside allowlist, explicit-only capture or reflection requires unchanged execution")
    return InstrumentedCode(compile(tree, filename, "exec", dont_inherit=True), runtime_name, references,
                            {i: i for i in range(1, len(source.splitlines()) + 1)}, coverage, filename)
