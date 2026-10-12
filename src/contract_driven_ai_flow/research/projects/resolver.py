"""Static, non-executing resolution of imports, calls and project graph slices.

Nothing here imports user modules; all facts come from an already-parsed AST or
from the persisted per-analysis fact cache. Unsupported patterns are reported as
unknown coverage instead of guessed edges.
"""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, field

from ..workbench.semantic_models import (
    GraphBlock,
    GraphCoverage,
    GraphEdge,
    GraphNode,
    SemanticGraph,
)
from ..models import SourceRef

_KIND = {
    "function": "operation",
    "class": "operation",
    "step": "operation",
    "assignment": "data",
    "parameter": "parameter",
}


def _id(prefix: str, *parts: str) -> str:
    raw = "\0".join([prefix, *parts])
    return f"{prefix}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


@dataclass
class FileFacts:
    file_id: str = ""
    relative_path: str = ""
    module: str = ""
    package: str = ""
    imports: list = field(default_factory=list)
    calls: list = field(default_factory=list)
    bound: dict = field(default_factory=dict)
    dynamic: list = field(default_factory=list)
    global_names: dict = field(default_factory=dict)
    nonlocal_names: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            "file_id": self.file_id,
            "relative_path": self.relative_path,
            "module": self.module,
            "package": self.package,
            "imports": self.imports,
            "calls": self.calls,
            "bound": self.bound,
            "dynamic": self.dynamic,
            "global_names": self.global_names,
            "nonlocal_names": self.nonlocal_names,
        }

    @classmethod
    def from_json(cls, data: dict) -> "FileFacts":
        return cls(
            file_id=data.get("file_id", ""),
            relative_path=data.get("relative_path", ""),
            module=data.get("module", ""),
            package=data.get("package", ""),
            imports=list(data.get("imports", [])),
            calls=list(data.get("calls", [])),
            bound=dict(data.get("bound", {})),
            dynamic=list(data.get("dynamic", [])),
            global_names=dict(data.get("global_names", {})),
            nonlocal_names=dict(data.get("nonlocal_names", {})),
        )


def package_of(module: str, is_init: bool) -> str:
    if not module:
        return ""
    if is_init:
        return module
    return module.rsplit(".", 1)[0] if "." in module else ""


def _resolve_relative(module: str, level: int, package: str) -> str:
    """Absolute (level 0) imports never gain the current package prefix."""
    if not level:
        return module
    parts = package.split(".") if package else []
    if level > 1:
        parts = parts[: max(0, len(parts) - (level - 1))]
    prefix = ".".join(parts)
    if module:
        return f"{prefix}.{module}" if prefix else module
    return prefix


def _target_names(node) -> list:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, (ast.Tuple, ast.List)):
        return [name for part in node.elts for name in _target_names(part)]
    return []


def _read_names(node) -> list:
    if node is None:
        return []
    names = []
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            if child.id not in names:
                names.append(child.id)
    return names


def _scope_of(node, parents) -> str:
    names = []
    current = parents.get(node)
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(current.name)
        current = parents.get(current)
    names.reverse()
    return ".".join(names) if names else "<module>"


def _receiver_names(call, parents) -> list:
    node = call
    parent = parents.get(node)
    while parent is not None and not isinstance(parent, ast.stmt):
        node = parent
        parent = parents.get(node)
    if isinstance(parent, ast.Assign):
        return [name for target in parent.targets for name in _target_names(target)]
    if isinstance(parent, (ast.AnnAssign, ast.AugAssign)):
        return _target_names(parent.target)
    return []


class _FactScanner(ast.NodeVisitor):
    """Collects imports and per-scope local bindings for shadowing checks."""

    def __init__(self, module: str, is_init: bool):
        self.module = module
        self.is_init = is_init
        self.package = package_of(module, is_init)
        self.imports: list = []
        self.bound: dict = {}
        self.global_names: dict = {}
        self.nonlocal_names: dict = {}
        self._scopes = ["<module>"]

    @property
    def scope(self) -> str:
        return self._scopes[-1]

    def _bind(self, name: str) -> None:
        self.bound.setdefault(self.scope, []).append(name)

    def visit_Global(self, node):
        self.global_names.setdefault(self.scope, []).extend(node.names)

    def visit_Nonlocal(self, node):
        self.nonlocal_names.setdefault(self.scope, []).extend(node.names)

    def visit_Import(self, node):
        for alias in node.names:
            local = alias.asname or alias.name.split(".")[0]
            self.imports.append(
                {"local": local, "module": alias.name, "name": None, "level": 0, "scope": self.scope}
            )

    def visit_ImportFrom(self, node):
        module = node.module or ""
        for alias in node.names:
            local = alias.asname or alias.name.split(".")[0]
            self.imports.append(
                {
                    "local": local,
                    "module": module,
                    "name": alias.name,
                    "level": node.level,
                    "scope": self.scope,
                }
            )

    def _function(self, node):
        name = getattr(node, "name", "<lambda>")
        self._bind(name)
        child = name if self.scope == "<module>" else f"{self.scope}.{name}"
        self._scopes.append(child)
        for arg in (
            *getattr(node.args, "posonlyargs", []),
            *node.args.args,
            *node.args.kwonlyargs,
        ):
            self._bind(arg.arg)
        for stmt in node.body:
            self.visit(stmt)
        self._scopes.pop()

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function

    def visit_ClassDef(self, node):
        self._bind(node.name)
        child = node.name if self.scope == "<module>" else f"{self.scope}.{node.name}"
        self._scopes.append(child)
        for stmt in node.body:
            self.visit(stmt)
        self._scopes.pop()

    def visit_Assign(self, node):
        for target in node.targets:
            for name in _target_names(target):
                self._bind(name)
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        for name in _target_names(node.target):
            self._bind(name)
        self.generic_visit(node)

    def visit_AugAssign(self, node):
        for name in _target_names(node.target):
            self._bind(name)
        self.generic_visit(node)

    def visit_For(self, node):
        for name in _target_names(node.target):
            self._bind(name)
        self.generic_visit(node)

    visit_AsyncFor = visit_For

    def visit_With(self, node):
        for item in node.items:
            if item.optional_vars is not None:
                for name in _target_names(item.optional_vars):
                    self._bind(name)
        self.generic_visit(node)

    visit_AsyncWith = visit_With

    def visit_comprehension(self, node):
        for name in _target_names(node.target):
            self._bind(name)
        self.generic_visit(node)


def scan(tree, *, module: str = "", is_init: bool = False) -> FileFacts:
    scanner = _FactScanner(module, is_init)
    for stmt in getattr(tree, "body", []):
        scanner.visit(stmt)
    parents: dict = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    calls: list = []
    dynamic: list = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        lineno = getattr(node, "lineno", 0)
        if isinstance(func, ast.Name):
            name, attr = func.id, None
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            name, attr = func.value.id, func.attr
        else:
            dynamic.append(f"Dynamic call target at line {lineno}")
            continue
        calls.append(
            {
                "scope": _scope_of(node, parents),
                "name": name,
                "attr": attr,
                "lineno": lineno,
                "args": [_read_names(arg) for arg in node.args],
                "keywords": {(kw.arg or "**"): _read_names(kw.value) for kw in node.keywords},
                "receiver": _receiver_names(node, parents),
            }
        )
    return FileFacts(
        module=module,
        package=scanner.package,
        imports=scanner.imports,
        calls=calls,
        bound=scanner.bound,
        dynamic=dynamic,
        global_names=scanner.global_names,
        nonlocal_names=scanner.nonlocal_names,
    )


@dataclass
class ProjectGraphInput:
    project_id: str
    project_name: str
    revision_id: str
    units: list
    analyses: dict
    facts: dict
    module_index: dict
    limit: int = 350
    scope_id: str | None = None
    view: str = "code"
    symbols: dict = field(default_factory=dict)
    relationships: list = field(default_factory=list)


def _scope_chain(scope: str) -> list:
    chain = []
    current = scope
    while current:
        chain.append(current)
        current = current.rsplit(".", 1)[0] if "." in current else "<module>" if current != "<module>" else ""
    return chain


class _Resolver:
    def __init__(self, data: ProjectGraphInput):
        self.data = data
        self.coverage: list = []

    def _shadowed(self, facts: FileFacts, scope: str, name: str) -> bool:
        chain = _scope_chain(scope)
        imports = {imp["local"] for imp in facts.imports if imp["scope"] in chain}
        if name not in imports:
            return False
        for probe in reversed(chain):
            if name in facts.bound.get(probe, []):
                return True
        return False

    def _symbol(self, module: str, name: str, depth: int = 0):
        if depth > 6 or not module:
            return None
        fid = self.data.module_index.get(module)
        if fid is None:
            return None
        analysis = self.data.analyses.get(fid)
        if analysis:
            for obj in analysis.objects:
                if (
                    obj.name == name
                    and obj.kind in ("function", "class")
                    and getattr(obj, "scope", "<module>") == "<module>"
                ):
                    return (fid, name)
        for symbol in self.data.symbols.get(fid, []):
            if (
                symbol.get("name") == name
                and symbol.get("kind") in ("function", "class")
                and symbol.get("scope", "<module>") == "<module>"
            ):
                return (fid, name)
        facts = self.data.facts.get(fid)
        if facts is None:
            return None
        for imp in facts.imports:
            if imp["local"] != name:
                continue
            base = _resolve_relative(imp["module"], imp["level"], facts.package)
            target = imp["name"] or name
            if imp["name"] is None:
                sub = f"{base}.{target}" if base else target
                if sub in self.data.module_index:
                    return (self.data.module_index[sub], None)
                return self._symbol(base, target, depth + 1)
            sub = f"{base}.{target}"
            if sub in self.data.module_index:
                return (self.data.module_index[sub], None)
            found = self._symbol(base, target, depth + 1)
            if found:
                return found
        return None

    def resolve_call(self, facts: FileFacts, call: dict):
        scope = call["scope"]
        name = call["name"]
        attr = call.get("attr")
        if self._shadowed(facts, scope, name):
            self.coverage.append(("shadowed_call", f"Local binding shadows imported name: {name}", call))
            return None
        imported = [imp for imp in facts.imports if imp["local"] == name and imp["scope"] in _scope_chain(scope)]
        if not imported:
            return None
        imp = imported[-1]
        base = _resolve_relative(imp["module"], imp["level"], facts.package)
        if attr is not None and imp["name"] is None:
            return self._symbol(base, attr)
        target = imp["name"] or name
        if attr is not None:
            return self._symbol(f"{base}.{target}" if base else target, attr)
        return self._symbol(base, target)


def _folders_for(rel: str) -> list:
    parts = rel.split("/")[:-1]
    return ["/".join(parts[: i + 1]) for i in range(len(parts))]


def _prefix_ref(ref, *, project_id: str, file_id: str, revision_id: str, path: str | None = None):
    if ref is None:
        base = SourceRef()
    else:
        base = ref
    update = {
        "project_id": project_id,
        "file_id": file_id,
        "project_revision_id": revision_id,
    }
    if path is not None:
        update["path"] = path
    return base.model_copy(update=update)


def build_project_graph(data: ProjectGraphInput) -> tuple[SemanticGraph, int]:
    unit_ids = {u.id for u in data.units}
    scope_unit = None
    if data.scope_id in unit_ids:
        scope_unit = data.scope_id
    elif data.scope_id and data.scope_id.startswith("file:"):
        scope_unit = next(
            (uid for uid in unit_ids if _id("file", uid) == data.scope_id), None
        )
    units = (
        [u for u in data.units if u.id == scope_unit] if scope_unit else list(data.units)
    )
    blocks: list = []
    nodes: list = []
    edges: list = []
    coverage: list = []
    omitted = 0

    project_block_id = _id("project", data.project_id)
    blocks.append(
        GraphBlock(
            id=project_block_id,
            logical_key=f"{data.project_id}::project::{data.project_name}",
            kind="project",
            label=data.project_name or "project",
            members=[],
            source=SourceRef(
                project_id=data.project_id, project_revision_id=data.revision_id
            ),
            runtime_coverage="supported",
        )
    )
    folder_ids: dict = {}
    obj_node: dict = {}
    var_nodes: dict = {}
    name_node: dict = {}
    param_entries: dict = {}
    return_nodes: dict = {}
    unit_nodes: dict = {}

    for unit in units:
        rel = unit.relative_path
        parent = project_block_id
        for folder in _folders_for(rel):
            fid = _id("folder", data.project_id, folder)
            if fid not in folder_ids:
                blocks.append(
                    GraphBlock(
                        id=fid,
                        logical_key=f"{data.project_id}::folder::{folder}",
                        kind="folder",
                        label=folder,
                        parent_id=parent,
                        members=[],
                        source=SourceRef(
                            path=folder,
                            project_id=data.project_id,
                            project_revision_id=data.revision_id,
                        ),
                        runtime_coverage="supported",
                    )
                )
                folder_ids[fid] = folder
                edges.append(GraphEdge(id=_id("e", parent, fid, "contains"), source=parent, target=fid, kind="contains", provenance="inferred"))
            parent = fid
        file_block_id = _id("file", unit.id)
        blocks.append(
            GraphBlock(
                id=file_block_id,
                logical_key=f"{data.project_id}::{unit.id}::file::{rel}",
                kind="file",
                label=rel,
                parent_id=parent,
                members=[],
                source=SourceRef(
                    path=rel,
                    digest=unit.digest,
                    project_id=data.project_id,
                    file_id=unit.id,
                    project_revision_id=data.revision_id,
                ),
                runtime_coverage="supported",
            )
        )
        edges.append(GraphEdge(id=_id("e", parent, file_block_id, "contains"), source=parent, target=file_block_id, kind="contains", provenance="inferred"))

        analysis = data.analyses.get(unit.id)
        if analysis is None:
            continue
        source_graph = analysis.graph
        idmap: dict = {}
        for block in source_graph.blocks:
            if block.kind == "file":
                idmap[block.id] = file_block_id
                continue
            new_id = _id("block", unit.id, block.id)
            idmap[block.id] = new_id
            new_parent = file_block_id
            if block.parent_id is not None:
                new_parent = idmap.get(block.parent_id, file_block_id)
            blocks.append(
                block.model_copy(
                    update={
                        "id": new_id,
                        "parent_id": new_parent,
                        "members": [],
                        "source": _prefix_ref(
                            block.source,
                            project_id=data.project_id,
                            file_id=unit.id,
                            revision_id=data.revision_id,
                            path=rel,
                        ),
                    }
                )
            )
            if block.source_object_id:
                obj_node[(unit.id, block.source_object_id)] = new_id
        for node in source_graph.nodes:
            new_id = _id("node", unit.id, node.id)
            idmap[node.id] = new_id
            new_block = idmap.get(node.block_id, file_block_id)
            nodes.append(
                node.model_copy(
                    update={
                        "id": new_id,
                        "block_id": new_block,
                        "ports": [],
                        "source": _prefix_ref(
                            node.source,
                            project_id=data.project_id,
                            file_id=unit.id,
                            revision_id=data.revision_id,
                            path=rel,
                        ),
                    }
                )
            )
            if node.source_object_id:
                obj_node[(unit.id, node.source_object_id)] = new_id
        for block in source_graph.blocks:
            if block.kind == "file":
                continue
            target = next((b for b in blocks if b.id == idmap.get(block.id)), None)
            if target is not None:
                target.members = [idmap.get(member, member) for member in block.members]
        file_block = next((b for b in blocks if b.id == file_block_id), None)
        file_root = next((b for b in source_graph.blocks if b.kind == "file"), None)
        if file_block is not None and file_root is not None:
            file_block.members = [idmap.get(member, member) for member in file_root.members]
        for edge in source_graph.edges:
            edges.append(
                edge.model_copy(
                    update={
                        "id": _id("edge", unit.id, edge.id),
                        "source": idmap.get(edge.source, edge.source),
                        "target": idmap.get(edge.target, edge.target),
                    }
                )
            )
        unit_nodes[unit.id] = [idmap[n.id] for n in source_graph.nodes]
        for obj in analysis.objects:
            nid = obj_node.get((unit.id, obj.id))
            if nid is None:
                continue
            if obj.kind in ("function", "class"):
                name_node[(unit.id, obj.name)] = (nid, obj.line, obj.end_line, obj.id)
            if obj.kind in ("assignment", "parameter", "function", "class"):
                var_nodes.setdefault((unit.id, obj.name), []).append((obj.line, nid, obj.scope))
            if obj.kind == "parameter":
                enclosing = min(
                    (
                        o
                        for o in analysis.objects
                        if o.kind == "function" and o.line <= obj.line <= o.end_line
                    ),
                    key=lambda o: o.end_line - o.line,
                    default=None,
                )
                if enclosing is not None:
                    param_entries.setdefault(unit.id, []).append(
                        (enclosing.id, obj.name, obj.line, obj.column, obj.end_line, nid)
                    )
        func_block_obj = {
            obj_node.get((unit.id, o.id)): o.id
            for o in analysis.objects
            if o.kind == "function"
        }
        for node in nodes:
            if node.kind == "return" and node.block_id in func_block_obj:
                return_nodes.setdefault((unit.id, func_block_obj[node.block_id]), []).append(node.id)

    def nearest(unit_id: str, name: str, lineno: int, scope: str = "<module>"):
        """Nearest prior binding in the exact lexical scope chain; never a sibling scope."""
        candidates = var_nodes.get((unit_id, name), [])
        if not candidates:
            return None
        by_scope: dict = {}
        for line, nid, bound_scope in candidates:
            by_scope.setdefault(bound_scope or "<module>", []).append((line, nid))
        facts = data.facts.get(unit_id)
        chain = _scope_chain(scope or "<module>")
        if facts is not None and name in facts.global_names.get(scope or "<module>", []):
            chain = ["<module>"]
        elif facts is not None and name in facts.nonlocal_names.get(scope or "<module>", []):
            chain = [c for c in chain if c != (scope or "<module>")]
        for probe in chain:
            entries = by_scope.get(probe)
            if not entries:
                continue
            eligible = [(line, nid) for line, nid in entries if line <= lineno]
            if eligible:
                return max(eligible)[1]
            # Name is local to this function scope but unbound before the reference.
            return None
        return None

    resolver = _Resolver(data)
    if not data.analyses:
        # Compact overview: no per-file analysis loaded; summarize cross-file
        # calls onto the retained file plates.
        for unit in units:
            facts = data.facts.get(unit.id)
            if facts is None:
                continue
            source_block = _id("file", unit.id)
            for call in facts.calls:
                resolved = resolver.resolve_call(facts, call)
                if resolved is None:
                    continue
                target_file, target_name = resolved
                if not target_file or target_file == unit.id or not target_name:
                    continue
                target_block = _id("file", target_file)
                edges.append(
                    GraphEdge(
                        id=_id("e", source_block, target_block, "call", target_name),
                        source=source_block,
                        target=target_block,
                        kind="call",
                        label=target_name,
                        provenance="inferred",
                    )
                )
    for unit in units:
        if not data.analyses:
            break
        facts = data.facts.get(unit.id)
        if facts is None:
            continue
        file_block_id = _id("file", unit.id)
        for call in facts.calls:
            resolved = resolver.resolve_call(facts, call)
            if resolved is None:
                continue
            target_file, target_name = resolved
            if target_file is None or target_file == unit.id:
                continue
            entry = name_node.get((target_file, target_name))
            if entry is None:
                resolver.coverage.append(("unknown_target", f"Unresolved static target: {target_name}", call))
                continue
            target_node, start, end, object_id = entry
            caller_node = file_block_id
            spans = [
                (o.line, o.end_line, o.id)
                for o in (data.analyses.get(unit.id).objects if data.analyses.get(unit.id) else [])
                if o.kind == "function"
            ]
            enclosing = sorted(
                (span_end - span_start, oid)
                for span_start, span_end, oid in spans
                if span_start <= call["lineno"] <= span_end
            )
            if enclosing:
                caller_node = obj_node.get((unit.id, enclosing[0][1]), file_block_id)
            edges.append(
                GraphEdge(
                    id=_id("e", caller_node, target_node, "call", target_name),
                    source=caller_node,
                    target=target_node,
                    kind="call",
                    label=target_name,
                    provenance="inferred",
                )
            )
            params = [
                p
                for p in param_entries.get(target_file, [])
                if p[0] == object_id
            ]
            params.sort(key=lambda p: (p[2], p[3]))
            positional = list(params)
            used = set()
            for index, arg_names in enumerate(call.get("args", [])):
                if index >= len(positional):
                    break
                _, pname, _, _, _, pnode = positional[index]
                used.add(pname)
                for aname in arg_names:
                    source_node = nearest(unit.id, aname, call["lineno"], call["scope"])
                    if source_node is None:
                        resolver.coverage.append(
                            ("unmapped_argument", f"Argument {aname} has no local node", call)
                        )
                        continue
                    edges.append(
                        GraphEdge(
                            id=_id("e", source_node, pnode, "argument", pname),
                            source=source_node,
                            target=pnode,
                            kind="argument",
                            label=pname,
                            provenance="inferred",
                        )
                    )
            for keyword, names in (call.get("keywords") or {}).items():
                match = next((p for p in params if p[1] == keyword), None)
                if match is None:
                    continue
                used.add(keyword)
                for aname in names:
                    source_node = nearest(unit.id, aname, call["lineno"], call["scope"])
                    if source_node is None:
                        continue
                    edges.append(
                        GraphEdge(
                            id=_id("e", source_node, match[5], "argument", keyword),
                            source=source_node,
                            target=match[5],
                            kind="argument",
                            label=keyword,
                            provenance="inferred",
                        )
                    )
            for rname in call.get("receiver", []):
                receiver = nearest(unit.id, rname, call["lineno"], call["scope"])
                if receiver is None:
                    resolver.coverage.append(
                        ("unmapped_receiver", f"Receiver {rname} has no local node", call)
                    )
                    continue
                for return_id in return_nodes.get((target_file, object_id), []):
                    edges.append(
                        GraphEdge(
                            id=_id("e", return_id, receiver, "return", rname),
                            source=return_id,
                            target=receiver,
                            kind="return",
                            label=rname,
                            provenance="inferred",
                        )
                    )

    for unit in units:
        facts = data.facts.get(unit.id)
        if facts is None:
            continue
        for message in facts.dynamic:
            resolver.coverage.append(("dynamic_call", message, {"lineno": 0}))
    for code, message, call in resolver.coverage:
        coverage.append(
            GraphCoverage(
                code=code,
                message=f"{message} (line {call.get('lineno', 0)})",
                runtime="partial",
            )
        )

    limit = max(1, int(data.limit))
    # Resolve a semantic scope before any size limit: the requested root must
    # survive even when unrelated large files would otherwise force a file-level
    # aggregate and erase the focused function/control detail.
    scoped = bool(data.scope_id) and data.scope_id not in unit_ids
    if not scoped:
        if (len(blocks) + len(nodes)) > limit:
            blocks, nodes, edges, dropped = _aggregate_to_files(blocks, nodes, edges)
            omitted += dropped
        if len(blocks) > limit:
            blocks, nodes, edges, pruned = _prune_blocks(blocks, edges, limit)
            omitted += pruned

    known = {b.id for b in blocks} | {n.id for n in nodes}
    edges = [
        e for e in edges if e.source in known and e.target in known and e.source != e.target
    ]
    for block in blocks:
        block.members = [m for m in block.members if m in known]
        if block.parent_id is not None and block.parent_id not in known:
            block.parent_id = None

    owners = {block.id: block for block in blocks}
    for child in blocks:
        if child.parent_id in owners and child.id not in owners[child.parent_id].members:
            owners[child.parent_id].members.append(child.id)
    for node in nodes:
        if node.block_id in owners and node.id not in owners[node.block_id].members:
            owners[node.block_id].members.append(node.id)

    graph = SemanticGraph(
        source_digest=hashlib.sha256(
            "|".join(f"{u.id}:{u.digest}" for u in units).encode()
        ).hexdigest(),
        roots=[project_block_id],
        blocks=blocks,
        nodes=nodes,
        edges=edges,
        coverage=coverage,
        omitted_count=omitted,
    )
    if scoped:
        graph = _scope_graph(graph, data.scope_id)
        graph, dropped = _bound_scoped(graph, limit)
        omitted += dropped
        graph = graph.model_copy(update={"omitted_count": omitted})
    return graph, omitted


def _file_owner(node_id: str, block_parent: dict, block_kind: dict):
    seen = set()
    current = node_id
    while current is not None and current not in seen:
        seen.add(current)
        if block_kind.get(current) == "file":
            return current
        current = block_parent.get(current)
    return None


def _aggregate_to_files(blocks, nodes, edges):
    """Large graph -> bounded file-level aggregate; dependencies preserved.

    Every block (not just file plates) is mapped to its owning file through the
    real parent hierarchy, so a call from a function plate in one file to a
    function in another survives as one file-level edge instead of vanishing.
    """
    kept = [b for b in blocks if b.kind in ("project", "folder", "file")]
    block_parent = {b.id: b.parent_id for b in blocks}
    block_kind = {b.id: b.kind for b in blocks}
    owner_of = {}
    for block in blocks:
        owner_of[block.id] = _file_owner(block.id, block_parent, block_kind)
    for node in nodes:
        owner_of[node.id] = _file_owner(node.block_id, block_parent, block_kind)
    aggregated: dict = {}
    for edge in edges:
        if edge.kind == "contains":
            continue
        source_file = owner_of.get(edge.source)
        target_file = owner_of.get(edge.target)
        if source_file is None or target_file is None or source_file == target_file:
            continue
        key = (source_file, target_file, edge.kind)
        originals = list(edge.original_ids) or ([edge.id] if edge.id else [])
        existing = aggregated.get(key)
        if existing is None:
            aggregated[key] = GraphEdge(
                id=_id("edge", source_file, target_file, edge.kind),
                source=source_file,
                target=target_file,
                kind=edge.kind,
                label=edge.label,
                provenance=edge.provenance or "inferred",
                original_ids=originals,
                count=len(originals),
            )
        else:
            ids = list(existing.original_ids)
            for original in originals:
                if original not in ids:
                    ids.append(original)
            aggregated[key] = existing.model_copy(
                update={"original_ids": ids, "count": len(ids)}
            )
    dropped = (len(blocks) - len(kept)) + len(nodes)
    return kept, [], list(aggregated.values()), dropped



def _prune_blocks(blocks, edges, limit):
    """Retain project/folder ancestors plus a bounded prefix of file plates.

    Omitted files are folded onto their nearest retained ancestor so cross-file
    relations survive as aggregate boundary edges instead of being discarded.
    """
    hierarchy = [b for b in blocks if b.kind in ("project", "folder")]
    files = [b for b in blocks if b.kind == "file"]
    if len(hierarchy) >= limit:
        hierarchy = hierarchy[:limit]
        files = []
    budget = max(0, limit - len(hierarchy))
    retained = files[:budget]
    dropped_files = files[budget:]
    hierarchy_ids = {b.id for b in hierarchy}
    parent = {b.id: b.parent_id for b in blocks}
    plate: dict = {}
    for block in dropped_files:
        current = block.parent_id
        while current is not None and current not in hierarchy_ids:
            current = parent.get(current)
        plate[block.id] = current or (hierarchy[0].id if hierarchy else None)

    def map_id(identifier):
        return plate.get(identifier, identifier)

    merged: dict = {}
    for edge in edges:
        source = map_id(edge.source)
        target = map_id(edge.target)
        if source is None or target is None or source == target:
            continue
        key = (source, target, edge.kind)
        originals = list(edge.original_ids) or ([edge.id] if edge.id else [])
        existing = merged.get(key)
        if existing is None:
            merged[key] = edge.model_copy(
                update={
                    "id": _id("edge", source, target, edge.kind, edge.label),
                    "source": source,
                    "target": target,
                    "original_ids": originals,
                    "count": len(originals),
                }
            )
        else:
            ids = list(existing.original_ids)
            for original in originals:
                if original not in ids:
                    ids.append(original)
            merged[key] = existing.model_copy(
                update={"original_ids": ids, "count": len(ids)}
            )
    return hierarchy + retained, [], list(merged.values()), len(dropped_files)


def _bound_scoped(graph: SemanticGraph, limit: int) -> tuple[SemanticGraph, int]:
    """Bound an already scope-filtered graph without collapsing it to file plates.

    The requested root is always retained; the remaining budget goes to the
    scope's own blocks and then its nodes. The exact number of dropped elements
    is reported as omitted coverage instead of fabricating adjacency.
    """
    blocks = list(graph.blocks)
    nodes = list(graph.nodes)
    total = len(blocks) + len(nodes)
    if total <= limit:
        return graph, 0
    roots = list(graph.roots)
    root_set = set(roots)
    primary = [b for b in blocks if b.id in root_set]
    rest = [b for b in blocks if b.id not in root_set]
    budget = max(0, limit - len(primary))
    kept_rest = rest[:budget]
    budget -= len(kept_rest)
    kept_nodes = nodes[:budget] if budget > 0 else []
    kept = primary + kept_rest
    dropped = total - (len(kept) + len(kept_nodes))
    known = {b.id for b in kept} | {n.id for n in kept_nodes}
    for block in kept:
        block.members = [m for m in block.members if m in known]
        if block.parent_id is not None and block.parent_id not in known:
            block.parent_id = None
    edges = [e for e in graph.edges if e.source in known and e.target in known]
    kept_roots = [r for r in roots if r in known]
    if not kept_roots and kept:
        kept_roots = [kept[0].id]
    return (
        graph.model_copy(
            update={
                "blocks": kept,
                "nodes": kept_nodes,
                "edges": edges,
                "roots": kept_roots,
            }
        ),
        dropped,
    )

def _scope_graph(graph: SemanticGraph, scope_id: str) -> SemanticGraph:
    block_ids = {b.id: b for b in graph.blocks}
    node_ids = {n.id: n for n in graph.nodes}
    seed = None
    if scope_id in block_ids:
        seed = block_ids[scope_id]
    elif scope_id in node_ids:
        seed = block_ids.get(node_ids[scope_id].block_id)
    else:
        for block in graph.blocks:
            if (
                block.label == scope_id
                or block.logical_key == scope_id
                or block.logical_key.endswith("::" + scope_id)
                or block.logical_key.endswith("::" + scope_id + "::")
            ):
                seed = block
                break
    if seed is None:
        raise KeyError(f"Unknown graph scope: {scope_id}")
    keep = set()
    stack = [seed.id]
    while stack:
        current = stack.pop()
        if current in keep:
            continue
        keep.add(current)
        block = block_ids.get(current)
        if block:
            stack.extend(block.members)
    keep = {k for k in keep if k in block_ids or k in node_ids}
    blocks = [b for b in graph.blocks if b.id in keep]
    nodes = [n for n in graph.nodes if n.id in keep]
    edges = [e for e in graph.edges if e.source in keep and e.target in keep]
    for block in blocks:
        block.members = [m for m in block.members if m in keep]
        if block.parent_id is not None and block.parent_id not in keep:
            block.parent_id = None
    return graph.model_copy(
        update={"blocks": blocks, "nodes": nodes, "edges": edges, "roots": [seed.id]}
    )
