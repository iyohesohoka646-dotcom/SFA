"""Bounded local scheduler. Execution, observation and control are separate records."""
from __future__ import annotations

import concurrent.futures
import importlib.metadata
import json
import multiprocessing
import platform
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .compiler import compile_project, select
from .models import ModuleSpec, ProjectSpec, RunEvent, canonical
from .paths import FlowError, inside
from .privacy import capture, sanitize, sensitive_key
from .source import symbol_text
from .probes import compile_expression, evaluate_probe
from .storage import Store, file_digest, now
from .worker import MAX_PAYLOAD, invoke


class CompositeContractError(FlowError):
    pass


class CompositeBlocked(FlowError):
    pass


def violations(schema: dict, value: Any, fields=None) -> list[dict]:
    result = []
    for error in list(Draft202012Validator(schema).iter_errors(value))[:32]:
        path = "/" + "/".join(str(p) for p in error.absolute_path)
        private = bool(error.absolute_path) and sensitive_key(str(error.absolute_path[-1]), fields or [], path)
        expected = "[REDACTED]" if private else sanitize(error.validator_value, fields or [])
        result.append({"path": path, "rule": error.validator, "expected": expected, "actual_type": type(error.instance).__name__})
    return result


class Runner:
    def __init__(self, root: Path):
        self.store = Store(root)
        self.root = self.store.root
        self.cancelled = threading.Event()
        self.pause_requested = threading.Event()
        self._control = threading.Condition()
        self._resume_generation = 0
        self.outputs: dict[str, Any] = {}
        self._lock = threading.Lock()
        self.boundary_lock = threading.RLock()

    def bound_value(self, source):
        value = source.value if source.kind == "literal" else self.input if source.kind == "project" else self.outputs[source.module]
        return select(value, source.pointer)

    def ensure_source_boundary(self, source, target_id):
        if source.kind == "module" and self.spec_modules[source.module].kind == "composite":
            boundary = "input" if self.spec_modules[target_id].parent == source.module else "output"
            self.ensure_composite(source.module, boundary)

    def ensure_composite(self, module_id, boundary):
        with self.boundary_lock:
            key = (module_id, boundary)
            if key in self.blocked_boundaries:
                raise CompositeBlocked("Composite public boundary was blocked")
            if key in self.boundary_checks:
                if not self.boundary_checks[key]:
                    raise CompositeContractError("Composite public contract failed")
                return
            module = self.spec_modules[module_id]
            if boundary == "input":
                bindings = [b for b in self.plan.composite_inputs if b.target == module_id]
                for binding in bindings:
                    original = self.logical_bindings[binding.id]
                    self.ensure_source_boundary(original.source, module_id)
                value = {b.port: self.bound_value(b.source) for b in bindings}
            else:
                for source in module.outputs.values():
                    self.ensure_source_boundary(source, module_id)
                value = {port: self.bound_value(source) for port, source in self.plan.composite_outputs[module_id].items()}
            errors = violations(getattr(module.contract, boundary), value, self.project.capture.sensitive_fields)
            self.emit("contract.checked", module, {"boundary": boundary, "status": "fail" if errors else "pass", "violations": errors})
            self.boundary_checks[key] = not errors
            if errors:
                with self._lock:
                    self.quality_failed = True
                self.emit("composite.failed", module, {"boundary": boundary})
                raise CompositeContractError("Composite public contract failed")
            self.emit("composite." + boundary, module, {"capture": capture(value, self.project.capture)})
            self.composite_values[key] = value
            if self.observe(module, boundary, value if boundary == "input" else self.composite_values.get((module_id, "input"), {}), value if boundary == "output" else None, 0):
                self.blocked_boundaries.add(key)
                self.emit("composite.blocked", module, {"boundary": boundary})
                raise CompositeBlocked("Composite public boundary was blocked")

    def emit(self, kind: str, module: ModuleSpec | None = None, data: dict | None = None, attempt: int = 0, binding=None, links=None):
        return self.store.event(RunEvent(run_id=self.run_id, time=now(), kind=kind, revision=self.project.revision,
                                        module=module.id if module else None, contract_revision=module.contract.revision if module else None,
                                        attempt=attempt, binding=binding, links=links or [], data=data or {}), self.project.capture.sensitive_fields)

    def poll_control(self):
        action = self.store.take_control(self.run_id)
        if action == "cancel":
            self.cancelled.set()
            self.pause_requested.clear()
        elif action == "pause":
            self.pause_requested.set()
            self.store.set_status(self.run_id, "paused")
            self.emit("control.paused", data={"reason": "User requested pause at module boundaries"})
        elif action == "resume":
            with self._control:
                if self.pause_requested.is_set():
                    self.pause_requested.clear()
                    self._resume_generation += 1
                    self.store.set_status(self.run_id, "running")
                    self.emit("control.resumed", data={"reason": "Explicit user override at module boundaries"})
                    self._control.notify_all()

    def pause(self, reason: str):
        with self._control:
            generation = self._resume_generation
            self.pause_requested.set()
            self.store.set_status(self.run_id, "paused")
            self.emit("control.paused", data={"reason": reason})
        while not self.cancelled.is_set():
            self.poll_control()
            with self._control:
                if self._resume_generation != generation:
                    return
                self._control.wait(.05)

    def observe(self, module, boundary, kwargs, output, attempt):
        stop = False
        for probe in self.project.probes:
            if probe.module != module.id or probe.boundary != boundary:
                continue
            result = evaluate_probe(probe, kwargs, output, input_schema=module.contract.input, output_schema=module.contract.output,
                                    sensitive_fields=self.project.capture.sensitive_fields)
            record = result.model_dump()
            if probe.kind == "capture" and result.status == "pass":
                record["value"] = capture(result.value, self.project.capture)
                record["pointer"] = probe.pointer
            self.emit("probe.result", module, record, attempt, probe.binding)
            with self._lock:
                if result.status == "fail":
                    self.quality_failed = True
                if result.status == "error":
                    self.observation_degraded = True
            if result.status != "skipped":
                if probe.policy == "breakpoint" or (probe.policy == "pause" and result.status in ("fail", "error")) or (probe.policy == "block" and result.status == "error"):
                    self.pause(f"Probe {probe.id}: {result.status}")
                elif probe.policy == "block" and result.status == "fail":
                    self.emit("control.blocked", module, {"probe": probe.id}, attempt)
                    stop = True
        return stop or self.cancelled.is_set()

    def work(self, module: ModuleSpec, kwargs: dict):
        if module.kind == "decision":
            value = compile_expression(module.condition or "", input_schema=module.contract.input).evaluate(kwargs, None)
            if type(value) is not bool:
                return {"status": "failed", "error": {"type": "DecisionTypeError", "message": "Decision must return bool"}}
            return {"status": "completed", "output": value}
        payload = canonical(kwargs).encode("utf-8")
        if len(payload) > MAX_PAYLOAD:
            return {"status": "failed", "error": {"type": "PayloadLimit", "message": "Input exceeds 16 MiB boundary limit"}}
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=invoke, args=(sender, str(self.root), module.symbol.model_dump(), payload, self.sources[module.id]), daemon=True)
        started = time.monotonic()
        try:
            process.start()
            sender.close()
            while True:
                self.poll_control()
                if self.cancelled.is_set():
                    return {"status": "cancelled"}
                if time.monotonic() - started > module.timeout_seconds:
                    return {"status": "timeout", "error": {"type": "Timeout", "message": "Worker exceeded its deadline"}}
                try:
                    if receiver.poll(.025):
                        return json.loads(receiver.recv_bytes(MAX_PAYLOAD))
                except (EOFError, OSError, ValueError):
                    return {"status": "failed", "error": {"type": "WorkerExit", "message": "Worker exited or returned invalid JSON"}}
                if not process.is_alive():
                    return {"status": "failed", "error": {"type": "WorkerExit", "exit_code": process.exitcode}}
        finally:
            if process.pid:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=2)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=2)
                process.close()
            sender.close()
            receiver.close()

    def execute_module(self, module):
        if self.pause_requested.is_set():
            self.pause("User requested pause")
        if self.cancelled.is_set():
            return "cancelled", None
        owner = module
        while owner:
            if owner.guard and self.outputs.get(owner.guard.decision) is not owner.guard.when:
                self.emit("module.skipped", module, {"reason": "Decision selected the other branch", "guard_owner": owner.id})
                if owner.kind == "composite":
                    with self.boundary_lock:
                        if owner.id not in self.skipped_composites:
                            self.skipped_composites.add(owner.id)
                            self.emit("composite.skipped", owner, {"reason": "Decision selected the other branch"})
                return "skipped", None
            owner = self.spec_modules.get(owner.parent)
        kwargs, links = {}, []
        try:
            ancestors = []
            parent = module.parent
            while parent:
                ancestors.append(parent)
                parent = self.spec_modules[parent].parent
            for parent in reversed(ancestors):
                self.ensure_composite(parent, "input")
            for binding in self.plan.bindings:
                if binding.target != module.id:
                    continue
                source = binding.source
                original = self.logical_bindings[binding.id]
                self.ensure_source_boundary(original.source, module.id)
                value = source.value if source.kind == "literal" else self.input if source.kind == "project" else self.outputs[source.module]
                # Even before a worker starts, aliases cannot cross a binding boundary.
                kwargs[binding.port] = json.loads(canonical(select(value, source.pointer)))
                link = {"binding": binding.id, "module": source.module, "sequence": self.completed_events.get(source.module)}
                links.append(link)
                self.emit("binding.transferred", module, {"port": binding.port}, binding=binding.id, links=[link])
        except CompositeContractError:
            self.emit("module.failed", module, {"error": {"type": "CompositeContract", "message": "Public boundary check failed"}})
            return "failed", None
        except CompositeBlocked:
            self.emit("module.blocked", module, {"boundary": "composite"})
            return "blocked", None
        except (KeyError, IndexError, TypeError, ValueError):
            self.emit("module.failed", module, {"error": {"type": "BindingError", "message": "Bound value is missing or cannot be encoded"}})
            return "failed", None
        for attempt in range(1, module.retries + 2):
            self.emit("module.started", module, {"input": capture(kwargs, self.project.capture)}, attempt, links=links)
            errors = violations(module.contract.input, kwargs, self.project.capture.sensitive_fields)
            self.emit("contract.checked", module, {"boundary": "input", "status": "fail" if errors else "pass", "violations": errors}, attempt)
            if errors:
                self.quality_failed = True
                self.emit("module.failed", module, {"error": {"type": "InputContract"}}, attempt)
                return "failed", None
            if self.observe(module, "input", kwargs, None, attempt):
                self.emit("module.blocked", module, {"boundary": "input"}, attempt)
                return "blocked", None
            started = time.monotonic()
            try:
                result = self.work(module, kwargs)
            except Exception as exc:
                result = {"status": "failed", "error": {"type": type(exc).__name__, "message": "Worker dispatch or decision evaluation failed"}}
            duration = (time.monotonic() - started) * 1000
            status = result["status"]
            if status != "completed":
                self.emit("module." + status, module, {**result, "duration_ms": duration}, attempt)
                if status in ("failed", "timeout") and attempt <= module.retries:
                    self.emit("module.retrying", module, {"next_attempt": attempt + 1}, attempt)
                    continue
                return status, None
            output = result.get("output")
            errors = violations(module.contract.output, output, self.project.capture.sensitive_fields)
            self.emit("contract.checked", module, {"boundary": "output", "status": "fail" if errors else "pass", "violations": errors}, attempt)
            if errors:
                self.quality_failed = True
                self.emit("module.failed", module, {"error": {"type": "OutputContract"}}, attempt)
                return "failed", None
            if self.pause_requested.is_set() and not self.cancelled.is_set():
                self.pause("User requested pause at output boundary")
            blocked = self.observe(module, "output", kwargs, output, attempt)
            event = self.emit("module.completed", module, {"duration_ms": duration, "output": capture(output, self.project.capture), "downstream_blocked": blocked}, attempt)
            with self._lock:
                self.completed_events[module.id] = event.sequence
            return "blocked" if blocked else "completed", output
        raise AssertionError("Unreachable retry loop")

    def run(self, input_value: Any, *, run_id: str | None = None, project: ProjectSpec | None = None) -> dict:
        self.project = project or self.store.load()
        self.plan = compile_project(self.project)
        if not self.plan.valid:
            raise FlowError("Compilation failed: " + "; ".join(d.message for d in self.plan.diagnostics if d.severity == "error"))
        canonical(input_value)
        self.outputs = {}
        self.input = json.loads(canonical(input_value))
        self.quality_failed, self.observation_degraded = False, False
        self.spec_modules = {m.id: m for m in self.project.modules}
        self.logical_bindings = {b.id: b for b in self.project.bindings}
        self.boundary_checks = {}
        self.blocked_boundaries = set()
        self.composite_values = {}
        self.skipped_composites = set()
        self.completed_events: dict[str, int] = {}
        sources, source_errors = {}, []
        for module in self.plan.modules:
            if module.symbol:
                path = inside(self.root, module.symbol.path)
                content = path.read_text(encoding="utf-8") if path.exists() else None
                sources[module.id] = file_digest(content) if content is not None else "missing"
                if module.symbol.digest:
                    try:
                        matches = content is not None and file_digest(symbol_text(content, module.symbol.qualname)) == module.symbol.digest
                    except (FlowError, SyntaxError):
                        matches = False
                    if not matches:
                        source_errors.append(module)
        env = {"python": sys.version.split()[0], "platform": platform.platform(), "sources": sources,
               "dependencies": {name: importlib.metadata.version(name) for name in ("contract-driven-ai-flow", "jsonschema", "pydantic")},
               "input_digest": file_digest(canonical(self.input))}
        self.sources = sources
        self.store.enforce_retention(self.project.capture.retention_days)
        self.run_id = self.store.create_run(self.project, env, run_id)
        self.emit("run.started", data={"input": capture(self.input, self.project.capture), "environment": env})
        states: dict[str, str] = {}
        modules = {m.id: m for m in self.plan.modules}
        deps = {mid: set(self.plan.dependencies[mid]) for mid in modules}
        pending = set(modules)
        futures = {}
        final_status = "completed"
        try:
            errors = violations(self.project.input_schema, self.input, self.project.capture.sensitive_fields)
            if errors:
                self.emit("run.input_invalid", data={"violations": errors})
                final_status = "failed"
                pending.clear()
                self.quality_failed = True
            if source_errors:
                for module in source_errors:
                    self.emit("module.failed", module, {"error": {"type": "SymbolVersion", "message": "Declared symbol digest changed; review the source before executing"}})
                    states[module.id] = "failed"
                final_status = "failed"
                pending.clear()
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.project.concurrency) as pool:
                while pending or futures:
                    self.poll_control()
                    for mid in self.plan.order:
                        if self.pause_requested.is_set() and not self.cancelled.is_set():
                            break
                        if mid not in pending or not deps[mid].issubset(states):
                            continue
                        if self.cancelled.is_set() or any(states[d] != "completed" for d in deps[mid]):
                            states[mid] = "skipped"
                            self.emit("module.skipped", modules[mid], {"reason": "Cancelled or upstream unavailable"})
                            pending.remove(mid)
                            continue
                        if len(futures) >= self.project.concurrency:
                            break
                        pending.remove(mid)
                        futures[pool.submit(self.execute_module, modules[mid])] = mid
                    if futures:
                        done, _ = concurrent.futures.wait(futures, timeout=.05, return_when=concurrent.futures.FIRST_COMPLETED)
                        for future in done:
                            mid = futures.pop(future)
                            state, output = future.result()
                            states[mid] = state
                            if state == "completed":
                                self.outputs[mid] = output
                    elif pending:
                        if self.pause_requested.is_set() and not self.cancelled.is_set():
                            time.sleep(.05)
                            continue
                        raise FlowError("Scheduler stalled after compilation")
            for mid, ports in self.plan.composite_outputs.items():
                composite = self.spec_modules[mid]
                if mid in self.skipped_composites or composite.guard and self.outputs.get(composite.guard.decision) is not composite.guard.when:
                    continue
                required = {source.module for source in ports.values() if source.kind == "module"}
                if required.issubset(self.outputs):
                    self.ensure_composite(mid, "output")
            if self.cancelled.is_set():
                final_status = "cancelled"
            elif any(s in ("failed", "timeout") for s in states.values()):
                final_status = "failed"
            elif "blocked" in states.values():
                final_status = "blocked"
        except BaseException as exc:
            self.cancelled.set()
            final_status = "blocked" if isinstance(exc, CompositeBlocked) else "cancelled" if isinstance(exc, KeyboardInterrupt) else "failed"
            self.emit("run.error", data={"type": type(exc).__name__, "message": "Run interrupted during scheduling"})
        finally:
            quality = "failed" if self.quality_failed else "degraded" if self.observation_degraded else "passed" if final_status == "completed" else "unknown"
            self.emit("run.finished", data={"status": final_status, "quality": quality, "modules": states})
            self.store.finish(self.run_id, final_status, quality)
        return self.store.run(self.run_id)
