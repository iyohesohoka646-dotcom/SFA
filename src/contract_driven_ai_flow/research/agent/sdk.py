"""Explicit observation without replacing the user's native objects."""
from __future__ import annotations

import contextvars
import json
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .adapters import UnknownAdapter
from .artifact_writer import ArtifactWriter
from .budget import CapturePolicy
from .privacy import clean_text, sanitize_json, sensitive
from .registry import AdapterRegistry
from .transport import EventTransport


def now():
    return datetime.now(timezone.utc).isoformat()


class TraceSession:
    def __init__(self, name: str, transport: EventTransport | None = None, policy: CapturePolicy | None = None, *,
                 run_id: str | None = None, registry: AdapterRegistry | None = None, artifact_root: Path | None = None, observer=None):
        self.name = clean_text(name)
        self.policy = policy or CapturePolicy()
        self.transport = transport or EventTransport(max_queue_events=self.policy.max_queue_events,
            publish_interval_ms=self.policy.publish_interval_ms, max_queue_bytes=self.policy.max_queue_bytes)
        self.run_id = run_id or uuid.uuid4().hex
        self.registry = registry or AdapterRegistry()
        self.observer = observer
        self.writer = ArtifactWriter(artifact_root, self.policy) if artifact_root is not None else None
        self._versions = {}
        self._latest = {}
        self._objects = {}
        self._lock = threading.RLock()
        self._current = contextvars.ContextVar("research_operation", default=None)
        self._scope = contextvars.ContextVar("research_scope", default="main")
        self._finished = False
        self.capture_errors = 0
        self._binding_count = 0
        self.emit("run.started", {"name": self.name, "capture": asdict(self.policy)}, critical=True)

    def emit(self, kind, payload, *, source=None, snapshot_id=None, operation_id=None, critical=False):
        self.transport.emit({"schema_version": 1, "run_id": self.run_id, "sequence": 0, "kind": kind,
            "timestamp": now(), "source": source, "snapshot_id": snapshot_id, "operation_id": operation_id,
            "payload": payload}, critical=critical)

    @contextmanager
    def scope(self, scope_id):
        token = self._scope.set(scope_id)
        try:
            yield
        finally:
            self._scope.reset(token)

    def latest(self, name):
        with self._lock:
            return self._latest.get(self._scope.get() + ":" + name) or self._latest.get("main:" + name)

    def watch(self, name: str, value: object, *, source=None, axes=None, unit=None, parents=(), parent_snapshots=None, provenance="declared", coverage=None) -> dict:
        scope_id = self._scope.get()
        if type(name) is not str or not name or len(name) > 256:
            raise ValueError("Observed binding name must be 1-256 characters")
        binding = scope_id + ":" + name
        from .source import logical_binding
        logical_key = logical_binding(source, scope_id, name)
        operation = self._current.get()
        private = sensitive(name, self.policy.sensitive_fields)
        adapter = self.registry._unknown
        try:
            adapter = self.registry.resolve(value)
            result = adapter.capture(value, CapturePolicy(level="metadata") if private else self.policy)
            # Validate BEFORE sanitising: invalid adapter data cannot masquerade
            # as a successful, partially hidden capture.
            json.dumps(asdict(result), allow_nan=False)
            descriptor = sanitize_json(result.descriptor, self.policy.sensitive_fields)
            sample = sanitize_json(result.sample, self.policy.sensitive_fields)
            statistics = sanitize_json(result.statistics, self.policy.sensitive_fields)
            if result.fidelity not in ("exact", "sampled", "metadata_only"):
                raise ValueError("Unsupported capture fidelity")
            if sum(len(row) for row in sample.get("values", [])) > self.policy.max_preview_cells:
                raise ValueError("Adapter exceeded preview budget")
            if statistics.get("sample_count", 0) > self.policy.max_stat_elements:
                raise ValueError("Adapter exceeded statistics budget")
            if not all(type(v) is str for v in (*result.truncation, *result.redacted)):
                raise ValueError("Invalid adapter diagnostics")
            fidelity = result.fidelity
            truncation = result.truncation[:128]
            redacted = result.redacted[:128]
            encoded_sample = json.dumps(sample, allow_nan=False)
            if '"truncated-string"' in encoded_sample:
                truncation.append("preview_text_truncated")
                fidelity = "sampled"
            if "[REDACTED" in encoded_sample:
                redacted.append("preview:text")
        except Exception as error:
            self.capture_errors += 1
            descriptor = UnknownAdapter().describe(value)
            sample, statistics, fidelity = {}, {}, "metadata_only"
            truncation, redacted = ["adapter_failed"], []
            self.emit("capture.error", {"binding": binding, "error_type": type(error).__name__}, critical=True)
        if axes is not None:
            if descriptor.get("shape") is not None and len(axes) != len(descriptor["shape"]):
                raise ValueError("Axis annotations must match the observed dimensions")
            descriptor["axes"] = [clean_text(axis) for axis in axes]
        if unit is not None:
            descriptor["unit"] = clean_text(unit)
        artifact = None
        if private:
            redacted.append("binding:" + name)
        elif self.policy.level == "full":
            if self.writer is None:
                truncation.append("artifact_storage_unconfigured")
            else:
                artifact, reason = self.writer.save(value, adapter, descriptor)
                if reason:
                    truncation.append(reason)
        parent_ids = list(parent_snapshots) if parent_snapshots is not None else [item["id"] for name in parents if (item := self.latest(name)) is not None]
        with self._lock:
            version = self._versions.get(binding, 0) + 1
            if version == 1:
                self._binding_count += 1
            self._versions[binding] = version
            snapshot = {"id": uuid.uuid4().hex, "run_id": self.run_id, "binding_id": binding, "scope_id": scope_id,
                "name": name, "logical_key": logical_key, "version": version, "descriptor": descriptor, "observed_at": now(),
                "source": sanitize_json(source) if source is not None else None,
                "operation_id": operation["id"] if operation else None, "parents": parent_ids,
                "provenance": provenance if parent_ids else "unknown", "fidelity": fidelity,
                "sample": sample, "statistics": statistics, "truncation": truncation, "redacted": redacted,
                "artifact_ref": artifact, "coverage": coverage or {"mode": "explicit", "hidden_mutations": "not_observed"}}
            if operation:
                operation["output_snapshots"].append(snapshot["id"])
            self._latest[binding] = snapshot
            self._objects[binding] = id(value)
        try:
            self.emit("value.observed", {"snapshot": snapshot}, source=snapshot["source"], snapshot_id=snapshot["id"], operation_id=snapshot["operation_id"],
                critical=self.observer is not None and self.observer.requires_gate(name, binding))
        except (TypeError, ValueError):
            snapshot.update(sample={}, statistics={}, fidelity="metadata_only", truncation=[*truncation, "event_budget_exceeded"])
            self.emit("value.observed", {"snapshot": snapshot}, snapshot_id=snapshot["id"], operation_id=snapshot["operation_id"])
            self.emit("capture.error", {"binding": binding, "error_type": "event_budget_exceeded"}, critical=True)
        if self.observer is not None:
            self.observer.boundary(snapshot, self)
        return snapshot

    @contextmanager
    def operation(self, label: str, *, inputs: dict, source=None, kind="custom", provenance="declared", iteration=1, input_snapshots=None):
        selected = list(input_snapshots) if input_snapshots is not None else []
        for name, value in inputs.items():
            binding = self._scope.get() + ":" + name
            observed = self._latest.get(binding)
            if observed is None or self._objects.get(binding) != id(value):
                token = self._current.set(None)
                try:
                    observed = self.watch(name, value, source=source)
                finally:
                    self._current.reset(token)
            selected.append(observed["id"])
        record = {"id": uuid.uuid4().hex, "run_id": self.run_id, "label": clean_text(label, 4096), "source": sanitize_json(source) if source else None,
            "scope_id": self._scope.get(), "iteration": iteration, "input_snapshots": selected, "output_snapshots": [],
            "kind": kind, "status": "started", "duration_ms": None, "parameters": {"timing": "scope-including-observation"}, "provenance": provenance}
        self.emit("operation.started", {"operation": record}, operation_id=record["id"], source=record["source"])
        token = self._current.set(record)
        started = time.perf_counter()
        try:
            yield record
        except BaseException:
            record["status"] = "failed"
            raise
        else:
            record["status"] = "completed"
        finally:
            if record["duration_ms"] is None:
                record["duration_ms"] = (time.perf_counter() - started) * 1000
            self._current.reset(token)
            self.emit("operation.finished", {"operation": record}, operation_id=record["id"], source=record["source"], critical=record["status"] == "failed")

    def finish(self, status="completed", **details):
        if not self._finished:
            self._finished = True
            self.emit("run.finished", {"status": status, "bindings": self._binding_count, "capture_errors": self.capture_errors,
                "dropped": self.transport.dropped, **sanitize_json(details)}, critical=True)
        return self.transport.close()

    def forget_scope(self, scope_id):
        """Runtime-only invocation scopes have already been published."""
        with self._lock:
            for binding in [key for key in self._latest if key.startswith(scope_id + ":")]:
                self._latest.pop(binding, None)
                self._versions.pop(binding, None)
                self._objects.pop(binding, None)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.finish("completed" if exc is None else "cancelled" if exc_type is KeyboardInterrupt else "failed",
                    error_type=exc_type.__name__ if exc_type else None)
