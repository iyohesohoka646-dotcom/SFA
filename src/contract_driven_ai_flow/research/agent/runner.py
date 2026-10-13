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
    def __init__(self, session, references, *, module_scope="main", controls=None):
        self.session = session
        self.references = references
        self.module_scope = module_scope
        self._iterations = {}
        self._active = contextvars.ContextVar("research_statement", default=None)
        self._frames = contextvars.ContextVar("research_scope_frames", default=())

        self._array_refs = {}
        from .control_observation import ControlCollector
        # P2a: a project run shares one collector so the detail/node budget is
        # enforced for the whole run. Legacy single-file runtimes omit this and
        # keep a private collector exactly as before.
        if controls is None:
            controls = ControlCollector(
                session, detail_limit=session.policy.max_control_details
            )
        self.controls = controls

    def branch(self, identifier, selected):
        self.controls.branch(self.references[identifier], selected)

    def loop_scope(self, identifier):
        return self.controls.loop(self.references[identifier])

    def iteration_enter(self, identifier):
        self.controls.iteration(self.references[identifier])

    def natural_exit(self, identifier):
        self.controls.natural(self.references[identifier])

    def reached_after(self, identifier):
        self.controls.reached_after(self.references[identifier])

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
            # P2a: every traced module keeps its own global binding scope; the
            # entry module keeps the legacy "main" scope so single-file runs are
            # byte-for-byte unchanged.
            return self.module_scope
        code = frame.f_code
        if name in code.co_varnames or name in code.co_cellvars:
            return self.session._scope.get()
        if name in code.co_freevars:
            for scope_id, declared in reversed(self._frames.get()[:-1]):
                if name in declared:
                    return scope_id
            return self.session._scope.get()
        return self.module_scope

    def remember_array(self, owner, name, value):
        np = sys.modules.get("numpy")
        if np is not None and isinstance(value, np.ndarray):
            self._array_refs[(owner, name)] = weakref.ref(value)

    def input_observation(self, owner, name, value, source, parents=(), provenance="declared"):
        binding = owner + ":" + name
        observed = self.session._latest.get(binding)
        if observed is None or self.session._objects.get(binding) != id(value):
            token = self.session._current.set(None)
            try:
                with self.session.scope(owner):
                    observed = self.session.watch(
                        name,
                        value,
                        source=source,
                        parent_snapshots=list(parents),
                        provenance=provenance,
                        coverage={"mode": "auto", "binding": "observed", "dependency": "inferred" if parents else "declared", "hidden_mutations": "not_observed"},
                    )
            finally:
                self.session._current.reset(token)
        self.remember_array(owner, name, value)
        return observed

    def call_inputs(self):
        """Caller operation context: the input snapshots of the active call site."""
        operation = self.session._current.get()
        return tuple(operation["input_snapshots"]) if operation else ()

    def call_arguments(self, frame, source):
        """Arguments captured with the real callee lexical owner and file id."""
        code = frame.f_code
        count = code.co_argcount + code.co_kwonlyargcount
        if code.co_flags & 0x04:
            count += 1
        if code.co_flags & 0x08:
            count += 1
        context = self.call_inputs()
        observed = []
        for name in code.co_varnames[:count]:
            if type(name) is not str or not name or name not in frame.f_locals:
                continue
            observed.append(
                self.input_observation(
                    self.owner(frame, name),
                    name,
                    frame.f_locals[name],
                    source,
                    parents=context,
                    provenance="inferred",
                )["id"]
            )
        return tuple(observed)

    def returned(self, identifier, value):
        # Passthrough return evidence: the value is already evaluated once and is
        # handed back unchanged. Nothing is published yet: a ``finally`` block, a
        # later ``return`` or an exception may still supersede this candidate, so
        # only the surviving return is committed when the frame exits normally.
        try:
            reference = self.references[identifier]
            frame = sys._getframe(1)
            reads = tuple(reference.get("reads") or ())
            parents = []
            for name in reads:
                values = self.values(frame, (name,))
                if name not in values:
                    continue
                parents.append(
                    self.input_observation(
                        self.owner(frame, name), name, values[name], reference["source"]
                    )["id"]
                )
            state = self.session.current_call_frame()
            candidate = {"value": value, "source": reference["source"], "parents": tuple(parents)}
            if state is None:
                return value
            state["candidate"] = candidate
        except Exception as error:
            self.capture_error("return-evidence", error)
        return value

    def capture_error(self, kind, error):
        # Observation failures stay visible without ever breaking user results.
        try:
            self.session.record_capture_error(kind, error)
        except Exception:
            pass

    def publish_return(self, state):
        """Commit only the surviving return, merged with the callee's arguments."""
        try:
            candidate = state.get("candidate")
            if candidate is None:
                return
            parents = tuple(dict.fromkeys((*candidate["parents"], *state.get("arguments", ()))))
            token = self.session._current.set(None)
            try:
                snapshot = self.session.watch(
                    "<return>",
                    candidate["value"],
                    source=candidate["source"],
                    parent_snapshots=list(parents),
                    provenance="observed",
                    coverage={"mode": "auto", "binding": "observed", "dependency": "inferred", "hidden_mutations": "not_observed", "return": "surviving"},
                )
            finally:
                self.session._current.reset(token)
        except Exception as error:
            self.capture_error("return-evidence", error)
            return
        self.session.commit_return(snapshot["id"])

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
                scope = self.session.open_return_scope()
                try:
                    yield
                finally:
                    self.session.close_return_scope(scope)
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
        # Surviving callee returns seen inside this statement widen the parent
        # ancestry, so a caller value can be traced to the real cross-file source.
        parents = (*parents, *self.session.pending_returns())
        frame = sys._getframe(1)
        values = self.values(frame, names)
        reference = self.references[identifier]
        updated = set()
        coverage = {"mode": "auto", "binding": "observed", "dependency": "inferred", "hidden_mutations": "not_observed"}
        if active:
            coverage["operation_duration_ms"] = record["duration_ms"]
        for name, value in values.items():
            owner = self.owner(frame, name)
            with self.session.scope(owner):
                self.session.watch(name, value, source=reference["source"], parent_snapshots=parents, provenance="inferred",
                    coverage=coverage)
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

    def function_scope(self, qualname, identifier):
        frame = sys._getframe(1)
        declared = set(frame.f_code.co_varnames) | set(frame.f_code.co_cellvars)
        scope_id = qualname + ":" + uuid.uuid4().hex
        source = self.references[identifier]["source"]

        @contextmanager
        def managed():
            token = self._frames.set((*self._frames.get(), (scope_id, declared)))
            state = {"scope": scope_id, "arguments": (), "candidate": None, "failed": False}
            frame_token = self.session.push_call_frame(state)
            try:
                with self.session.scope(scope_id), self.controls.activation(qualname, scope_id), self.controls.function(self.references[identifier]):
                    # Arguments belong to the callee activation, not the caller scope.
                    try:
                        state["arguments"] = self.call_arguments(frame, source)
                    except Exception as error:
                        self.capture_error("call-arguments", error)
                    try:
                        yield
                    except BaseException:
                        # Exceptional exits discard the superseded return candidate.
                        state["failed"] = True
                        raise
                    self.publish_return(state)
            finally:
                self.session.pop_call_frame(frame_token)
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
