"""Compose scientific services. Parsing, computation and drawing are explicit calls."""
from __future__ import annotations

from pathlib import Path
import asyncio
import sys
import threading
from fnmatch import fnmatchcase

from ..models import ProbeSpec
from ..agent.source import read_source
from ..agent.privacy import clean_text
from ...storage import atomic_write_private
from .analysis import analyze_source
from .catalog import ProbeCatalog
from .configuration import ConfigurationStore
from .jobs import JobManager
from .models import AnalysisDocument, ExecutionPlan, ProbeOutput
from .planning import compile_plan, fingerprint
from .relations import relationship_output
from .rendering import DrawingService
from .store import WorkbenchStore
from .tools import ToolManager


class WorkbenchService:
    def __init__(self, research):
        self.research = research
        self.root = research.root
        self.store = WorkbenchStore(self.root)
        self.configurations = ConfigurationStore(self.root)
        self.catalog = ProbeCatalog(research.registry)
        self.tools = ToolManager(self.root)
        from .resources import ResourceManager
        self.resources = ResourceManager(self.root, self.catalog, self.tools)
        from .data_semantics import SemanticsService
        self.semantics = SemanticsService(self.root)
        from .preferences import PreferenceService
        self.preferences = PreferenceService(self.root)
        self.drawing = DrawingService(self.root, self.catalog, pool=research.pool, tools=self.tools)
        self.jobs = JobManager(self.store)
        self.models = None
        self._harness = None
        self._changes = None
        self._owns_models = False
        self._closed = False
        self._model_lock = threading.Lock()

    @property
    def changes(self):
        from .changes import ScientificChangeService
        if self._changes is None:
            self._changes = ScientificChangeService(self)
        return self._changes

    @property
    def harness(self):
        from .intelligence.harness import HarnessService
        if self.models is None:
            from ...settings.service import ModelSettingsService
            self.models = ModelSettingsService(self.root)
            self._owns_models = True
        if self._harness is None or self._harness.models is not self.models:
            self._harness = HarnessService(self, self.models)
        return self._harness

    def ask(self, request):
        def execute(task, cancel):
            result = asyncio.run(self.harness.execute(request, task_id=task.id, cancel=cancel))
            return {'receipt': result, 'status': 'failed' if result['status'] in ('error', 'budget_exhausted') else 'completed'}
        return self.jobs.submit('intelligence.' + request.policy.role, execute, receipt={'analysis_id': request.analysis_id})

    def import_source(self, path):
        path = Path(path)
        if not path.is_absolute():
            path = self.root / path
        analysis = analyze_source(path)
        source = read_source(path)
        if source.digest != analysis.source_digest:
            raise ValueError('Source changed during import; retry parsing')
        atomic_write_private(self.research.store.state / 'sources' / (source.digest + '.txt'), clean_text(source.text, 10 * 1024 * 1024))
        self.store.put('analyses', analysis.id, analysis)
        return analysis

    def analysis_source(self, key):
        analysis = self.analysis(key)
        path = self.research.store.state / 'sources' / (analysis.source_digest + '.txt')
        if not path.exists():
            raise LookupError('Imported source snapshot is unavailable')
        return {'path': analysis.path, 'digest': analysis.source_digest, 'code': path.read_bytes().decode('utf-8')}

    def analysis(self, key):
        return AnalysisDocument.model_validate(self.store.get('analyses', key))

    def run_analysis(self, run_id):
        run = self.research.store.run(run_id)
        records = [a for a in self.store.list('analyses', limit=1000) if a['source_digest'] == run['source_digest'] and a['path'] == run['script']]
        if records:
            return AnalysisDocument.model_validate(records[0])
        source = self.research.source(run_id)
        analysis = analyze_source(Path(run['script']), archived_text=source['code'], expected_digest=run['source_digest'])
        self.store.put('analyses', analysis.id, analysis)
        return analysis

    def configure(self, config, *, expected_revision):
        return self.configurations.save(config, expected_revision=expected_revision)

    def plan(self, analysis_id, *, scope='compute', run_id=None, snapshot_ids=(), instance_ids=None, target_scope=None):
        analysis = self.analysis(analysis_id)
        config = self.configurations.load()
        from .semantic_models import ScopeSelector
        target_scope = ScopeSelector.model_validate(target_scope or {})
        if scope == 'compute':
            # A new computation observes new evidence for selected logical
            # objects. Exact historical evidence belongs to probes/replot.
            def logical(ref):
                return ref.model_copy(update={'snapshot_id':None, 'run_id':None})
            target_scope = target_scope.model_copy(deep=True, update={'targets':[logical(t) for t in target_scope.targets]})
            config = config.model_copy(deep=True)
            for probe in config.probes:
                probe.inputs = {role:logical(ref) for role,ref in probe.inputs.items()}
                if probe.selector is not None:
                    probe.selector.targets = [logical(t) for t in probe.selector.targets]
        script = Path(config.script or analysis.path)
        if not script.is_absolute():
            script = self.root / script
        if scope == 'compute' and script.resolve() != Path(analysis.path).resolve():
            raise ValueError('Configuration belongs to another source; import the configured script')
        if scope == 'compute' and analyze_source(script).source_digest != analysis.source_digest:
            raise ValueError('Source changed; import it again before planning')
        if run_id:
            run = self.research.store.run(run_id)
            if run['source_digest'] != analysis.source_digest:
                raise ValueError('Saved run belongs to a different source version')
        if instance_ids is not None:
            wanted = set(instance_ids)
            if wanted - {p.id for p in config.probes}:
                raise ValueError('Requested probe instance is not configured')
            config = config.model_copy(deep=True, update={'probes': [p for p in config.probes if p.id in wanted]})
        environment = self.tools.scan(config.interpreter or sys.executable)
        snapshots = [self.research.store.snapshot(key) for key in snapshot_ids] if snapshot_ids else self.research.store.snapshots(run_id, latest=True, limit=10000, metadata_only=True) if run_id else []
        referenced = {ref.snapshot_id for p in config.probes if p.enabled and self.catalog.resolve(p.definition_id).input_mode == 'joint'
            for ref in p.inputs.values() if ref.snapshot_id}
        if scope != 'compute':
            known_snapshots = {s.id for s in snapshots}
            snapshots += [self.research.store.snapshot(key) for key in referenced - known_snapshots]
        foreign = {s.id for s in snapshots if s.run_id != run_id}
        if foreign and scope == 'compute':
            raise ValueError('Snapshot belongs to another run')
        plan = compile_plan(analysis, config, self.catalog.definitions(), scope=scope,
            run_id=run_id, snapshot_ids=snapshot_ids, environment=environment, snapshots=snapshots, target_scope=target_scope)
        for call in plan.invocations:
            if any(target.snapshot_id in foreign for target in call.targets) and not (call.definition.input_mode == 'joint' and call.instance.parameters.get('allow_cross_run') is True):
                raise ValueError('Cross-run input requires explicit allow_cross_run on its joint probe')
            call.semantics = {target.logical_key: value.model_dump(mode='json') for target in call.targets
                if (value := self.semantics.get(target.logical_key)) is not None and value.accepted}
        if foreign - {t.snapshot_id for call in plan.invocations for t in call.targets}:
            raise ValueError('Cross-run input is not assigned to a reviewed joint probe')
        plan.preferences = self.preferences.load()['values']
        self.store.put('plans', plan.id, plan)
        return plan

    def execute(self, plan_id):
        plan = ExecutionPlan.model_validate(self.store.get('plans', plan_id))
        if plan.protocol_version != 3:
            raise ValueError('Legacy plan must be reviewed and prepared again with the current protocol')
        analysis = self.analysis(plan.analysis_id)
        if plan.scope == 'compute':
            if analyze_source(Path(analysis.path)).source_digest != plan.source_digest:
                raise ValueError('Source changed; this plan cannot execute')
            if fingerprint(self.tools.scan(plan.config.interpreter or sys.executable)) != plan.environment_digest:
                raise ValueError('Environment changed; prepare a new plan')
        else:
            run = self.research.store.run(plan.run_id)
            if run['status'] not in ('completed', 'failed', 'cancelled', 'timeout', 'interrupted'):
                raise ValueError('Wait for computation before evaluating saved evidence')
        return self.jobs.submit(plan.scope, lambda task, cancel: self._execute(plan, task, cancel), plan_id=plan.id)

    def _execute(self, plan, task, cancel):
        run_id = plan.run_id
        config = plan.config
        if plan.scope == 'compute':
            checks = []
            grouped = {}
            for invocation in plan.invocations:
                instance, definition = invocation.instance, invocation.definition
                if instance.enabled and definition.capability == 'check' and definition.execution == 'program' and not definition.entrypoint and invocation.targets[0].kind == 'data':
                    signature = (instance.id, fingerprint(instance.parameters))
                    group = grouped.setdefault(signature, ProbeSpec(id=instance.id, kind=definition.id.removeprefix('check.'), binding=instance.binding,
                        parameters=instance.parameters, policy=instance.policy, target_keys=[], budget_ms=min(instance.budget_ms, 30000)))
                    for target in invocation.targets:
                        if target.logical_key not in group.target_keys:
                            group.target_keys.append(target.logical_key)
            checks = [spec.model_dump(mode='json') for spec in grouped.values()]
            if cancel.is_set():
                raise InterruptedError()
            full_targets = list(dict.fromkeys(target.logical_key for call in plan.invocations
                if call.definition.evidence in ('full', 'full_coordinates') for target in call.targets if target.kind == 'data'))
            handle = self.research.start_analysis(Path(self.analysis(plan.analysis_id).path), interpreter=config.interpreter or None,
                arguments=config.arguments, mode=config.capture, probes=checks, adapters=config.adapters,
                capture={**{k:v for k,v in plan.preferences.get('capture',{}).items() if k!='level'},'full_targets': full_targets}, expected_digest=plan.source_digest)
            run_id = handle.run_id
            self.jobs.update(task.id, run_id=run_id, calculation_status='running')
            while True:
                if cancel.is_set():
                    self.research.cancel(run_id)
                    self.jobs.update(task.id, calculation_status='cancelled')
                    raise InterruptedError()
                try:
                    run = self.research.wait(run_id, timeout=.1)
                    break
                except TimeoutError:
                    status = self.research.calculation_status(run_id)
                    if status != self.jobs.get(task.id).calculation_status:
                        self.jobs.update(task.id, calculation_status=status,
                            message='Probe gate paused; inspect its result before continuing' if status == 'paused' else '')
            self.jobs.update(task.id, calculation_status=run['status'], progress=.6)
        else:
            run = self.research.store.run(run_id)
            self.jobs.update(task.id, run_id=run_id, calculation_status=run['status'])
        result = self._postprocess(plan, run_id, task, cancel)
        return {'run_id': run_id, 'calculation_status': run['status'], **result}

    def _postprocess(self, plan, run_id, task, cancel):
        from .bindings import resolve_calls, snapshot_target
        from .scopes import resolve_scope, source_targets
        analysis = self.analysis(plan.analysis_id)
        if plan.scope == 'compute':
            snapshots = self.research.store.snapshots(run_id, latest=True, limit=10000, metadata_only=True)
            available = [snapshot_target(snapshot, analysis) for snapshot in snapshots]
            available.extend(target for target in source_targets(analysis) if target.kind != 'data')
            targets = resolve_scope(analysis.graph, plan.target_scope, available)
            calls = resolve_calls(analysis, plan.config, plan.definitions, targets, snapshots,
                resource_versions=plan.invocations[0].resource_versions if plan.invocations else {}, scope=plan.scope)
            frozen_meaning = {key: value for call in plan.invocations for key, value in call.semantics.items()}
            for call in calls:
                call.semantics = {target.logical_key: frozen_meaning[target.logical_key] for target in call.targets if target.logical_key in frozen_meaning}
        else:
            calls = plan.invocations
        outputs = []
        counts = {'drawing_errors': 0, 'check_failures': 0, 'unknown': 0}
        from concurrent.futures import ThreadPoolExecutor
        selected_calls = calls[:plan.config.max_outputs]
        workers = min(16, max(1, int(plan.preferences.get('probes',{}).get('concurrency',4))))
        def evaluate(invocation):
            if cancel.is_set():
                raise InterruptedError()
            self.store.put('invocations', invocation.id, invocation)
            if invocation.definition.execution in ('model', 'skill'):
                with self._model_lock:
                    return self._evaluate_call(invocation, run_id, plan, task, cancel)
            return self._evaluate_call(invocation, run_id, plan, task, cancel)
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='probe') as executor:
          for invocation, output in zip(selected_calls, executor.map(evaluate, selected_calls)):
            if cancel.is_set():
                raise InterruptedError()
            output = output.model_copy(update={'invocation_id': invocation.id, 'targets': invocation.targets,
                'parent_snapshot_ids': [target.snapshot_id for target in invocation.targets if target.snapshot_id],
                'data': {**output.data, 'definition_version': invocation.definition.version}})
            self.store.put('outputs', output.id, output)
            outputs.append(output.id)
            if output.status == 'error' and output.capability == 'view':
                counts['drawing_errors'] += 1
            if output.status == 'fail' and output.capability == 'check':
                counts['check_failures'] += 1
            if output.status == 'unknown':
                counts['unknown'] += 1
            self.jobs.update(task.id, output_ids=outputs, progress=.6 + .39 * len(outputs) / plan.config.max_outputs)
        return {'output_ids': outputs, 'receipt': {**counts, 'truncated': len(calls) > len(outputs),
            'omitted_calls': max(0, len(calls) - len(outputs)), 'source_digest': plan.source_digest,
            'config_digest': plan.config_digest, 'environment_digest': plan.environment_digest, 'evidence_only': plan.scope != 'compute'}}

    def _evaluate_call(self, invocation, run_id, plan, task, cancel):
        instance, definition = invocation.instance, invocation.definition
        if definition.entrypoint:
            from .programs import evaluate_program
            return evaluate_program(self,invocation,run_id,plan,cancel)
        if definition.input_mode == 'joint':
            return self._joint_output(invocation, run_id, plan, cancel)
        target = invocation.targets[0]
        snapshot = self.research.store.snapshot(target.snapshot_id) if target.snapshot_id else None
        if definition.execution in ('model', 'skill'):
            from .intelligence.harness import HarnessRequest
            policy = next(policy for policy in plan.config.harness if policy.role == 'probe').model_copy(deep=True)
            if instance.parameters.get('provider_id'):
                policy.provider_id = instance.parameters['provider_id']
            if instance.parameters.get('model'):
                policy.model = instance.parameters['model']
            source_ids = None
            if snapshot is None and target.kind != 'file':
                from .scopes import resolve_scope, source_targets
                from .semantic_models import ScopeSelector
                analysis = self.analysis(plan.analysis_id)
                scoped = resolve_scope(analysis.graph, ScopeSelector(mode='block', block_id=target.block_id), source_targets(analysis)) if target.block_id else []
                source_ids = ([target.object_id] if target.object_id else []) if target.kind == 'operation' else list(dict.fromkeys(item.object_id for item in scoped if item.object_id))
            request = HarnessRequest(question=instance.parameters.get('prompt') or 'Explain the selected scientific evidence, its direct relationships and coverage.',
                analysis_id=plan.analysis_id, run_id=run_id, snapshot_id=snapshot.id if snapshot else None,
                object_id=target.object_id if snapshot is None else None, source_object_ids=source_ids,
                policy=policy, skill_id=instance.parameters.get('skill_id'))
            result = asyncio.run(self.harness.execute(request, task_id=task.id, cancel=cancel))
            return ProbeOutput(instance_id=instance.id, definition_id=definition.id, capability=definition.capability, execution=definition.execution,
                status='ready' if result['status'] == 'completed' else 'cancelled' if result['status'] == 'cancelled' else 'unknown' if result['status'] == 'offline' else 'error',
                run_id=run_id, snapshot_id=snapshot.id if snapshot else None, analysis_id=plan.analysis_id, fidelity=snapshot.fidelity if snapshot else 'metadata_only',
                provenance='skill' if definition.execution == 'skill' else 'model', message=result['answer'] or result['message'],
                data={'context_id': result['context_id'], 'citations': result['citations'], 'automatic_check': False})
        if snapshot is None:
            return self._block_output(invocation, run_id, plan)
        if definition.id == 'view.relationships':
            return relationship_output(self.research, snapshot.id).model_copy(update={'instance_id': instance.id})
        return self.drawing.render(instance, snapshot, cancel=cancel, definition=definition, resource_versions=invocation.resource_versions)

    def _joint_output(self, invocation, run_id, plan, cancel):
        from .derivation import DerivationService
        return DerivationService(self).execute(invocation, run_id, plan, cancel)

    def _block_output(self, invocation, run_id, plan):
        target, definition = invocation.targets[0], invocation.definition
        analysis = self.analysis(plan.analysis_id)
        base = dict(instance_id=invocation.instance.id, definition_id=definition.id, capability=definition.capability,
            execution=definition.execution, run_id=run_id, analysis_id=plan.analysis_id, fidelity='metadata_only', provenance='inferred')
        if definition.id == 'check.structure':
            block = next((block for block in analysis.graph.blocks if block.id == target.block_id), None)
            coverage = [item.model_dump(mode='json') for item in analysis.graph.coverage if not block or item.source and block.source and block.source.line <= item.source.line <= block.source.end_line]
            return ProbeOutput(**base, status='unknown' if coverage else 'pass', message='结构覆盖检查', data={'coverage': coverage, 'diagnostics': analysis.diagnostics})
        if definition.id == 'view.controls':
            from .scopes import resolve_scope
            from .semantic_models import ScopeSelector, TargetRef
            summaries = self.research.store.control_summaries(run_id)
            if target.block_id:
                summaries = [summary for summary in summaries if resolve_scope(analysis.graph, ScopeSelector(mode='block', block_id=target.block_id),
                    [TargetRef(kind='control', logical_key=summary['node_id'], block_id=summary['node_id'])])]
            return ProbeOutput(**{**base, 'provenance': 'observed'}, status='ready' if summaries else 'unknown', message='实际控制摘要', data={'control_summaries': summaries})
        if definition.id == 'check.timing':
            if target.kind == 'function':
                records = [s for s in self.research.store.control_summaries(run_id) if s['node_id'] == target.block_id and s['kind'] == 'function']
                if records:
                    record = records[0]
                    data = {'calls': record['activations'], 'total_ms': record.get('total_ms', 0),
                        'maximum_ms': record.get('maximum_ms', 0), 'complete': record['complete'], 'timing': 'scope-including-observation'}
            else:
                obj = next((o for o in analysis.objects if o.id == target.object_id), None)
                records = [op for op in self.research.store.operations(run_id, limit=10000) if op.source and obj and
                    op.source.line == obj.line and op.source.column == obj.column and op.duration_ms is not None]
                if records:
                    data = {'calls': len(records), 'total_ms': sum(op.duration_ms for op in records),
                        'maximum_ms': max(op.duration_ms for op in records), 'complete': len(records) < 10000,
                        'timing': 'scope-including-observation'}
            if records:
                limit = invocation.instance.parameters.get('maximum_ms')
                status = 'unknown' if not data['complete'] else 'fail' if limit is not None and data['maximum_ms'] > limit else 'pass'
                return ProbeOutput(**{**base, 'provenance': 'observed'}, status=status, message='实际调用耗时（包含观察开销）', data=data)
        return ProbeOutput(**base, status='unknown', message='此目标缺少该探针所需的运行证据')

    def presenters(self, snapshot_id, analysis_id=None):
        from .bindings import effective_presenters
        snapshot = self.research.store.snapshot(snapshot_id)
        run = self.research.store.run(snapshot.run_id)
        candidates = [raw for raw in self.store.list('analyses', limit=1000) if raw['source_digest'] == run['source_digest'] and raw['path'] == run['script']]
        analysis = self.analysis(analysis_id) if analysis_id else AnalysisDocument.model_validate(candidates[0]) if candidates else AnalysisDocument(path=run['script'], source_digest=run['source_digest'])
        return effective_presenters(self.configurations.load(), self.catalog.definitions(), snapshot, analysis)

    def _evidence_plan(self, run_id, *, scope, snapshot_ids=(), instance_ids=None, target_scope=None):
        run = self.research.store.run(run_id)
        analysis = self.run_analysis(run_id)
        return self.plan(analysis.id, scope=scope, run_id=run_id, snapshot_ids=snapshot_ids, instance_ids=instance_ids, target_scope=target_scope)

    def execute_probes(self, run_id, *, snapshot_ids=(), instance_ids=None, target_scope=None):
        return self.execute(self._evidence_plan(run_id, scope='probes', snapshot_ids=snapshot_ids, instance_ids=instance_ids, target_scope=target_scope).id)

    def replot(self, run_id, *, snapshot_ids=(), instance_ids=None, target_scope=None):
        return self.execute(self._evidence_plan(run_id, scope='replot', snapshot_ids=snapshot_ids, instance_ids=instance_ids, target_scope=target_scope).id)

    def task(self, key):
        return self.jobs.get(key)

    def outputs(self, *, task_id=None, run_id=None, snapshot_id=None):
        if task_id:
            return [self.store.get('outputs', key) for key in self.task(task_id).output_ids]
        return [output for output in self.store.list('outputs', limit=1000)
                if (run_id is None or output['run_id'] == run_id) and (snapshot_id is None or output['snapshot_id'] == snapshot_id)]

    def relationships(self, snapshot_id):
        return relationship_output(self.research, snapshot_id)

    def retain_derived(self, key, retained):
        if type(retained) is not bool:
            raise ValueError('Retention must be explicitly true or false')
        record = self.store.get('derived', key)
        if retained:
            self.research.store.retain_artifacts([record['snapshot_id']], 'derived:'+key)
        else:
            self.research.store.release_artifacts('derived:'+key)
        record['retained'] = retained
        return self.store.put('derived', key, record)

    def propose_derived(self, key):
        """Recreate a computation as a pure function; accepting it is separate."""
        import json
        record = self.store.get('derived', key)
        parents = record['inputs']
        p = record['parameters']
        operator = record['operator']
        if operator == 'derive.elementwise':
            symbol = {'add':'+','subtract':'-','multiply':'*','divide':'/'}[p.get('operation','subtract')]
            expression = 'left '+symbol+' right'
        elif operator == 'derive.matmul':
            expression = 'left @ right'
        elif operator == 'derive.aggregate':
            method = p.get('method','mean')
            if method not in ('mean','sum','min','max','std','median'):
                raise ValueError('Unknown aggregation')
            expression = 'np.'+method+'(input, axis='+repr(p.get('axis'))+')'
        elif operator == 'derive.correlation':
            expression = 'np.corrcoef(np.asarray(left).reshape(-1), np.asarray(right).reshape(-1))[0, 1]'
        elif operator == 'derive.join':
            expression = 'left.merge(right, on='+repr(p['keys'])+', how='+repr(p.get('how','inner'))+', validate='+repr(p.get('cardinality','one_to_one'))+')'
        else:
            raise ValueError('This operator has no code proposal adapter')
        lines = ['# Derived evidence '+key, '# Parent snapshots: '+', '.join(t['snapshot_id'] for t in parents.values()),
            '# Frozen parameters: '+json.dumps(p,sort_keys=True), 'import numpy as np', '', 'def derive_'+key[:8]+'('+', '.join(parents)+'):',
            '    """Numeric kernel; the workbench validates versions, coordinates and budgets."""']
        if operator in ('derive.elementwise','derive.matmul','derive.correlation','derive.aggregate'):
            for role in parents:
                lines.append('    '+role+' = np.asarray('+role+')')
                if p.get('missing','error') == 'error':
                    lines.append('    if not np.isfinite('+role+').all(): raise ValueError("Missing or nonfinite input")')
        if operator == 'derive.elementwise' and not p.get('broadcast',False):
            lines.append('    if left.shape != right.shape: raise ValueError("Shape mismatch")')
        if operator == 'derive.correlation':
            lines.append('    if left.shape != right.shape: raise ValueError("Shape mismatch")')
            if not p.get('flatten',False):
                lines.append('    if left.ndim != 1: raise ValueError("Flatten must be explicit")')
            if p.get('missing') == 'pairwise':
                lines += ['    valid = np.isfinite(left) & np.isfinite(right)', '    left, right = left[valid], right[valid]']
            lines.append('    if left.size < 2 or np.std(left) == 0 or np.std(right) == 0: raise ValueError("Insufficient variance")')
        lines.append('    return '+expression)
        analysis = self.run_analysis(record['run_id'])
        return self.changes.propose_new(analysis.id, 'derived_analysis_'+key[:8]+'.py', '\n'.join(lines)+'\n')

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.jobs.close()
        self.drawing.close()
        if getattr(self, 'terminals', None):
            self.terminals.close()
        if self._owns_models and self.models is not None:
            self.models.close()
