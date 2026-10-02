"""Public drawing catalog and project-owned optional environments."""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

from ...storage import atomic_write
from .process import run_process

PUBLIC_TOOLS = [
    ('matplotlib', 'Matplotlib', 'matplotlib>=3.8,<4', 'https://matplotlib.org/', 'implemented', 'PNG'),
    ('seaborn', 'Seaborn', 'seaborn>=0.13,<1', 'https://seaborn.pydata.org/', 'implemented', 'PNG'),
    ('plotly', 'Plotly', 'plotly>=5.24,<7', 'https://plotly.com/python/', 'implemented', 'HTML'),
    ('altair', 'Altair', 'altair>=5.4,<7', 'https://altair-viz.github.io/', 'implemented', 'Vega-Lite'),
    ('bokeh', 'Bokeh', 'bokeh>=3,<4', 'https://bokeh.org/', 'candidate', 'HTML'),
    ('pyvista', 'PyVista', 'pyvista>=0.44,<1', 'https://docs.pyvista.org/', 'candidate', '3D'),
    ('holoviews', 'HoloViews', 'holoviews>=1.19,<2', 'https://holoviews.org/', 'candidate', 'multiple'),
]


class ToolManager:
    discovery_code = "import json, importlib.metadata as m; print(json.dumps({d.metadata['Name'].lower().replace('_','-'):d.version for d in m.distributions() if d.metadata.get('Name')}))"

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.state = self.root / '.cdaf' / 'research'
        self.env = self.state / 'drawing-env'
        self.python = self.env / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        self.settings = self.state / 'drawing-tools.json'
        self._versions = {}
        self._interpreters = {}
        self._lock = threading.RLock()

    def _disabled(self):
        return json.loads(self.settings.read_text(encoding='utf-8')).get('disabled', []) if self.settings.exists() else []

    def catalog(self):
        disabled = self._disabled()
        return [{'id': key, 'label': label, 'package': package, 'url': url, 'adapter_status': adapter,
                 'format': fmt, 'available': key in self._versions, 'version': self._versions.get(key),
                 'interpreter': self._interpreters.get(key), 'enabled': key not in disabled,
                 'managed': self._interpreters.get(key) == str(self.python)}
                for key, label, package, url, adapter, fmt in PUBLIC_TOOLS]

    def scan(self, interpreter=None, *, cancel=None):
        selected = interpreter or sys.executable
        with self._lock:
            versions = {}
            interpreters = {}
            for executable in dict.fromkeys([selected, *([str(self.python)] if self.python.exists() else [])]):
                code, stdout, _ = run_process([executable, '-E', '-P', '-X', 'utf8', '-c', self.discovery_code], timeout=10, cancel=cancel)
                if code != 0:
                    raise ValueError('Interpreter metadata discovery failed')
                distributions = json.loads(stdout.decode('utf-8'))
                for key, *_ in PUBLIC_TOOLS:
                    if key in distributions:
                        versions[key] = distributions[key]
                        interpreters[key] = executable
            self._versions, self._interpreters = versions, interpreters
            return {'interpreter': selected, 'method': 'distribution-metadata', 'tools': self.catalog()}

    def _tool(self, key):
        for tool in PUBLIC_TOOLS:
            if tool[0] == key:
                return tool
        raise ValueError('Tool is not in the public package catalog')

    def install_command(self, key):
        tool = self._tool(key)
        return [str(self.python), '-X', 'utf8', '-m', 'pip', '--isolated', '--disable-pip-version-check', 'install', '--no-input', '--no-user', tool[2]]

    def install(self, key, *, cancel=None):
        self._tool(key)
        with self._lock:
            self.state.mkdir(parents=True, exist_ok=True)
            if not self.python.exists():
                code, _, _ = run_process([sys.executable, '-X', 'utf8', '-m', 'venv', str(self.env)], timeout=120, cancel=cancel)
                if code:
                    raise ValueError('Managed drawing environment creation failed')
            code, _, _ = run_process(self.install_command(key), timeout=300, cancel=cancel)
            if code:
                raise ValueError('Package installation failed; inspect the managed environment and retry explicitly')
            return self.scan(cancel=cancel)

    def disable(self, key, disabled=True):
        self._tool(key)
        with self._lock:
            keys = set(self._disabled())
            keys.add(key) if disabled else keys.discard(key)
            atomic_write(self.settings, json.dumps({'disabled': sorted(keys)}))
        return self.catalog()

    def remove(self, key, *, interpreter=None, cancel=None):
        self._tool(key)
        if interpreter is not None and Path(interpreter).absolute() != self.python.absolute():
            raise ValueError('Removal only supports this project’s managed drawing environment')
        with self._lock:
            if self.python.exists():
                code, _, _ = run_process([str(self.python), '-X', 'utf8', '-m', 'pip', 'uninstall', '-y', key], timeout=120, cancel=cancel)
                if code:
                    raise ValueError('Managed package removal failed')
            return self.scan(cancel=cancel)

    def resolve(self, key):
        self._tool(key)
        if key in self._disabled():
            raise ValueError('Drawing tool is disabled')
        if not self._versions:
            self.scan()
        if key not in self._interpreters:
            raise LookupError('Drawing tool is unavailable; install it in the managed environment')
        return self._interpreters[key], self._versions[key]
