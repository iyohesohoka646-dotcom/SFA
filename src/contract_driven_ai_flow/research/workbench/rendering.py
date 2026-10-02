from __future__ import annotations

import json
import time
from pathlib import Path

from ..agent.privacy import clean_text, sanitize_json
from ..models import ProbeSpec, SnapshotRef
from ..probes import ProbePool
from .catalog import ProbeCatalog
from .models import ProbeInstance, ProbeOutput
from .planning import fingerprint
from .process import run_process
from .store import WorkbenchStore
from .tools import ToolManager


class DrawingService:
    def __init__(self, root: Path, catalog: ProbeCatalog, *, pool=None, tools=None):
        self.catalog = catalog
        self.store = WorkbenchStore(root)
        self.tools = tools or ToolManager(root)
        self.pool = pool or ProbePool(catalog.registry, artifact_root=self.store.state)
        self._owns_pool = pool is None
        self.artifacts = self.store.state / 'drawings'
        self.artifacts.mkdir(exist_ok=True)

    def render(self, instance: ProbeInstance, snapshot: SnapshotRef, *, cancel=None) -> ProbeOutput:
        definition = self.catalog.resolve(instance.definition_id)
        started = time.perf_counter()
        output = ProbeOutput(instance_id=instance.id, definition_id=definition.id, capability=definition.capability,
            execution=definition.execution, status='unknown', run_id=snapshot.run_id, snapshot_id=snapshot.id,
            fidelity=snapshot.fidelity, data={'snapshot_id': snapshot.id, 'coverage': snapshot.coverage},
            cache_key=fingerprint({'snapshot': snapshot.id, 'descriptor': snapshot.descriptor.model_dump(mode='json'), 'sample': snapshot.sample,
                'parameters': instance.parameters, 'definition': definition.model_dump(mode='json')}))
        if cancel is not None and cancel.is_set():
            return output.model_copy(update={'status': 'cancelled', 'message': 'Task cancelled'})
        if not instance.enabled:
            return output.model_copy(update={'status': 'skipped', 'message': 'Probe disabled'})
        try:
            if definition.capability == 'check' and definition.execution == 'program':
                spec = ProbeSpec(id=instance.id, kind=definition.id.removeprefix('check.'), parameters=instance.parameters,
                    policy=instance.policy, budget_ms=min(instance.budget_ms, 30000))
                result = self.pool.evaluate(spec, snapshot, cancel=cancel)
                output = output.model_copy(update={'status': result.status, 'message': result.message, 'fidelity': result.fidelity, 'data': result.evidence})
            elif definition.execution == 'builtin':
                kind = definition.id.removeprefix('view.')
                values = snapshot.sample.get('values')
                if kind == 'auto':
                    kind = 'table' if snapshot.sample.get('columns') else 'matrix' if values else 'scalar' if snapshot.descriptor.kind == 'scalar' else 'metadata'
                available = kind == 'metadata' or kind == 'scalar' and snapshot.descriptor.kind == 'scalar' or kind in ('matrix', 'table') and values is not None
                output = output.model_copy(update={'status': 'ready' if available else 'unknown', 'message': 'Saved evidence view' if available else 'Required captured values are unavailable for this view',
                    'data': {**output.data, 'renderer': kind}})
            elif definition.tool_id:
                output = self._plot(instance, snapshot, output, definition.tool_id, cancel)
            else:
                output = output.model_copy(update={'message': 'Requires an explicit model, Skill or manual result'})
        except InterruptedError:
            output = output.model_copy(update={'status': 'cancelled', 'message': 'Task cancelled'})
        except (LookupError, ValueError) as error:
            output = output.model_copy(update={'status': 'unknown', 'message': clean_text(str(error))})
        except TimeoutError:
            output = output.model_copy(update={'status': 'error', 'message': 'Drawing worker exceeded time budget'})
        except Exception as error:
            output = output.model_copy(update={'status': 'error', 'message': f'Isolated drawing failed ({type(error).__name__})'})
        return output.model_copy(update={'duration_ms': (time.perf_counter() - started) * 1000})

    def _plot(self, instance, snapshot, output, tool, cancel):
        values = sanitize_json(snapshot.sample.get('values', []))
        if not values or not isinstance(values, list) or not all(isinstance(row, list) for row in values) or sum(map(len, values)) > 65536:
            raise LookupError('A bounded numeric matrix sample is required for this drawing adapter')
        if not any(type(value) in (int, float) for row in values for value in row):
            raise LookupError('Captured cells are not numeric; choose a table or register another adapter')
        interpreter, version = self.tools.resolve(tool)
        key = fingerprint({'key': output.cache_key, 'tool': tool, 'version': version, 'interpreter': interpreter})
        suffix = '.png' if tool in ('matplotlib', 'seaborn') else '.html' if tool == 'plotly' else '.json'
        path = self.artifacts / (key + suffix)
        try:
            receipt = self.store.get('artifacts', key)
            if path.exists() and path.stat().st_size == receipt['bytes']:
                return output.model_copy(update={'status': 'ready', 'artifact_id': key, 'cache_key': key, 'message': 'Reused saved drawing'})
        except KeyError:
            pass
        temp = path.with_name(key + '.' + output.id + '.tmp')
        kind = instance.parameters.get('kind', 'heatmap')
        if kind not in ('heatmap', 'line', 'histogram'):
            raise ValueError('Drawing kind must be heatmap, line or histogram')
        request = {'tool': tool, 'values': values, 'output': str(temp), 'kind': kind, 'title': clean_text(snapshot.name) + (' (sample)' if snapshot.fidelity != 'exact' else '')}
        try:
            code, stdout, _ = run_process([interpreter, '-E', '-P', '-X', 'utf8', str(Path(__file__).with_name('tool_worker.py'))],
                timeout=instance.budget_ms / 1000, cancel=cancel, input=json.dumps(request, allow_nan=False).encode())
            if code:
                raise RuntimeError('Drawing adapter failed')
            result = json.loads(stdout)
            if not temp.exists() or temp.stat().st_size > 8 * 1024 * 1024:
                raise ValueError('Drawing artifact exceeds byte budget')
            temp.replace(path)
            receipt = {'id': key, 'filename': path.name, 'mime': result['mime'], 'bytes': path.stat().st_size,
                'tool_id': tool, 'tool_version': version, 'snapshot_id': snapshot.id, 'fidelity': snapshot.fidelity}
            self.store.put('artifacts', key, receipt)
            return output.model_copy(update={'status': 'ready', 'artifact_id': key, 'cache_key': key, 'message': 'Rendered saved evidence', 'data': {**output.data, 'tool_id': tool}})
        finally:
            temp.unlink(missing_ok=True)

    def artifact(self, key):
        receipt = self.store.get('artifacts', key)
        path = (self.artifacts / receipt['filename']).resolve()
        if not path.is_relative_to(self.artifacts.resolve()) or not path.is_file():
            raise LookupError('Drawing artifact is unavailable')
        return path, receipt

    def close(self):
        if self._owns_pool:
            self.pool.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
