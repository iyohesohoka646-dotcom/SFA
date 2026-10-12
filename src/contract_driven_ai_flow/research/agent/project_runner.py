"""P2a project-local multi-file observation runner.

The entry module and every indexed, in-root standard source module are traced
through one shared TraceSession. Only the standard ``SourceFileLoader`` is
wrapped, and only for files present in the supplied manifest: stdlib, third
party and custom loaders keep their normal behaviour and are reported through
explicit coverage instead.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import sys
import traceback
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

from .instrument import InstrumentPolicy, instrument
from .privacy import clean_text
from .source import read_source

_MISSING = object()


def project_source(info):
    """Optional P1 project metadata stamped onto compiled source references."""
    return {
        "project_id": info.get("project_id"),
        "file_id": info.get("file_id"),
        "project_revision_id": info.get("project_revision_id"),
    }


def module_scope(info, path):
    """A distinct global binding scope per indexed module, mapped to ``<module>``."""
    identifier = info.get("file_id") or info.get("digest") or Path(path).name
    return "<module>:" + str(identifier)


def _under(root, path):
    try:
        Path(path).resolve().relative_to(root)
        return True
    except (ValueError, OSError):
        return False


class ProjectRuntime:
    def __init__(self, root, session, manifest, policy):
        self.root = Path(root).resolve()
        self.session = session
        self.manifest = {
            str(Path(key).resolve()): dict(value) for key, value in (manifest or {}).items()
        }
        self.policy = policy or InstrumentPolicy()
        self.allowed = {
            str(Path(item).resolve()) for item in self.policy.allowed_files
        }
        self.runtimes = []
        self.traced = []
        from .control_observation import ControlCollector
        from .instrument import CoverageReport

        self.coverage = CoverageReport()
        # P2a: exactly one control collector per project run, shared by every
        # module runtime so the detail budget and summary node budget are bounded
        # and finalised across the whole run rather than once per module.
        self.controls = ControlCollector(
            session, detail_limit=session.policy.max_control_details
        )

    # -- selection ----------------------------------------------------
    def traces(self, path):
        resolved = str(Path(path).resolve())
        return (
            resolved in self.manifest
            and _under(self.root, resolved)
            and (not self.allowed or resolved in self.allowed)
        )

    def load(self, path):
        """Read and digest-check a traced source immediately before compiling."""
        resolved = str(Path(path).resolve())
        info = self.manifest.get(resolved)
        if info is None:
            raise RuntimeError(
                "Entry source is not part of the indexed project manifest; index the project first"
            )
        source = read_source(Path(resolved))
        expected = info.get("digest")
        if expected is not None and source.digest != expected:
            raise RuntimeError(
                "Analysis source changed before execution; start a new run"
            )
        return source, info

    def exec_module(self, path, module):
        source, info = self.load(path)
        compiled = instrument(
            source.text,
            source.path,
            self.policy,
            source_digest=source.digest,
            project=project_source(info),
        )
        compiled.execute(
            self.session,
            module.__dict__,
            module_scope=module_scope(info, path),
            finalize_controls=False,
            runtimes=self.runtimes,
            controls=self.controls,
        )
        self.traced.append(source.path)

    def exec_entry_script(self, path, arguments):
        source, info = self.load(path)
        compiled = instrument(
            source.text,
            source.path,
            self.policy,
            source_digest=source.digest,
            project=project_source(info),
        )
        module = ModuleType("__main__")
        module.__dict__.update(__file__=source.path, __package__=None, __spec__=None)
        sys.modules["__main__"] = module
        sys.argv = [source.path, *arguments]
        sys.path.insert(0, str(Path(source.path).parent))
        compiled.execute(
            self.session,
            module.__dict__,
            module_scope="main",
            finalize_controls=False,
            runtimes=self.runtimes,
            controls=self.controls,
        )
        self.traced.append(source.path)


@contextmanager
def source_loader_hook(runtime):
    """Wrap only the standard source loader; every other loader is untouched."""
    loader = importlib.machinery.SourceFileLoader
    original = loader.exec_module

    def exec_module(self, module):
        path = getattr(module, "__file__", None)
        if type(self) is not loader:
            # Custom loader subclasses keep their own execution semantics; the
            # boundary is reported instead of being silently instrumented.
            if path is not None and runtime.traces(path):
                runtime.coverage.add(
                    "custom-loader",
                    "unsupported",
                    message="Manifest file loaded by a non-standard loader; executed unchanged",
                )
            return original(self, module)
        if path is not None and runtime.traces(path):
            runtime.exec_module(path, module)
            return None
        return original(self, module)

    loader.exec_module = exec_module
    try:
        yield
    finally:
        loader.exec_module = original


def module_entry(target):
    """runpy-style resolution: packages run their ``__main__`` submodule."""
    if target.startswith("."):
        raise ValueError("Relative module entry targets are not supported")
    spec = importlib.util.find_spec(target)
    if spec is None:
        raise ImportError(f"No module named {target}")
    if spec.submodule_search_locations is not None:
        child = target + ".__main__"
        spec = importlib.util.find_spec(child)
        if spec is None:
            raise ImportError(f"No module named {child}")
        return child, target, spec
    return target, target.rpartition(".")[0], spec


def run_module_entry(runtime, target, arguments):
    name, package, spec = module_entry(target)
    if not spec.origin or not spec.origin.endswith(".py"):
        raise RuntimeError(f"Module entry {name} is not a standard Python source file")
    module = ModuleType("__main__")
    module.__dict__.update(
        __name__="__main__",
        __file__=spec.origin,
        __package__=package,
        __spec__=spec,
        __loader__=spec.loader,
        __cached__=spec.cached,
    )
    sys.argv = [spec.origin, *arguments]
    sys.modules["__main__"] = module
    runtime.exec_module(spec.origin, module)


def project_frames(error, root, manifest):
    known = {str(Path(key).resolve()) for key in manifest}
    frames = []
    for frame in traceback.extract_tb(error.__traceback__):
        if frame.filename in known or _under(root, frame.filename):
            frames.append(
                {
                    "path": clean_text(frame.filename, 4096),
                    "line": frame.lineno,
                    "name": clean_text(frame.name),
                    "code": clean_text(frame.line or "", 4096),
                }
            )
    return frames


def run_project(project_root, entry, *, session, manifest, arguments=(), policy=None, cwd=None) -> int:
    """Execute an indexed project entry with cross-file observation."""
    root = Path(project_root).resolve()
    kind = (entry or {}).get("kind")
    target = (entry or {}).get("target")
    if kind not in ("script", "module") or not isinstance(target, str) or not target:
        raise ValueError("entry must be {'kind': 'script'|'module', 'target': <str>}")
    runtime = ProjectRuntime(root, session, manifest, policy)
    original = {
        "cwd": os.getcwd(),
        "path": list(sys.path),
        "argv": list(sys.argv),
        "main": sys.modules.get("__main__", _MISSING),
        "modules": set(sys.modules),
    }
    status, code, details = "completed", 0, {}
    try:
        working = Path(cwd).resolve() if cwd is not None else root
        os.chdir(working)
        with source_loader_hook(runtime):
            if kind == "script":
                path = Path(target)
                runtime.exec_entry_script(
                    path if path.is_absolute() else root / path, arguments
                )
            else:
                sys.path.insert(0, str(working))
                run_module_entry(runtime, target, arguments)
    except KeyboardInterrupt:
        status, code = "cancelled", 130
    except SystemExit as error:
        code = error.code if type(error.code) is int else (0 if error.code is None else 1)
        status = "completed" if code == 0 else "failed"
        details = {"exit_code": code}
    except BaseException as error:
        frames = project_frames(error, root, runtime.manifest)
        session.emit(
            "analysis.error",
            {
                "error_type": type(error).__name__,
                "message": clean_text(str(error), 4096),
                "frames": frames,
            },
            critical=True,
        )
        status, code = "failed", 1
        details = {"error_type": type(error).__name__, "frames": frames}
    finally:
        # Project runtimes finalize controls only once, after every module ran.
        collectors = []
        for instance in runtime.runtimes:
            if all(instance.controls is not seen for seen in collectors):
                collectors.append(instance.controls)
        succeeded = status == "completed"
        for collector in collectors:
            collector.flush(final=True, succeeded=succeeded, receipt=False)
        if collectors:
            collectors[0].emit_receipt(
                succeeded=succeeded,
                failed=any(collector.failed for collector in collectors),
                node_count=sum(len(c.summaries) for c in collectors),
                omitted=sum(c.omitted for c in collectors),
            )
        if runtime.coverage.entries:
            session.emit(
                "coverage.report",
                {"entries": runtime.coverage.entries},
                critical=True,
            )
        os.chdir(original["cwd"])
        sys.path[:] = original["path"]
        sys.argv = original["argv"]
        if original["main"] is _MISSING:
            sys.modules.pop("__main__", None)
        else:
            sys.modules["__main__"] = original["main"]
        for name in list(sys.modules):
            if name in original["modules"]:
                continue
            module = sys.modules.get(name)
            path = getattr(module, "__file__", None)
            locations = list(getattr(module, "__path__", None) or ())
            if path and _under(root, path):
                sys.modules.pop(name, None)
            elif locations and all(_under(root, item) for item in locations):
                # Namespace packages have no __file__ but must not leak either.
                sys.modules.pop(name, None)
        session.finish(status, **details)
    return code