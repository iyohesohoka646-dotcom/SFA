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
        self.drawing = DrawingService(self.root, self.catalog, pool=research.pool, tools=self.tools)
        self.jobs = JobManager(self.store)
        self.models = None
        self._harness = None
        self._changes = None
        self._owns_models = False
        self._closed = False

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
        return {'path': analysis.path, 'digest': analysis.source_digest, 'code': path.read_text(encoding='utf-8')}

    def analysis(self, key):
        return AnalysisDocument.model_validate(self.store.get('analyses', key))

    def configure(self, config, *, expected_revision):
        return self.configurations.save(config, expected_revision=expected_revision)

    def plan(self, analysis_id, *, scope='compute', run_id=None, snapshot_ids=(), instance_ids=None):
        analysis = self.analysis(analysis_id)
        config = self.configurations.load()
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
        plan = compile_plan(analysis, config, self.catalog.definitions(), scope=scope,
            run_id=run_id, snapshot_ids=snapshot_ids, environment=environment)
        self.store.put('plans', plan.id, plan)
        return plan

    def execute(self, plan_id):
        plan = ExecutionPlan.model_validate(self.store.get('plans', plan_id))
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
            for instance in config.probes:
                definition = self.catalog.resolve(instance.definition_id)
                if instance.enabled and definition.capability == 'check' and definition.execution == 'program':
                    checks.append(ProbeSpec(id=instance.id, kind=definition.id.removeprefix('check.'), binding=instance.binding,
                        parameters=instance.parameters, policy=instance.policy, budget_ms=min(instance.budget_ms, 30000)).model_dump(mode='json'))
            if cancel.is_set():
                raise InterruptedError()
            handle = self.research.start_analysis(Path(self.analysis(plan.analysis_id).path), interpreter=config.interpreter or None,
                arguments=config.arguments, mode=config.capture, probes=checks, adapters=config.adapters, expected_digest=plan.source_digest)
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
        if plan.snapshot_ids:
            snapshots = [self.research.store.snapshot(key) for key in plan.snapshot_ids[:plan.config.max_outputs]]
            if any(s.run_id != run_id for s in snapshots):
                raise ValueError('Snapshot belongs to another run')
        else:
            snapshots = self.research.store.snapshots(run_id, latest=True, limit=plan.config.max_outputs + 1)
        outputs = []
        truncated = False
        counts = {'drawing_errors': 0, 'check_failures': 0, 'unknown': 0}
        for snapshot in snapshots:
            for instance in plan.config.probes:
                if not instance.enabled or not (instance.binding == snapshot.id or fnmatchcase(snapshot.name, instance.binding) or fnmatchcase(snapshot.binding_id, instance.binding)):
                    continue
                definition = self.catalog.resolve(instance.definition_id)
                if plan.scope == 'replot' and definition.capability != 'view':
                    continue
                if len(outputs) >= plan.config.max_outputs:
                    truncated = True
                    break
                if cancel.is_set():
                    raise InterruptedError()
                if definition.id == 'view.relationships':
                    output = relationship_output(self.research, snapshot.id).model_copy(update={'instance_id': instance.id})
                elif definition.execution in ('model', 'skill'):
                    from .intelligence.harness import HarnessRequest
                    policy = next(p for p in plan.config.harness if p.role == 'probe').model_copy(deep=True)
                    if instance.parameters.get('provider_id'):
                        policy.provider_id = instance.parameters['provider_id']
                    if instance.parameters.get('model'):
                        policy.model = instance.parameters['model']
                    request = HarnessRequest(question=instance.parameters.get('prompt') or 'Explain the selected scientific evidence, its direct relationships and coverage.',
                        analysis_id=plan.analysis_id, run_id=run_id, snapshot_id=snapshot.id, policy=policy, skill_id=instance.parameters.get('skill_id'))
                    result = asyncio.run(self.harness.execute(request, task_id=task.id, cancel=cancel))
                    output = ProbeOutput(instance_id=instance.id, definition_id=definition.id, capability=definition.capability, execution=definition.execution,
                        status='ready' if result['status'] == 'completed' else 'cancelled' if result['status'] == 'cancelled' else 'unknown' if result['status'] == 'offline' else 'error',
                        run_id=run_id, snapshot_id=snapshot.id, analysis_id=plan.analysis_id, fidelity=snapshot.fidelity,
                        provenance='skill' if definition.execution == 'skill' else 'model', message=result['answer'] or result['message'], data={'context_id': result['context_id'], 'citations': result['citations'], 'automatic_check': False})
                else:
                    output = self.drawing.render(instance, snapshot, cancel=cancel)
                self.store.put('outputs', output.id, output)
                outputs.append(output.id)
                if output.status == 'error' and output.capability == 'view':
                    counts['drawing_errors'] += 1
                if output.status == 'fail' and output.capability == 'check':
                    counts['check_failures'] += 1
                if output.status == 'unknown':
                    counts['unknown'] += 1
                self.jobs.update(task.id, output_ids=outputs, progress=.6 + .39 * len(outputs) / plan.config.max_outputs)
            if truncated:
                break
        return {'output_ids': outputs, 'receipt': {**counts, 'truncated': truncated, 'source_digest': plan.source_digest,
            'config_digest': plan.config_digest, 'environment_digest': plan.environment_digest, 'evidence_only': plan.scope != 'compute'}}

    def _evidence_plan(self, run_id, *, scope, snapshot_ids=(), instance_ids=None):
        run = self.research.store.run(run_id)
        analyses = [a for a in self.store.list('analyses', limit=1000) if a['source_digest'] == run['source_digest'] and a['path'] == run['script']]
        if not analyses:
            path = Path(run['script'])
            if not path.exists() or analyze_source(path).source_digest != run['source_digest']:
                raise ValueError('Historical source is unavailable for this plan; retain its existing evidence')
            analysis = self.import_source(path)
        else:
            analysis = AnalysisDocument.model_validate(analyses[0])
        return self.plan(analysis.id, scope=scope, run_id=run_id, snapshot_ids=snapshot_ids, instance_ids=instance_ids)

    def execute_probes(self, run_id, *, snapshot_ids=(), instance_ids=None):
        return self.execute(self._evidence_plan(run_id, scope='probes', snapshot_ids=snapshot_ids, instance_ids=instance_ids).id)

    def replot(self, run_id, *, snapshot_ids=(), instance_ids=None):
        return self.execute(self._evidence_plan(run_id, scope='replot', snapshot_ids=snapshot_ids, instance_ids=instance_ids).id)

    def task(self, key):
        return self.jobs.get(key)

    def outputs(self, *, task_id=None, run_id=None, snapshot_id=None):
        if task_id:
            return [self.store.get('outputs', key) for key in self.task(task_id).output_ids]
        return [output for output in self.store.list('outputs', limit=1000)
                if (run_id is None or output['run_id'] == run_id) and (snapshot_id is None or output['snapshot_id'] == snapshot_id)]

    def relationships(self, snapshot_id):
        return relationship_output(self.research, snapshot_id)

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.jobs.close()
        self.drawing.close()
        if self._owns_models and self.models is not None:
            self.models.close()
