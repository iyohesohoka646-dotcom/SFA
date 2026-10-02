"""Reviewed fragment changes. No candidate is imported or executed."""
from __future__ import annotations

import ast
import difflib
import io
import json
from pathlib import Path
import textwrap
import tokenize

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider

from ...source import replace_body, symbol_text
from ...storage import atomic_write_private, atomic_write
from ..agent.privacy import clean_text
from ..agent.source import read_source
from .analysis import analyze_source, digest
from .models import CodeProposal

PURE_IMPORTS = {'math', 'statistics', 'collections', 'itertools', 'functools', 'typing', 'datetime'}


class ScientificChangeService:
    def __init__(self, workbench):
        self.workbench = workbench
        self.store = workbench.store
        self.journal = self.store.state / 'change-journal.json'
        self._recover()

    def _recover(self):
        if not self.journal.exists():
            return
        with self.store.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            item = json.loads(self.journal.read_text(encoding='utf-8'))
            proposal = self.get(item['proposal_id'])
            path = Path(proposal.path)
            current = read_source(path).digest if path.exists() else ''
            if current == item['after']:
                proposal.status, proposal.accepted_digest = 'accepted', current
            elif current != item['before']:
                proposal.status = 'conflict'
                proposal.diagnostics = ['Source changed during interrupted acceptance; inspect the file before another proposal']
            self._put(conn, proposal)
            self.journal.unlink(missing_ok=True)

    def get(self, key):
        return CodeProposal.model_validate(self.store.get('proposals', key))

    def _put(self, conn, proposal):
        conn.execute('INSERT INTO records(kind,id,payload) VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload',
            ('proposals', proposal.id, proposal.model_dump_json()))

    def _target(self, proposal):
        analysis = self.workbench.analysis(proposal.analysis_id)
        obj = next((o for o in analysis.objects if o.id == proposal.object_id), None)
        if obj is None or obj.path != proposal.path or obj.kind not in ('function', 'assignment'):
            raise ValueError('Select a declared function or one stable assignment step')
        return obj

    def _allowed_imports(self, source, obj=None):
        tree = ast.parse(source)
        nodes = list(tree.body)
        if obj is not None:
            nodes += list(ast.walk(ast.parse(textwrap.dedent(obj.code))))
        roots = set(PURE_IMPORTS)
        for node in nodes:
            if isinstance(node, ast.Import):
                roots.update(a.name.split('.')[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and not node.level:
                roots.add((node.module or '').split('.')[0])
        return sorted(roots)

    def _assignment(self, source, obj, candidate):
        old = ast.parse(textwrap.dedent(obj.code))
        new = ast.parse(candidate)
        allowed = (ast.Assign, ast.AnnAssign, ast.AugAssign)
        if len(old.body) != 1 or len(new.body) != 1 or not isinstance(old.body[0], allowed) or type(old.body[0]) is not type(new.body[0]):
            raise ValueError('Candidate must contain exactly the same assignment boundary')
        before, after = old.body[0], new.body[0]
        old_targets = before.targets if isinstance(before, ast.Assign) else [before.target]
        new_targets = after.targets if isinstance(after, ast.Assign) else [after.target]
        if [ast.dump(n) for n in old_targets] != [ast.dump(n) for n in new_targets]:
            raise ValueError('Assignment targets must remain unchanged')
        for node in ast.walk(new):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ('eval', 'exec', '__import__', 'compile'):
                raise ValueError('Dynamic code loading is outside the patch policy')
        replacement = cst.parse_module(candidate).body[0]
        class Replace(cst.CSTTransformer):
            METADATA_DEPENDENCIES = (PositionProvider,)
            def __init__(self):
                self.count = 0
            def leave_SimpleStatementLine(self, original_node, updated_node):
                position = self.get_metadata(PositionProvider, original_node)
                if position.start.line == obj.line and position.end.line == obj.end_line:
                    if len(original_node.body) != 1:
                        raise ValueError('Split a statement containing semicolons before proposing a patch')
                    self.count += 1
                    return replacement.with_changes(leading_lines=original_node.leading_lines)
                return updated_node
        visitor = Replace()
        result = MetadataWrapper(cst.parse_module(source)).visit(visitor).code
        if visitor.count != 1:
            raise ValueError('Assignment boundary is ambiguous')
        return result

    def _patched(self, proposal):
        if proposal.object_id is None:
            path = Path(proposal.path).resolve()
            if not path.is_relative_to(self.workbench.root.resolve()) or path.suffix != '.py' or path.exists():
                raise ValueError('New analysis must be a new Python file inside this project')
            tree = ast.parse(proposal.candidate)
            for node in ast.walk(tree):
                imports = [a.name.split('.')[0] for a in node.names] if isinstance(node, ast.Import) else [(node.module or '').split('.')[0]] if isinstance(node, ast.ImportFrom) else []
                if isinstance(node, ast.ImportFrom) and node.level or set(imports) - (PURE_IMPORTS | {'numpy', 'pandas', 'scipy'}):
                    raise ValueError('New analysis imports an undeclared dependency')
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ('eval', 'exec', '__import__', 'compile'):
                    raise ValueError('Dynamic code loading is outside the patch policy')
            compile(proposal.candidate, str(path), 'exec')
            return proposal.candidate, '', 'utf-8'
        source = read_source(Path(proposal.path))
        if source.digest != proposal.source_digest:
            raise ValueError('Source changed since this proposal was created')
        obj = self._target(proposal)
        if obj.kind == 'function':
            original = symbol_text(source.text, obj.qualname)
            patched = replace_body(source.text, obj.qualname, proposal.candidate, self._allowed_imports(source.text, obj))
        else:
            # A sanitized display excerpt must never become a rollback source.
            original = textwrap.dedent(''.join(source.text.splitlines(keepends=True)[obj.line - 1:obj.end_line]))
            patched = self._assignment(source.text, obj, proposal.candidate)
        compile(patched, proposal.path, 'exec')
        raw = Path(proposal.path).read_bytes()
        encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
        return patched, original, encoding

    def propose(self, analysis_id, object_id, candidate):
        analysis = self.workbench.analysis(analysis_id)
        obj = next((o for o in analysis.objects if o.id == object_id), None)
        if obj is None:
            raise ValueError('Proposal object is not in this analysis')
        proposal = CodeProposal(analysis_id=analysis_id, object_id=object_id, path=obj.path, source_digest=analysis.source_digest, candidate=textwrap.dedent(candidate))
        return self._validate(proposal)

    def propose_new(self, analysis_id, relative_path, candidate):
        self.workbench.analysis(analysis_id)
        path = (self.workbench.root / relative_path).resolve()
        if not path.is_relative_to(self.workbench.root.resolve()) or path.exists() or path.suffix != '.py':
            raise ValueError('New analysis must be a new Python file inside this project')
        proposal = CodeProposal(analysis_id=analysis_id, path=str(path), source_digest='', candidate=candidate)
        return self._validate(proposal)

    def _validate(self, proposal):
        try:
            if clean_text(proposal.candidate, 16384) != proposal.candidate:
                raise ValueError('Use credential references; secret-bearing candidates cannot be saved')
            _, original, _ = self._patched(proposal)
            proposal.original_fragment = original if clean_text(original, 16384) == original else None
            proposal.diff = clean_text(''.join(difflib.unified_diff(original.splitlines(keepends=True), proposal.candidate.splitlines(keepends=True), fromfile='current fragment', tofile='candidate fragment')), 16384)
            proposal.status = 'valid'
            proposal.diagnostics = ['Syntax and modification boundary verified; numerical behavior remains unverified']
        except Exception as error:
            proposal.status = 'invalid'
            proposal.candidate = clean_text(proposal.candidate, 16384)
            proposal.diagnostics = [clean_text(str(error))]
        self.store.put('proposals', proposal.id, proposal)
        return proposal

    def validate(self, key):
        proposal = self.get(key)
        if proposal.status in ('accepted', 'rejected'):
            raise ValueError('This proposal is already finalized')
        return self._validate(proposal)

    def accept(self, key):
        conflict = None
        with self.store.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            proposal = self.get(key)
            if proposal.status != 'valid':
                raise ValueError('Only a valid pending proposal can be accepted')
            try:
                patched, _, encoding = self._patched(proposal)
            except ValueError as error:
                proposal.status = 'conflict'
                self._put(conn, proposal)
                conflict = error
            if conflict is None:
                raw = patched.encode(encoding)
                import hashlib
                after = hashlib.sha256(raw).hexdigest()
                atomic_write_private(self.journal, json.dumps({'proposal_id': key, 'before': proposal.source_digest, 'after': after}))
                atomic_write(Path(proposal.path), raw)
                proposal.status, proposal.accepted_digest = 'accepted', after
                self._put(conn, proposal)
        if conflict is not None:
            raise conflict
        self.journal.unlink(missing_ok=True)
        self.workbench.import_source(proposal.path)
        return proposal

    def record_validation(self, key, run_id, output_ids):
        proposal = self.get(key)
        if proposal.status != 'accepted' or not output_ids:
            raise ValueError('Select executed program checks for an accepted proposal')
        run = self.workbench.research.store.run(run_id)
        if run['source_digest'] != proposal.accepted_digest or run['status'] != 'completed':
            raise ValueError('Validation run does not match the accepted source version')
        for output_id in output_ids:
            output = self.store.get('outputs', output_id)
            if output['run_id'] != run_id or output['capability'] != 'check' or output['execution'] != 'program' or output['status'] != 'pass':
                raise ValueError('Selected validation requires matching, passed program checks')
        proposal.behavior, proposal.validation_run_id, proposal.validation_output_ids = 'verified', run_id, list(output_ids)
        self.store.put('proposals', key, proposal)
        return proposal

    def reject(self, key):
        with self.store.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            proposal = self.get(key)
            if proposal.status == 'accepted':
                raise ValueError('Accepted proposals require a reviewed rollback')
            proposal.status = 'rejected'
            self._put(conn, proposal)
        return proposal

    def rollback(self, key):
        original = self.get(key)
        if original.status != 'accepted' or original.object_id is None or original.original_fragment is None:
            raise ValueError('No safe scoped rollback fragment is available; use source control')
        if read_source(Path(original.path)).digest != original.accepted_digest:
            raise ValueError('Source changed after acceptance; review a new rollback')
        analysis = self.workbench.import_source(original.path)
        old = self._target(original)
        obj = next((o for o in analysis.objects if o.qualname == old.qualname and o.line == old.line and o.kind == old.kind), None)
        if obj is None:
            raise ValueError('Rollback target is no longer unambiguous')
        proposal = self.propose(analysis.id, obj.id, original.original_fragment)
        proposal.rollback_of = original.id
        self.store.put('proposals', proposal.id, proposal)
        return proposal
