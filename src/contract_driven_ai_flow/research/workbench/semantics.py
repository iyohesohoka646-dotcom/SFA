"""Inert, lexical single-file computation graph and extensible block projections.

Edges express possible static relationships. They are never runtime evidence or
authority to read source. SourceObject relations remain the separate read graph.
"""
from __future__ import annotations

import ast
import hashlib
from collections import defaultdict
from typing import Protocol

from ..agent.privacy import clean_text
from ..agent.source import source_identity as identity
from ..models import SourceRef
from .semantic_models import GraphBlock, GraphCoverage, GraphEdge, GraphNode, GraphPort, SemanticGraph


def lexical_bindings(function: ast.AST) -> set[str]:
    """Names declared local by Python, excluding nested lexical scopes."""
    local, external = set(), set()

    def visit(node):
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            external.update(node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            local.add(node.name)
        elif isinstance(node, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            # Comprehensions own their iteration bindings.
            return
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            local.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            local.update(alias.asname or alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ExceptHandler):
            if node.name:
                local.add(node.name)
            for child in node.body:
                visit(child)
        else:
            for child in ast.iter_child_nodes(node):
                visit(child)

    for statement in getattr(function, 'body', []):
        visit(statement)
    args = getattr(function, 'args', None)
    if args:
        local.update(arg.arg for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs))
        local.update(arg.arg for arg in (args.vararg, args.kwarg) if arg)
    return local - external


def read_names(expression: ast.AST | None) -> list[str]:
    return list(dict.fromkeys(part.id for part in ast.walk(expression) if isinstance(part, ast.Name) and isinstance(part.ctx, ast.Load))) if expression else []


def write_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for item in target.elts for name in write_names(item)]
    if isinstance(target, ast.Starred):
        return write_names(target.value)
    if isinstance(target, (ast.Attribute, ast.Subscript)):
        return write_names(target.value)
    return []


class GraphBuilder:
    def __init__(self, source, path, digest, objects):
        self.text, self.path, self.digest = source, path, digest
        self.objects = objects
        self.graph = SemanticGraph(source_digest=digest)
        self.node_index = {}
        self.block_index = {}
        self.object_index = {(obj.scope, obj.name, obj.line, obj.column): obj for obj in objects}
        self.functions = {}
        self.pending_calls = []
        self.versions = defaultdict(int)
        self.edge_keys = set()
        self.coverage_keys = set()

    def source(self, node, scope):
        return SourceRef(path=self.path, qualname='' if scope == '<module>' else scope,
            line=getattr(node, 'lineno', 1), end_line=getattr(node, 'end_lineno', 1),
            column=getattr(node, 'col_offset', 0), end_column=getattr(node, 'end_col_offset', 0),
            digest=self.digest, code=clean_text(ast.get_source_segment(self.text, node) or '', 16384))

    def coverage(self, code, message, node, scope, runtime='partial'):
        key = (code, getattr(node, 'lineno', 0), getattr(node, 'col_offset', 0))
        if key not in self.coverage_keys:
            self.coverage_keys.add(key)
            self.graph.coverage.append(GraphCoverage(code=code, message=message, source=self.source(node, scope), runtime=runtime))

    def block(self, node, kind, label, parent, scope, obj=None):
        key = identity(self.path, self.digest, node, 'block:' + kind)
        block = GraphBlock(id=key, logical_key=f'{self.path}::{scope}::{kind}@{getattr(node, "lineno", 1)}:{getattr(node, "col_offset", 0)}',
            kind=kind, label=clean_text(label, 256), parent_id=parent, source=self.source(node, scope), source_object_id=obj.id if obj else None)
        self.graph.blocks.append(block)
        self.block_index[key] = block
        if parent:
            self.block_index[parent].members.append(key)
            self.edge(parent, key, 'contains')
        if obj:
            obj.block_id = key
        return key

    def node(self, node, kind, label, block, scope, suffix='', obj=None):
        key = identity(self.path, self.digest, node, f'node:{kind}:{suffix}')
        if key in self.node_index:
            return key
        item = GraphNode(id=key, kind=kind, label=clean_text(label, 512), block_id=block,
            source=self.source(node, scope), source_object_id=obj.id if obj else None,
            logical_key=obj.logical_key if obj else '')
        if obj:
            obj.block_id = block
            self.versions[obj.logical_key] += 1
            item.version = self.versions[obj.logical_key]
        self.graph.nodes.append(item)
        self.node_index[key] = item
        self.block_index[block].members.append(key)
        self.edge(block, key, 'contains')
        return key

    def port(self, node_id, name, direction):
        node = self.node_index.get(node_id)
        if node is None:
            return None
        key = f'{node_id}:{direction}:{name}'
        if not any(port.id == key for port in node.ports):
            node.ports.append(GraphPort(id=key, name=name, direction=direction))
        return key

    def edge(self, source, target, kind, label='', branch=None):
        signature = (source, target, kind, label, branch)
        if signature in self.edge_keys:
            return
        self.edge_keys.add(signature)
        key = hashlib.sha256(repr(signature).encode()).hexdigest()[:24]
        data_port = kind in ('data', 'argument', 'return', 'merge', 'backedge') and bool(label)
        self.graph.edges.append(GraphEdge(id=key, source=source, target=target, kind=kind, label=label,
            source_port=self.port(source, label, 'output') if data_port else None,
            target_port=self.port(target, label, 'input') if data_port else None, branch=branch, original_ids=[key]))

    def object(self, node, name, scope):
        line = min([getattr(node, 'lineno', 0), *[decorator.lineno for decorator in getattr(node, 'decorator_list', [])]])
        return self.object_index.get((scope, name, line, getattr(node, 'col_offset', 0)))

    def read(self, expression, target, env, block, scope):
        for name in read_names(expression):
            dep = env.get(name)
            if dep is None:
                dep = self.node(expression, 'unknown', name, block, scope, suffix='read:' + name)
            self.edge(dep, target, 'data', name)

    def merge(self, statement, paths, block, scope, before, suffix='join'):
        result = dict(before)
        for name in set().union(*(path.keys() for path in paths)):
            values = {path.get(name) for path in paths}
            if len(values) == 1:
                result[name] = next(iter(values))
                continue
            merge = self.node(statement, 'merge', name, block, scope, suffix=f'{suffix}:{name}')
            for i, value in enumerate(values):
                if value is None:
                    value = self.node(statement, 'unknown', 'unbound ' + name, block, scope, suffix=f'{suffix}:unbound:{name}')
                self.edge(value, merge, 'merge', name)
            result[name] = merge
        return result

    def calls(self, expression, operation, env, scope):
        if expression is None:
            return
        for call in (part for part in ast.walk(expression) if isinstance(part, ast.Call)):
            self.pending_calls.append((call, operation, dict(env), scope))

    def statements(self, body, block, scope, env, incoming=()):
        """Reaching definitions are possible paths; no predicate is executed."""
        previous = list(incoming)
        for statement in body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                obj = self.object(statement, statement.name, scope)
                child_scope = statement.name if scope == '<module>' else scope + '.' + statement.name
                child = self.block(statement, 'class' if isinstance(statement, ast.ClassDef) else 'function', statement.name, block, child_scope, obj)
                for prior in previous:
                    self.edge(prior, child, 'control')
                env[statement.name] = child
                child_env = dict(env)
                if not isinstance(statement, ast.ClassDef):
                    for name in lexical_bindings(statement):
                        child_env.pop(name, None)
                    args = statement.args
                    parameters = [*args.posonlyargs, *args.args, *args.kwonlyargs, *([args.vararg] if args.vararg else []), *([args.kwarg] if args.kwarg else [])]
                    param_ids = {}
                    for arg in parameters:
                        param_id = self.node(arg, 'parameter', arg.arg, child, child_scope, suffix=arg.arg, obj=self.object(arg, arg.arg, child_scope))
                        child_env[arg.arg] = param_id
                        param_ids[arg.arg] = param_id
                    self.functions[(scope, statement.name)] = (child, param_ids, parameters)
                    # Unbound locals get explicit unknown boundaries, never a global input edge.
                    for name in lexical_bindings(statement) - param_ids.keys():
                        child_env[name] = self.node(statement, 'unknown', 'unbound ' + name, child, child_scope, suffix='local:' + name)
                    if isinstance(statement, ast.AsyncFunctionDef):
                        self.block_index[child].runtime_coverage = 'unsupported'
                        self.coverage('async_control', 'Async lifecycle is structural only; explicit SDK required', statement, child_scope, 'unsupported')
                    if any(isinstance(item, (ast.Yield, ast.YieldFrom)) for item in ast.walk(statement)):
                        self.block_index[child].runtime_coverage = 'unsupported'
                        self.coverage('generator_control', 'Generator suspension is structural only', statement, child_scope, 'unsupported')
                self.statements(statement.body, child, child_scope, child_env)
                previous = [child]
                continue
            if isinstance(statement, ast.If):
                plate = self.block(statement, 'condition', 'if ' + ast.unparse(statement.test), block, scope)
                test = self.node(statement.test, 'condition', ast.unparse(statement.test), plate, scope)
                self.read(statement.test, test, env, plate, scope)
                self.calls(statement.test, test, env, scope)
                for prior in previous:
                    self.edge(prior, test, 'control')
                paths, ends = [], []
                for branch, suite in (('true', statement.body), ('false', statement.orelse)):
                    entry = self.node(statement, 'entry', branch, plate, scope, suffix=branch)
                    self.edge(test, entry, 'control', branch, branch)
                    path = dict(env)
                    last = self.statements(suite, plate, scope, path, [entry])
                    paths.append(path)
                    ends.extend(last)
                env.update(self.merge(statement, paths, plate, scope, env))
                exit_id = self.node(statement, 'exit', 'merge paths', plate, scope)
                for last in ends:
                    self.edge(last, exit_id, 'control')
                previous = [exit_id]
                continue
            if isinstance(statement, (ast.For, ast.While, ast.AsyncFor)):
                expression = statement.test if isinstance(statement, ast.While) else statement.iter
                label = ('while ' + ast.unparse(expression)) if isinstance(statement, ast.While) else ('for ' + ast.unparse(statement.target) + ' in ' + ast.unparse(expression))
                plate = self.block(statement, 'loop', label, block, scope)
                header = self.node(statement, 'loop_header', label, plate, scope)
                self.read(expression, header, env, plate, scope)
                self.calls(expression, header, env, scope)
                for prior in previous:
                    self.edge(prior, header, 'control')
                body_env = dict(env)
                carried = {}
                synthetic = ast.FunctionDef(name='_', args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]), body=statement.body, decorator_list=[])
                for name in lexical_bindings(synthetic):
                    if name in env:
                        merge = self.node(statement, 'merge', name, plate, scope, suffix='carried:' + name)
                        self.edge(env[name], merge, 'merge', name)
                        body_env[name] = merge
                        carried[name] = merge
                if isinstance(statement, (ast.For, ast.AsyncFor)):
                    for name in write_names(statement.target):
                        value = self.node(statement.target, 'data', name, plate, scope, suffix='iteration:' + name, obj=self.object(statement.target, name, scope))
                        self.edge(header, value, 'data', name)
                        body_env[name] = value
                entry = self.node(statement, 'entry', 'body', plate, scope, suffix='body')
                self.edge(header, entry, 'control', 'body', 'body')
                ends = self.statements(statement.body, plate, scope, body_env, [entry])
                for last in ends:
                    self.edge(last, header, 'backedge', 'next iteration')
                for name, merge in carried.items():
                    self.edge(body_env[name], merge, 'backedge', name)
                    if isinstance(statement, ast.While) and name in read_names(expression):
                        self.edge(merge, header, 'data', name)
                exit_id = self.node(statement, 'exit', 'loop exit', plate, scope)
                self.edge(header, exit_id, 'control', 'exit', 'exit')
                env.update(self.merge(statement, [env, body_env], plate, scope, env, 'loop-exit'))
                previous = self.statements(statement.orelse, plate, scope, env, [exit_id])
                if isinstance(statement, ast.AsyncFor):
                    self.block_index[plate].runtime_coverage = 'unsupported'
                    self.coverage('async_control', 'Async iteration is structural only', statement, scope, 'unsupported')
                continue
            if isinstance(statement, (ast.Try, ast.TryStar, ast.With, ast.AsyncWith)):
                plate = self.block(statement, 'try' if isinstance(statement, (ast.Try, ast.TryStar)) else 'with', type(statement).__name__.lower(), block, scope)
                if isinstance(statement, (ast.Try, ast.TryStar)):
                    before = dict(env)
                    normal = dict(env)
                    ends = self.statements(statement.body, plate, scope, normal, previous)
                    ends = self.statements(statement.orelse, plate, scope, normal, ends)
                    paths = [normal]
                    for handler in statement.handlers:
                        branch_env = dict(before)
                        marker = self.node(handler, 'entry', ast.unparse(handler.type) if handler.type else 'exception', plate, scope, suffix='except')
                        for prior in previous:
                            self.edge(prior, marker, 'control', 'exception', 'exception')
                        ends.extend(self.statements(handler.body, plate, scope, branch_env, [marker]))
                        paths.append(branch_env)
                    env.update(self.merge(statement, paths, plate, scope, before))
                    previous = self.statements(statement.finalbody, plate, scope, env, ends)
                    self.coverage('exception_flow', 'Exception edges conservatively describe possible handlers and finalization', statement, scope)
                else:
                    previous = self.statements(statement.body, plate, scope, env, previous)
                continue
            if isinstance(statement, (ast.Import, ast.ImportFrom)):
                for alias in statement.names:
                    name = alias.asname or alias.name.split('.')[0]
                    env[name] = self.node(statement, 'data', name, block, scope, suffix=name, obj=self.object(statement, name, scope))
                continue
            expression = getattr(statement, 'value', None)
            if isinstance(statement, ast.Return):
                operation = self.node(statement, 'return', 'return ' + (ast.unparse(expression) if expression else ''), block, scope)
                # Returns inside a control plate belong to the nearest function boundary.
                parent = block
                while self.block_index[parent].kind not in ('function', 'file'):
                    parent = self.block_index[parent].parent_id
                self.edge(operation, parent, 'return', 'result')
            else:
                kind = 'call' if isinstance(expression, ast.Call) else 'operation'
                operation = self.node(statement, kind, ast.unparse(statement), block, scope)
            for prior in previous:
                self.edge(prior, operation, 'control')
            self.read(expression, operation, env, block, scope)
            for name in read_names(expression):
                dep = env.get(name)
                if dep and self.node_index.get(dep) and self.node_index[dep].label == 'unbound ' + name:
                    self.coverage('unbound_local', f'{name} may be read before local assignment', statement, scope)
            self.calls(expression, operation, env, scope)
            writes = statement.targets if isinstance(statement, ast.Assign) else [statement.target] if isinstance(statement, (ast.AnnAssign, ast.AugAssign)) else []
            for target in writes:
                for name in write_names(target):
                    if isinstance(statement, ast.AugAssign) or isinstance(target, (ast.Attribute, ast.Subscript)):
                        if name in env:
                            self.edge(env[name], operation, 'data', name)
                    data = self.node(statement, 'data', name, block, scope, suffix=name, obj=self.object(statement, name, scope))
                    self.edge(operation, data, 'data', name)
                    env[name] = data
            if isinstance(statement, (ast.Match, ast.AsyncWith)):
                self.coverage('opaque_structure', 'This control structure requires a dedicated semantic provider', statement, scope, 'unsupported')
            previous = [operation]
        return previous

    def finish_calls(self):
        for call, operation, env, scope in self.pending_calls:
            if not isinstance(call.func, ast.Name):
                self.coverage('dynamic_call', 'Attribute/native target is unresolved; inputs remain explicit', call, scope)
                continue
            current = scope
            function = None
            while current:
                function = self.functions.get((current, call.func.id))
                if function:
                    break
                current = current.rsplit('.', 1)[0] if '.' in current else '<module>' if current != '<module>' else ''
            if not function:
                self.coverage('dynamic_call', f'Unresolved call: {call.func.id}', call, scope)
                continue
            child, params, args = function
            # A binding must point to this definition, otherwise the name was dynamically reassigned.
            if env.get(call.func.id) not in (None, child):
                self.coverage('dynamic_call', 'Callee binding is not the static function definition', call, scope)
                continue
            self.edge(operation, child, 'call', call.func.id)
            for argument, parameter in zip(call.args, args):
                if isinstance(argument, ast.Starred):
                    self.coverage('dynamic_arguments', 'Starred arguments require runtime binding evidence', call, scope)
                    continue
                for name in read_names(argument):
                    if name in env:
                        self.edge(env[name], params[parameter.arg], 'argument', parameter.arg)
                if not read_names(argument):
                    self.edge(operation, params[parameter.arg], 'argument', parameter.arg)
            for keyword in call.keywords:
                if keyword.arg in params:
                    for name in read_names(keyword.value):
                        if name in env:
                            self.edge(env[name], params[keyword.arg], 'argument', keyword.arg)
            for node in self.graph.nodes:
                if node.kind == 'return' and node.source and node.source.qualname == (self.block_index[child].source.qualname or ''):
                    self.edge(node.id, operation, 'return', 'result')


def build_graph(tree, text, path, digest, objects):
    builder = GraphBuilder(text, path, digest, objects)
    root = builder.block(tree, 'file', path.replace('\\', '/').rsplit('/', 1)[-1], None, '<module>')
    builder.block_index[root].source.end_line = max(1, len(text.splitlines()))
    builder.graph.roots = [root]
    builder.statements(tree.body, root, '<module>', {})
    builder.finish_calls()
    # Objects omitted from a specialized scope still have an honest file boundary.
    for obj in objects:
        if not obj.block_id:
            obj.block_id = root
    return SemanticGraph.model_validate(builder.graph.model_dump())


def project_graph(graph: SemanticGraph, *, collapsed: set[str] | None = None) -> SemanticGraph:
    """Aggregate crossing edges, retaining every original relationship reference.

    Internal relations of a collapsed plate become plate self-relations. A
    renderer may hide those loops but can inspect their original references.
    """
    collapsed = collapsed or set()
    parents = {block.id: block.parent_id for block in graph.blocks}
    parents.update({node.id: node.block_id for node in graph.nodes})

    def representative(key):
        current, ancestors = key, []
        while current is not None:
            if current in collapsed:
                ancestors.append(current)
            current = parents.get(current)
        return ancestors[-1] if ancestors else key

    blocks = [block.model_copy(update={'members': [key for key in block.members if representative(key) == key]}) for block in graph.blocks if representative(block.id) == block.id]
    nodes = [node for node in graph.nodes if representative(node.id) == node.id]
    grouped = {}
    for edge in graph.edges:
        if edge.kind == 'contains':
            continue
        source, target = representative(edge.source), representative(edge.target)
        signature = (source, target, edge.kind, edge.branch)
        if signature not in grouped:
            grouped[signature] = edge.model_copy(update={'source': source, 'target': target,
                'source_port': edge.source_port if source == edge.source else None,
                'target_port': edge.target_port if target == edge.target else None,
                'original_ids': list(edge.original_ids or [edge.id]), 'count': edge.count})
        else:
            grouped[signature].original_ids.extend(edge.original_ids or [edge.id])
            grouped[signature].count += edge.count
    return graph.model_copy(update={'nodes': nodes, 'blocks': blocks, 'edges': list(grouped.values())})


class BlockProvider(Protocol):
    def provide(self, key: str, label: str, graph: SemanticGraph, members: list[str]) -> GraphBlock: ...


class MemberBlockProvider:
    """Development adapter for overlapping user streams, not structural parents."""
    def provide(self, key, label, graph, members):
        known = {node.id for node in graph.nodes} | {block.id for block in graph.blocks} | {edge.id for edge in graph.edges}
        if any(member not in known for member in members):
            raise ValueError('Stream contains an unknown semantic member')
        return GraphBlock(id=key, logical_key=key, kind='stream', label=label, members=list(dict.fromkeys(members)))


class StructuralBlockProvider:
    """Contract fixture for a future folder/project importer; never parses files."""
    def __init__(self, kind='folder'):
        if kind not in ('folder', 'project'):
            raise ValueError('Structural provider supports folder or project blocks')
        self.kind = kind

    def provide(self, key, label, graph, members):
        known = {block.id for block in graph.blocks}
        if any(member not in known for member in members):
            raise ValueError('Structural members must reference existing blocks')
        return GraphBlock(id=key, logical_key=key, kind=self.kind, label=label,
                          members=list(dict.fromkeys(members)), runtime_coverage='unsupported')
