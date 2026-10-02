"""Authored configuration is separate from observations and caches."""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import yaml

from ...storage import atomic_write
from .models import ProbeInstance, WorkbenchConfig

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


class ConfigurationStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.path = self.root / 'workbench.yaml'
        with _locks_guard:
            self._lock = _locks.setdefault(str(self.path), threading.RLock())

    def load(self) -> WorkbenchConfig:
        with self._lock:
            if not self.path.exists():
                return WorkbenchConfig(interpreter=sys.executable)
            return WorkbenchConfig.model_validate(yaml.safe_load(self.path.read_text(encoding='utf-8')))

    def save(self, config: WorkbenchConfig, *, expected_revision: int) -> WorkbenchConfig:
        with self._lock:
            current = self.load()
            if current.revision != expected_revision:
                raise ValueError('Configuration revision conflict; reload before saving')
            updated = config.model_copy(deep=True, update={'revision': current.revision + 1})
            atomic_write(self.path, yaml.safe_dump(updated.model_dump(mode='json'), allow_unicode=True, sort_keys=False))
            return updated

    def migrate_legacy(self, *, apply=False):
        legacy = self.root / 'research.yaml'
        raw = legacy.read_text(encoding='utf-8')
        old = yaml.safe_load(raw) or {}
        issues = []
        probes = []
        for item in old.get('probes', []):
            kind = item.get('kind', 'finite')
            if kind == 'router':
                kind = 'branch-observer'
                issues.append('Router retained as an observer, not executable routing')
            probes.append(ProbeInstance(id=item['id'], definition_id='check.' + kind,
                binding=item.get('binding', '*'), enabled=item.get('enabled', True),
                parameters=item.get('parameters', {}), policy=item.get('policy', 'continue'),
                budget_ms=item.get('budget_ms', 50)))
        config = WorkbenchConfig(protocol_version=3, script=old.get('script', ''), interpreter=old.get('interpreter') or sys.executable,
            arguments=old.get('arguments', []), probes=probes, adapters=old.get('adapters', []))
        pending, binding_issues = self._resolve_legacy_bindings(config)
        result = {'config': config.model_dump(mode='json'), 'issues': issues + binding_issues, 'pending_rebind':pending, 'applied': False}
        if apply:
            if self.path.exists():
                raise ValueError('workbench.yaml already exists; migration will not overwrite it')
            backup = legacy.with_name(legacy.name + '.v1.bak')
            if not backup.exists():
                # Preserve exact bytes, including the original newline convention.
                atomic_write(backup, legacy.read_bytes())
            config = self.save(config, expected_revision=0)
            result.update(config=config.model_dump(mode='json'), applied=True)
        return result

    def migrate_v2(self, *, apply=False):
        """Keep authored deletion and exact bytes; ambiguities require rebinding."""
        from fnmatch import fnmatchcase
        from .analysis import analyze_source
        from .semantic_models import ScopeSelector,TargetRef
        with self._lock:
            raw=self.path.read_bytes();old=yaml.safe_load(raw.decode('utf-8-sig'))
            if old.get('protocol_version',2)==3:return {'applied':False,'pending_rebind':[],'issues':[],'config':self.load().model_dump(mode='json')}
            config=WorkbenchConfig.model_validate(old)
            pending, issues = self._resolve_legacy_bindings(config)
            config.protocol_version=3
            result={'applied':False,'pending_rebind':pending,'issues':issues,'config':config.model_dump(mode='json')}
            if apply:
                backup=self.path.with_name(self.path.name+'.v2.bak')
                if backup.exists() and backup.read_bytes()!=raw:raise ValueError('Migration backup already belongs to another revision')
                if not backup.exists():atomic_write(backup,raw)
                updated=self.save(config,expected_revision=config.revision)
                result.update(applied=True,config=updated.model_dump(mode='json'))
            return result

    def _resolve_legacy_bindings(self, config):
        from fnmatch import fnmatchcase
        from .analysis import analyze_source
        from .semantic_models import ScopeSelector, TargetRef
        script = Path(config.script)
        if not script.is_absolute():
            script = self.root / script
        analysis = analyze_source(script) if script.is_file() else None
        pending, issues = [], []
        for probe in config.probes:
            if probe.definition_id == 'check.branch-observer':
                probe.enabled = False
                pending.append(probe.id)
                issues.append('Legacy branch observer needs a reviewed resource and target')
            if probe.selector is not None:
                continue
            if probe.binding == '*':
                probe.selector = ScopeSelector()
                continue
            matches = [o for o in analysis.objects if o.kind not in ('import', 'class') and
                       (fnmatchcase(o.name, probe.binding) or fnmatchcase(o.qualname, probe.binding))] if analysis else []
            by_key = {o.logical_key:o for o in matches}
            if len(by_key) == 1:
                o = next(iter(by_key.values()))
                probe.selector = ScopeSelector(mode='selection', targets=[TargetRef(
                    kind='function' if o.kind == 'function' else 'data', logical_key=o.logical_key,
                    object_id=o.id, block_id=o.block_id, analysis_id=analysis.id)])
            else:
                probe.enabled = False
                probe.selector = ScopeSelector(mode='selection', targets=[])
                if probe.id not in pending:
                    pending.append(probe.id)
                issues.append(f'Probe {probe.id} needs an explicit target; {len(by_key)} matches')
        return pending, issues
