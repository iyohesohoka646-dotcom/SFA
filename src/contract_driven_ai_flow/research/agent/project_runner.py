"""P2a project-local multi-file observation runner.

The entry module and every indexed, in-root standard source module are traced
through one shared TraceSession. Only the standard ``SourceFileLoader`` is
wrapped, and only for files present in the supplied manifest: stdlib, third
party and custom loaders keep their normal behaviour and are reported through
explicit coverage instead.

Every file the interpreter actually enters is recorded in a bounded ledger so a
project run can publish a durable, root-relative receipt of what was loaded.
Unused manifest files are never counted; empty modules still are.
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


class LoadedFileLedger:
    """Bounded ledger of files actually entered by the project interpreter.

    Rows are keyed by root-relative path, so repeated execution of one module
    updates a single entry (with a per-file count) instead of inflating the
    receipt. Indexed manifest files are always tracked, while a small budget
    covers unindexed in-root loads so a coverage gap is explicit rather than
    silently absent. Drops past that budget are counted as omitted.
    """

    MAX_UNKNOWN = 64

    def __init__(self, root, manifest):
        self.root = Path(root).resolve()
        self.manifest = manifest or {}
        self._rows: dict = {}
        self.omitted = 0
        self.unknown_boundary = 0

    def _relative(self, path):
        try:
            resolved = str(Path(path).resolve())
            relative = Path(resolved).relative_to(self.root).as_posix()
        except (ValueError, OSError):
            return None, None
        return clean_text(relative, 4096), resolved

    def record(self, path, *, state, coverage, module_name=None):
        relative, resolved = self._relative(path)
        if relative is None:
            # Stdlib, third-party and out-of-root files stay outside the receipt.
            return None
        name = clean_text(module_name, 256) if module_name else ""
        row = self._rows.get(relative)
        if row is not None:
            row["state"] = state
            row["coverage"] = coverage
            if name:
                row["module_name"] = name
            # ``count`` means actual executions: only *entering* a module adds an
            # execution, while the entered->completed/failed transitions merely
            # update state. A cached re-import therefore stays at one, whereas a
            # genuine re-execution (e.g. importlib.reload) increments again.
            if state == "entered":
                row["count"] = row.get("count", 0) + 1
            return row
        info = self.manifest.get(resolved)
        if info is None:
            if self.unknown_boundary >= self.MAX_UNKNOWN:
                self.omitted += 1
                return None
            self.unknown_boundary += 1
            digest = ""
            try:
                digest = read_source(Path(resolved)).digest
            except (OSError, ValueError):
                digest = ""
            row = {
                "path": relative,
                "file_id": "",
                "digest": digest,
                "project_id": "",
                "project_revision_id": "",
                "module_name": name,
                "state": state,
                "coverage": coverage,
                "count": 1,
            }
        else:
            row = {
                "path": relative,
                "file_id": info.get("file_id", ""),
                "digest": info.get("digest", ""),
                "project_id": info.get("project_id", ""),
                "project_revision_id": info.get("project_revision_id", ""),
                "module_name": name,
                "state": state,
                "coverage": coverage,
                "count": 1,
            }
        self._rows[relative] = row
        return row

    def rows(self):
        return [dict(row) for row in self._rows.values()]

    def coverage_summary(self):
        counts = {"supported": 0, "unsupported": 0, "partial": 0}
        for row in self._rows.values():
            counts[row["coverage"]] = counts.get(row["coverage"], 0) + 1
        counts["unknown_boundary"] = self.unknown_boundary
        return counts


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
        self.ledger = LoadedFileLedger(self.root, self.manifest)
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

    def in_root(self, path):
        return _under(self.root, path)

    @staticmethod
    def _module_name(module):
        return getattr(module, "__name__", "") or ""

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

    def _tracked(self, source, module, state):
        return self.ledger.record(
            source.path,
            state=state,
            coverage="supported",
            module_name=self._module_name(module),
        )

    def exec_module(self, path, module):
        source, info = self.load(path)
        # Entered BEFORE any user code runs; digest already verified in load().
        self._tracked(source, module, "entered")
        try:
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
        except BaseException:
            self._tracked(source, module, "failed")
            raise
        self._tracked(source, module, "completed")
        self.traced.append(source.path)

    def exec_entry_script(self, path, arguments):
        source, info = self.load(path)
        module = ModuleType("__main__")
        module.__dict__.update(__file__=source.path, __package__=None, __spec__=None)
        self._tracked(source, module, "entered")
        sys.modules["__main__"] = module
        sys.argv = [source.path, *arguments]
        sys.path.insert(0, str(Path(source.path).parent))
        try:
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
                module_scope="main",
                finalize_controls=False,
                runtimes=self.runtimes,
                controls=self.controls,
            )
        except BaseException:
            self._tracked(source, module, "failed")
            raise
        self._tracked(source, module, "completed")
        self.traced.append(source.path)

    def exec_untracked(self, path, module, original, loader_self):
        """Actual in-root load that is not part of the frozen manifest.

        The file is still executed normally by the standard loader; only its
        boundary is recorded, never a fabricated frozen membership.
        """
        name = self._module_name(module)
        self.ledger.record(path, state="entered", coverage="unsupported", module_name=name)
        try:
            result = original(loader_self, module)
        except BaseException:
            self.ledger.record(path, state="failed", coverage="unsupported", module_name=name)
            raise
        self.ledger.record(path, state="completed", coverage="unsupported", module_name=name)
        return result

    def exec_custom(self, path, module, original, loader_self):
        """A custom loader executed unchanged; its unsupported boundary is explicit."""
        name = self._module_name(module)
        self.ledger.record(path, state="entered", coverage="unsupported", module_name=name)
        try:
            result = original(loader_self, module)
        except BaseException:
            self.ledger.record(path, state="failed", coverage="unsupported", module_name=name)
            raise
        self.ledger.record(path, state="completed", coverage="unsupported", module_name=name)
        return result

    # -- durable receipt ----------------------------------------------
    def project_identity(self):
        for info in self.manifest.values():
            if info.get("project_id"):
                return info.get("project_id", ""), info.get("project_revision_id", "")
        return "", ""

    def emit_loaded_files(self, session):
        """Critical, paged project.files packets from the actual ledger."""
        project_id, revision_id = self.project_identity()
        rows = self.ledger.rows()
        batches = [rows[offset:offset + 16] for offset in range(0, len(rows), 16)]
        for index, batch in enumerate(batches):
            session.emit(
                "project.files",
                {
                    "project_id": project_id,
                    "project_revision_id": revision_id,
                    "batch": index,
                    "batches": len(batches),
                    "omitted_count": self.ledger.omitted,
                    "files": batch,
                },
                critical=True,
            )
        return len(batches)

    def build_receipt(self, complete, *, summary_limit=128):
        project_id, revision_id = self.project_identity()
        rows = self.ledger.rows()
        summary = rows[:summary_limit]
        return {
            "project_id": project_id,
            "project_revision_id": revision_id,
            "loaded_count": len(rows),
            "loaded_files": summary,
            "omitted_from_summary": max(0, len(rows) - len(summary)),
            "omitted_count": self.ledger.omitted,
            "complete": bool(complete) and self.ledger.omitted == 0,
            "coverage": self.ledger.coverage_summary(),
        }


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
                runtime.exec_custom(path, module, original, self)
                return None
            return original(self, module)
        if path is not None and runtime.traces(path):
            runtime.exec_module(path, module)
            return None
        if path is not None and runtime.in_root(path):
            # Real in-root load outside the frozen manifest: a coverage gap.
            return runtime.exec_untracked(path, module, original, self)
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
    flush_failed = False
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
        status, code = "failed", 1
        details = {"error_type": type(error).__name__, "frames": frames}
        try:
            session.emit(
                "analysis.error",
                {**details, "message": clean_text(str(error), 4096)},
                critical=True,
            )
        except Exception as observer_error:
            flush_failed = True
            details["observer_error"] = "analysis_error_delivery:" + type(observer_error).__name__
    finally:
        # Project runtimes finalize controls only once, after every module ran.
        # Each observation step lives in its own error-aware boundary so a
        # faulting observer can never skip process-state restoration, the loaded
        # receipt, or the terminal run.finished event. The program outcome is
        # preserved and is never silently upgraded to complete/pass.
        collectors = []
        for instance in runtime.runtimes:
            if all(instance.controls is not seen for seen in collectors):
                collectors.append(instance.controls)
        succeeded = status == "completed"
        observer_failed = flush_failed
        try:
            for collector in collectors:
                collector.flush(final=True, succeeded=succeeded, receipt=False)
            if collectors:
                collectors[0].emit_receipt(
                    succeeded=succeeded,
                    failed=any(collector.failed for collector in collectors),
                    node_count=sum(len(c.summaries) for c in collectors),
                    omitted=sum(c.omitted for c in collectors),
                )
        except BaseException:
            observer_failed = True
        # The durable actual-load ledger is emitted independently of controls so
        # a control observer fault cannot suppress the project.files batches.
        try:
            if runtime.coverage.entries:
                session.emit(
                    "coverage.report",
                    {"entries": runtime.coverage.entries},
                    critical=True,
                )
            runtime.emit_loaded_files(session)
        except BaseException:
            observer_failed = True
        # Restore interpreter state unconditionally before finishing the trace.
        try:
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
        except BaseException:
            observer_failed = True
        complete = status != "cancelled" and not observer_failed
        receipt = runtime.build_receipt(complete)
        session.finish(status, **details, project_execution=receipt)
    return code
