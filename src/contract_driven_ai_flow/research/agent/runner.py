"""Native Python runner and binding hooks; no global numerical monkey-patches."""
from __future__ import annotations

import contextvars
import sys
import time
import traceback
import uuid
import weakref
from contextlib import contextmanager
from pathlib import Path
from types import BuiltinFunctionType, FunctionType, ModuleType

from .instrument import InstrumentPolicy, instrument
from .privacy import clean_text
from .source import read_source


class ObservationRuntime:
    def __init__(self, session, references):
        self.session = session
        self.references = references
        self._iterations = {}
        self._active = contextvars.ContextVar("research_statement", default=None)
        self._frames = contextvars.ContextVar("research_scope_frames", default=())
        self._array_refs = {}

    @staticmethod
    def values(frame, names):
        result = {}
        local, global_values = frame.f_locals, frame.f_globals
        lexical = set(frame.f_code.co_varnames) | set(frame.f_code.co_cellvars) | set(frame.f_code.co_freevars)
        for name in names:
            if name in local:
                value = local[name]
            elif name not in lexical and name in global_values:
                value = global_values[name]
            else:
                continue
            if isinstance(value, (ModuleType, FunctionType, BuiltinFunctionType)):
                continue
            result[name] = value
        return result

    def owner(self, frame, name):
        if frame.f_locals is frame.f_globals:
            return "main"
        code = frame.f_code
        if name in code.co_varnames or name in code.co_cellvars:
            return self.session._scope.get()
        if name in code.co_freevars:
            for scope_id, declared in reversed(self._frames.get()[:-1]):
                if name in declared:
                    return scope_id
            return self.session._scope.get()
        return "main"

    def remember_array(self, owner, name, value):
        np = sys.modules.get("numpy")
        if np is not None and isinstance(value, np.ndarray):
            self._array_refs[(owner, name)] = weakref.ref(value)

    def input_observation(self, owner, name, value, source):
        binding = owner + ":" + name
        observed = self.session._latest.get(binding)
        if observed is None or self.session._objects.get(binding) != id(value):
            token = self.session._current.set(None)
            try:
                with self.session.scope(owner):
                    observed = self.session.watch(name, value, source=source)
            finally:
                self.session._current.reset(token)
        self.remember_array(owner, name, value)
        return observed

    def step(self, identifier, names):
        # Read the caller before contextlib enters its own generator frame.
        frame = sys._getframe(1)
        inputs = self.values(frame, names)
        reference = self.references[identifier]
        observed = [self.input_observation(self.owner(frame, name), name, value, reference["source"]) for name, value in inputs.items()]
        key = (self.session._scope.get(), identifier)
        self._iterations[key] = self._iterations.get(key, 0) + 1
        context = self.session.operation(reference["source"]["code"], inputs={}, input_snapshots=[s["id"] for s in observed], source=reference["source"],
            kind=reference["kind"], provenance="inferred", iteration=self._iterations[key])

        @contextmanager
        def managed():
            with context as record:
                token = self._active.set((record, time.perf_counter(), tuple(s["id"] for s in observed)))
                try:
                    yield
                finally:
                    self._active.reset(token)
        return managed()

    def after(self, identifier, names):
        active = self._active.get()
        if active:
            record, started, parents = active
            record["duration_ms"] = (time.perf_counter() - started) * 1000
            record["parameters"]["timing"] = "statement-only"
        else:
            parents = ()
        frame = sys._getframe(1)
        values = self.values(frame, names)
        reference = self.references[identifier]
        updated = set()
        for name, value in values.items():
            owner = self.owner(frame, name)
            with self.session.scope(owner):
                self.session.watch(name, value, source=reference["source"], parent_snapshots=parents, provenance="inferred",
                    coverage={"mode": "auto", "binding": "observed", "dependency": "inferred", "hidden_mutations": "not_observed"})
            self.remember_array(owner, name, value)
            updated.add((owner, name))
        if reference["kind"] in ("mutation", "inplace"):
            self.refresh_aliases(updated, values.values(), reference["source"])

    def refresh_aliases(self, updated, values, source):
        np = sys.modules.get("numpy")
        if np is None:
            return
        targets = [np.ndarray.view(v, np.ndarray) for v in values if isinstance(v, np.ndarray)]
        if not targets:
            return
        candidates = list(self._array_refs.items())
        if len(candidates) > 256:
            self.session.emit("coverage.limited", {"kind": "alias-refresh", "limit": 256, "candidates": len(candidates)}, critical=True)
        for (owner, name), ref in candidates[:256]:
            if (owner, name) in updated:
                continue
            value = ref()
            if value is None:
                self._array_refs.pop((owner, name), None)
                continue
            try:
                aliased = any(np.shares_memory(np.ndarray.view(value, np.ndarray), target, max_work=1000) for target in targets)
            except np.exceptions.TooHardError:
                self.session.emit("coverage.limited", {"kind": "alias-refresh", "binding": owner + ":" + name, "reason": "overlap_budget"}, critical=True)
                continue
            if aliased:
                parents = [self.session._latest[o + ":" + n]["id"] for o, n in updated]
                with self.session.scope(owner):
                    self.session.watch(name, value, source=source, parent_snapshots=parents, provenance="observed",
                        coverage={"mode": "auto", "alias_update": "observed", "hidden_mutations": "not_observed"})

    def function_scope(self, qualname):
        frame = sys._getframe(1)
        declared = set(frame.f_code.co_varnames) | set(frame.f_code.co_cellvars)
        scope_id = qualname + ":" + uuid.uuid4().hex

        @contextmanager
        def managed():
            token = self._frames.set((*self._frames.get(), (scope_id, declared)))
            try:
                with self.session.scope(scope_id):
                    yield
            finally:
                self._frames.reset(token)
                self.session.forget_scope(scope_id)
                for key in [key for key in self._iterations if key[0] == scope_id]:
                    self._iterations.pop(key, None)
                for key in [key for key in self._array_refs if key[0] == scope_id]:
                    self._array_refs.pop(key, None)
        return managed()


def run_script(path: Path, *, arguments=(), session, policy: InstrumentPolicy | None = None, expected_digest=None) -> int:
    original_argv, original_path = sys.argv, list(sys.path)
    original_main = sys.modules.get("__main__")
    try:
        source = read_source(path)
        if expected_digest is not None and source.digest != expected_digest:
            raise RuntimeError("Analysis source changed before execution; start a new run")
        sys.argv = [source.path, *arguments]
        sys.path.insert(0, str(Path(source.path).parent))
        compiled = instrument(source.text, source.path, policy or InstrumentPolicy(), source_digest=source.digest)
        module = ModuleType("__main__")
        module.__dict__.update(__file__=source.path, __package__=None, __spec__=None)
        sys.modules["__main__"] = module
        compiled.execute(session, module.__dict__)
    except KeyboardInterrupt:
        session.finish("cancelled")
        return 130
    except SystemExit as error:
        code = error.code if type(error.code) is int else 0 if error.code is None else 1
        session.finish("completed" if code == 0 else "failed", exit_code=code)
        return code
    except BaseException as error:
        frames = [{"path": clean_text(f.filename, 4096), "line": f.lineno, "name": clean_text(f.name), "code": clean_text(f.line or "", 4096)}
                  for f in traceback.extract_tb(error.__traceback__) if f.filename == str(Path(path).resolve())]
        session.emit("analysis.error", {"error_type": type(error).__name__, "message": clean_text(str(error), 4096), "frames": frames}, critical=True)
        session.finish("failed", error_type=type(error).__name__, frames=frames)
        return 1
    else:
        session.finish("completed")
        return 0
    finally:
        sys.argv = original_argv
        sys.path[:] = original_path
        if original_main is not None:
            sys.modules["__main__"] = original_main
        else:
            sys.modules.pop("__main__", None)
