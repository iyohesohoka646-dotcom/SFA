"""Frozen joint probes and immutable full-data operations in owned workers."""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path

from ..models import ObservationEvent, OperationRecord, SnapshotRef
from ..agent.privacy import clean_text
from .models import DerivedData, ProbeOutput, uid
from .process import run_process


class InputDiagnostic(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class DerivationService:
    def __init__(self, workbench):
        self.workbench = workbench
        self.store = workbench.research.store

    def artifact(self, snapshot):
        if snapshot.redacted:
            raise InputDiagnostic('redacted_input', '脱敏输入不能用于全量计算')
        if not snapshot.artifact_ref:
            code = 'input_budget_exceeded' if any(reason in snapshot.truncation for reason in ('artifact_byte_limit', 'run_byte_limit')) else 'full_data_not_captured'
            raise InputDiagnostic(code, '未保存完整输入；请为这些对象补采集并创建新运行')
        if not re.fullmatch(r'artifacts/[0-9a-f]{32}\.(npy|arrow)', snapshot.artifact_ref):
            raise InputDiagnostic('unsupported_artifact', '完整输入编码未注册')
        original = self.store.state/snapshot.artifact_ref
        path = original.resolve()
        if original.is_symlink() or path.parent != (self.store.state/'artifacts').resolve():
            raise InputDiagnostic('artifact_unavailable', '输入产物不属于证据存储')
        if not path.is_file():
            raise InputDiagnostic('artifact_expired', '完整输入已过期或缺失；需要重新采集')
        if path.stat().st_size > 64*1024*1024:
            raise InputDiagnostic('input_budget_exceeded', '完整输入超过单产物预算')
        receipt_path = path.with_suffix(path.suffix+'.meta.json')
        if receipt_path.exists():
            receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
            if receipt.get('bytes') != path.stat().st_size:
                raise InputDiagnostic('artifact_changed', '产物长度与保存记录不一致')
            if receipt.get('metadata', {}).get('redacted'):
                raise InputDiagnostic('redacted_input', '完整产物包含脱敏内容')
            checksum = receipt['sha256']
        else:
            # Legacy numeric full artifacts retain positional semantics; legacy
            # tables still require complete coordinate metadata inside Arrow.
            hasher = hashlib.sha256()
            with path.open('rb') as stream:
                while chunk := stream.read(1024*1024):
                    hasher.update(chunk)
            checksum = hasher.hexdigest()
        return {'path': str(path), 'sha256': checksum, 'shape': snapshot.descriptor.shape, 'bytes': path.stat().st_size}

    def execute(self, invocation, run_id, plan, cancel):
        started = time.perf_counter()
        definition, instance = invocation.definition, invocation.instance
        base = dict(instance_id=instance.id, definition_id=definition.id, capability=definition.capability, execution=definition.execution,
            run_id=run_id, analysis_id=plan.analysis_id, invocation_id=invocation.id, targets=invocation.targets,
            parent_snapshot_ids=[target.snapshot_id for target in invocation.targets if target.snapshot_id])
        if definition.id == 'view.compare':
            return ProbeOutput(**base, status='ready', fidelity='sampled', provenance='declared', message='独立输入比较',
                data={'renderer': 'compare', 'inputs': {role: target.model_dump(mode='json') for role, target in invocation.inputs.items()},
                    'parameters': instance.parameters, 'numeric_conclusion': False})
        parents = []
        try:
            if not invocation.inputs or any(not target.snapshot_id for target in invocation.inputs.values()):
                raise InputDiagnostic('full_data_not_captured', '联合运算需要明确的数据版本')
            parents = [self.store.snapshot(target.snapshot_id) for target in invocation.inputs.values()]
            if len({snapshot.run_id for snapshot in parents}) > 1 and not instance.parameters.get('allow_cross_run', False):
                raise InputDiagnostic('cross_run_confirmation_required', '跨运行输入需要明确开启比较')
            specs = {role: self.artifact(snapshot) for role, snapshot in zip(invocation.inputs, parents)}
            for role, target in invocation.inputs.items():
                specs[role]['semantics'] = invocation.semantics.get(target.logical_key, {})
            if sum(spec['bytes'] for spec in specs.values()) > 256*1024*1024:
                raise InputDiagnostic('input_budget_exceeded', '联合输入超过总预算')
            self.store.retain_artifacts([snapshot.id for snapshot in parents], 'active:'+invocation.id, minutes=60)
            request = {'inputs': specs, 'operator': definition.id.removeprefix('derive.'), 'parameters': instance.parameters,
                'maximum': 64*1024*1024, 'state': str(self.store.state), 'run_id': run_id,
                'name': definition.id.removeprefix('derive.') + '_' + uid(), 'parents': [snapshot.id for snapshot in parents]}
            interpreter = plan.config.interpreter or sys.executable
            code, stdout, _ = run_process([interpreter, '-E', '-P', '-X', 'utf8', str(Path(__file__).with_name('joint_worker.py'))],
                timeout=instance.budget_ms/1000, cancel=cancel, input=json.dumps(request, allow_nan=False).encode('utf-8'))
            if code:
                raise InputDiagnostic('worker_failed', '联合运算工作进程退出')
            response = json.loads(stdout)
            if response['status'] != 'ready':
                return ProbeOutput(**base, status='error', message=clean_text(response['message']), data={'diagnostic_code': response['code']}, duration_ms=(time.perf_counter()-started)*1000)
            snapshot = SnapshotRef.model_validate(response['snapshot'])
            if snapshot.run_id != run_id or snapshot.parents != request['parents'] or not snapshot.artifact_ref:
                raise InputDiagnostic('worker_evidence_mismatch', '工作进程返回的证据与冻结输入不一致')
            if cancel.is_set():
                self._remove_result(snapshot)
                raise InterruptedError('Task cancelled')
            derived_id = uid()
            operation = OperationRecord(id=derived_id, run_id=run_id, label=definition.label, scope_id='derived',
                input_snapshots=request['parents'], output_snapshots=[snapshot.id], kind=definition.id, status='completed',
                duration_ms=(time.perf_counter()-started)*1000, parameters=instance.parameters, provenance='declared')
            snapshot.operation_id = operation.id
            self.store.append([ObservationEvent(run_id=run_id, kind='operation.finished', operation_id=operation.id, payload={'operation': operation.model_dump(mode='json')}),
                ObservationEvent(run_id=run_id, kind='value.observed', snapshot_id=snapshot.id, operation_id=operation.id, payload={'snapshot': snapshot.model_dump(mode='json')})])
            derived = DerivedData(id=derived_id, snapshot_id=snapshot.id, run_id=run_id, invocation_id=invocation.id,
                operator=definition.id, parents=invocation.targets, inputs=invocation.inputs, parameters=instance.parameters,
                input_digests={role: spec['sha256'] for role, spec in specs.items()})
            self.store.retain_artifacts([snapshot.id], 'derived:'+derived.id)
            self.workbench.store.put('derived', derived.id, derived)
            return ProbeOutput(**base, status='ready', snapshot_id=snapshot.id, fidelity='exact', provenance='declared',
                message='已保存可追溯的派生数据', duration_ms=operation.duration_ms,
                data={'derived_id': derived.id, 'derived_snapshot_id': snapshot.id, 'statistics': response.get('statistics', {}),
                    'operator': definition.id, 'parameters': instance.parameters, 'complete_inputs': True})
        except InputDiagnostic as error:
            return ProbeOutput(**base, status='unknown', message=str(error), data={'diagnostic_code': error.code}, duration_ms=(time.perf_counter()-started)*1000)
        except InterruptedError:
            return ProbeOutput(**base, status='cancelled', message='联合运算已取消')
        except TimeoutError:
            return ProbeOutput(**base, status='error', message='联合运算超时', data={'diagnostic_code': 'worker_timeout'})
        finally:
            self.store.release_artifacts('active:'+invocation.id)

    def _remove_result(self, snapshot):
        if snapshot.artifact_ref and re.fullmatch(r'artifacts/[0-9a-f]{32}\.(npy|arrow)', snapshot.artifact_ref):
            path = self.store.state/snapshot.artifact_ref
            path.unlink(missing_ok=True)
            path.with_suffix(path.suffix+'.meta.json').unlink(missing_ok=True)
