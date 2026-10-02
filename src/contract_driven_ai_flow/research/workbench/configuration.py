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
        config = WorkbenchConfig(protocol_version=2, script=old.get('script', ''), interpreter=old.get('interpreter') or sys.executable,
            arguments=old.get('arguments', []), probes=probes, adapters=old.get('adapters', []))
        result = {'config': config.model_dump(mode='json'), 'issues': issues, 'applied': False}
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
