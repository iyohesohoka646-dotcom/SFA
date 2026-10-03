"""Explicit runner protocol v1; supervisors retain process/evidence ownership."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Protocol


class RunnerAdapter(Protocol):
    protocol_version: int
    backend: str
    capabilities: tuple[str, ...]

    def launch(self, job: dict, job_file: Path) -> subprocess.Popen: ...


class PythonRunner:
    protocol_version = 1
    backend = "python"
    capabilities = ("python-script", "native-observation", "boundary-control")

    def launch(self, job, job_file):
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        bootstrap = Path(__file__).parent / "agent/bootstrap.py"
        return subprocess.Popen([job["interpreter"], "-X", "utf8", str(bootstrap), str(job_file)],
            cwd=str(Path(job["script"]).parent), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            start_new_session=os.name != "nt")


class RunnerRegistry:
    def __init__(self):
        self._runners = {"python": PythonRunner()}

    def register(self, runner):
        if getattr(runner, "protocol_version", None) != 1 or not callable(getattr(runner, "launch", None)):
            raise ValueError("Runner must implement protocol v1 and launch")
        if type(runner.backend) is not str or not runner.backend or len(runner.backend) > 256:
            raise ValueError("Runner backend must be a bounded identifier")
        if runner.backend in self._runners:
            raise ValueError("Runner backend is already registered")
        self._runners[runner.backend] = runner

    def enable(self, names):
        if not names:
            return
        from importlib.metadata import entry_points
        available = {e.name: e for e in entry_points(group="cdaf.research.runners")}
        for name in names:
            if name not in available:
                raise ValueError("Unknown explicitly enabled runner: " + name)
            self.register(available[name].load()())

    def resolve(self, backend):
        if backend not in self._runners:
            raise ValueError("Unknown scientific runner: " + backend)
        return self._runners[backend]

    def types(self):
        return [{"backend": r.backend, "protocol_version": 1, "capabilities": list(r.capabilities)} for r in self._runners.values()]
