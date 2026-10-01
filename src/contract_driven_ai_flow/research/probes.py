"""Read-only bounded scientific checks and a reusable isolated plugin pool."""
from __future__ import annotations

import json
import math
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from .agent.privacy import sanitize_json
from .models import ProbeResult, ProbeSpec, SnapshotRef
from .probe_registry import EXPENSIVE, ProbeRegistry


def freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class ProbeContext:
    probe_id: str
    snapshot_id: str
    descriptor: object
    sample: object
    statistics: object
    parameters: object
    fidelity: str

    @classmethod
    def from_wire(cls, spec, snapshot):
        return cls(spec.id, snapshot.id, freeze(snapshot.descriptor.model_dump(mode="json")), freeze(snapshot.sample),
                   freeze(snapshot.statistics), freeze(spec.parameters), snapshot.fidelity)


class ProbePlugin(Protocol):
    protocol_version: int
    def evaluate(self, context: ProbeContext) -> ProbeResult: ...


def result(spec, snapshot, status, message, *, fidelity="metadata_only", evidence=None, duration=0):
    return ProbeResult(probe_id=spec.id, snapshot_id=snapshot.id, status=status, message=message,
        fidelity=fidelity, evidence=evidence or {}, duration_ms=duration)


def shape(value):
    if not isinstance(value, (list, tuple)) or any(type(n) is not int or n < 0 for n in value):
        raise ValueError("Dimensions must be a list of non-negative integers")
    return list(value)


def broadcast(left, right):
    output = []
    for i in range(1, max(len(left), len(right)) + 1):
        a = left[-i] if i <= len(left) else 1
        b = right[-i] if i <= len(right) else 1
        if a == b or a == 1 or b == 1:
            output.insert(0, b if a == 1 else a)
        else:
            return None
    return output


def scalar(value):
    if type(value) in (bool, int, float):
        return value
    if isinstance(value, dict) and value.get("type") == "complex":
        return complex(scalar(value["real"]), scalar(value["imag"]))
    raise ValueError("Value is not a finite numeric cell")


def threshold(parameters, key, default=None):
    value = parameters.get(key, default)
    if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
        raise ValueError("Probe threshold must be finite")
    return value


def _builtin(spec, snapshot):
    kind, parameters = spec.kind, spec.parameters
    descriptor, stats = snapshot.descriptor, snapshot.statistics
    exact = stats.get("exact", False) is True
    fidelity = "exact" if exact else "sampled"
    if not spec.enabled:
        return result(spec, snapshot, "skipped", "Probe is disabled")
    if kind in EXPENSIVE:
        if parameters.get("enable_expensive") is not True:
            return result(spec, snapshot, "skipped", "Expensive probe requires explicit enable_expensive")
        return result(spec, snapshot, "unknown", "Use the isolated pool with an authorised complete artifact for this check")
    if kind == "shape":
        expected = parameters.get("expected")
        if not isinstance(expected, list) or any(n is not None and (type(n) is not int or n < 0) for n in expected):
            raise ValueError("Expected shape must contain dimensions or null wildcards")
        actual = descriptor.shape
        passed = actual is not None and len(actual) == len(expected) and all(want is None or want == got for want, got in zip(expected, actual))
        return result(spec, snapshot, "unknown" if actual is None else "pass" if passed else "fail", "Observed dimensions checked", evidence={"actual_shape": actual, "expected_shape": expected})
    if kind == "dtype":
        expected = parameters.get("expected")
        if type(expected) is not str:
            raise ValueError("Expected dtype must be a string")
        return result(spec, snapshot, "unknown" if descriptor.dtype is None else "pass" if expected == descriptor.dtype else "fail", "Observed data type checked", evidence={"actual_dtype": descriptor.dtype, "expected_dtype": expected})
    if kind in ("broadcast", "dimensions"):
        actual = descriptor.shape
        if actual is None:
            return result(spec, snapshot, "unknown", "Dimensions were not observed")
        other = shape(parameters.get("other_shape"))
        operation = parameters.get("operation", "broadcast")
        if operation == "matmul":
            if not actual or not other or actual[-1] != (other[-2] if len(other) > 1 else other[0]):
                output = None
            else:
                batch = broadcast(actual[:-2] if len(actual) > 1 else [], other[:-2] if len(other) > 1 else [])
                output = None if batch is None else [*batch, *([actual[-2]] if len(actual) > 1 else []), *([other[-1]] if len(other) > 1 else [])]
        elif operation == "broadcast":
            output = broadcast(actual, other)
        else:
            raise ValueError("Unknown dimension operation")
        return result(spec, snapshot, "pass" if output is not None else "fail", "Observed operation dimensions checked", evidence={"actual_shape": actual, "other_shape": other, "output_shape": output, "operation": operation})
    if kind == "finite":
        if "finite_count" not in stats:
            return result(spec, snapshot, "unknown", "Numeric values were not captured")
        bad = stats.get("nan_count", 0) + stats.get("inf_count", 0)
        evidence = {key: stats.get(key) for key in ("sample_count", "population_count", "finite_count", "nan_count", "inf_count", "method")}
        evidence["sample_passed"] = bad == 0
        if bad:
            return result(spec, snapshot, "fail", "Captured values contain NaN or Infinity", fidelity=fidelity, evidence=evidence)
        fully_numeric = stats.get("finite_count", 0) == stats.get("population_count", -1)
        return result(spec, snapshot, "pass" if exact and fully_numeric else "unknown", "All numeric values are finite" if exact and fully_numeric else "Sample is finite; unobserved or non-numeric cells remain unknown", fidelity=fidelity, evidence=evidence)
    if kind in ("range", "variance", "missing"):
        if not stats or not stats.get("sample_count"):
            return result(spec, snapshot, "unknown", "Required value statistics were not captured")
        low, high = threshold(parameters, "min"), threshold(parameters, "max")
        if kind == "range":
            minimum, maximum = stats.get("min"), stats.get("max")
            if minimum is None or maximum is None:
                return result(spec, snapshot, "unknown", "Numeric range is unavailable")
            failed = low is not None and minimum < low or high is not None and maximum > high
            evidence = {"min": minimum, "max": maximum, "sample_count": stats["sample_count"], "method": stats.get("method")}
        elif kind == "variance":
            variance = stats.get("variance")
            if variance is None:
                return result(spec, snapshot, "unknown", "Variance is unavailable")
            failed = low is not None and variance < low or high is not None and variance > high
            evidence = {"variance": variance, "sample_count": stats["sample_count"]}
        else:
            high = threshold(parameters, "max_ratio", 0)
            missing = stats.get("missing_count")
            if missing is None:
                return result(spec, snapshot, "unknown", "Missing value count is unavailable")
            ratio = missing / stats["sample_count"]
            failed = ratio > high
            evidence = {"missing_count": missing, "sample_count": stats["sample_count"], "ratio": ratio}
        # A range witness disproves the global range even in a sample. Aggregate
        # estimates (variance/ratio) cannot settle a whole-population assertion.
        status = "fail" if failed and (exact or kind == "range") else "pass" if exact else "unknown"
        return result(spec, snapshot, status, "Full value statistics checked" if exact else "Sample statistic only; full population is not established", fidelity=fidelity, evidence=evidence)
    if kind == "symmetry":
        actual = descriptor.shape
        if actual is None or len(actual) != 2 or actual[0] != actual[1]:
            return result(spec, snapshot, "fail" if actual is not None else "unknown", "Symmetry requires an observed square matrix", evidence={"actual_shape": actual})
        sample = snapshot.sample
        values, rows, columns = sample.get("values", []), sample.get("row_indices", []), sample.get("column_indices", [])
        lookup = {(r, c): scalar(values[i][j]) for i, r in enumerate(rows) for j, c in enumerate(columns)}
        tolerance = threshold(parameters, "tolerance", 1e-8)
        differences = [abs(v - lookup[c, r]) for (r, c), v in lookup.items() if (c, r) in lookup]
        if not differences:
            return result(spec, snapshot, "unknown", "No paired matrix cells were captured")
        maximum = max(differences)
        full = len(lookup) == actual[0] * actual[1]
        return result(spec, snapshot, "fail" if maximum > tolerance else "pass" if full else "unknown", "Compared captured transpose pairs", fidelity="exact" if full else "sampled", evidence={"max_difference": maximum, "paired_cells": len(differences), "tolerance": tolerance})
    if kind in ("capture_size", "duration"):
        number = descriptor.nbytes if kind == "capture_size" else snapshot.coverage.get("operation_duration_ms")
        limit = threshold(parameters, "max_bytes" if kind == "capture_size" else "max_ms")
        if number is None or limit is None:
            return result(spec, snapshot, "unknown", "Required size/duration evidence or limit is absent")
        return result(spec, snapshot, "fail" if number > limit else "pass", "Observed metadata checked", evidence={"actual": number, "limit": limit})
    return result(spec, snapshot, "error", "Unknown or unregistered probe kind")


def evaluate_probe(spec: ProbeSpec, snapshot: SnapshotRef, *, budget_ms=None) -> ProbeResult:
    started = time.perf_counter()
    try:
        evaluated = _builtin(spec, snapshot)
    except Exception as error:
        evaluated = result(spec, snapshot, "error", "Probe configuration or captured value is invalid", evidence={"error_type": type(error).__name__})
    elapsed = (time.perf_counter() - started) * 1000
    if elapsed > (spec.budget_ms if budget_ms is None else budget_ms):
        evaluated = result(spec, snapshot, "error", "Probe evaluation exceeded budget", evidence={"reason": "timeout"})
    return evaluated.model_copy(update={"duration_ms": elapsed})


def control_action(spec: ProbeSpec, evaluated: ProbeResult):
    if not spec.enabled or spec.policy == "continue" or evaluated.status == "pass":
        return None
    if evaluated.status == "fail":
        return spec.policy
    return "pause"


class ProbeWorker:
    def __init__(self):
        self.process = None
        self.messages = queue.Queue(maxsize=16)
        self.prepared = set()

    @staticmethod
    def _read(process, messages):
        try:
            while True:
                line = process.stdout.readline(512 * 1024 + 1)
                if not line:
                    messages.put({"type": "closed"}, timeout=0.5)
                    return
                if len(line) > 512 * 1024 or not line.endswith(b"\n"):
                    messages.put({"type": "invalid"}, timeout=0.5)
                    return
                messages.put(json.loads(line), timeout=0.5)
        except Exception:
            try:
                messages.put({"type": "invalid"}, timeout=0.5)
            except queue.Full:
                pass

    def start(self):
        if self.process is not None and self.process.poll() is None:
            return
        self.messages = queue.Queue(maxsize=16)
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[2]) + os.pathsep + os.environ.get("PYTHONPATH", ""),
               "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"}
        self.process = subprocess.Popen([sys.executable, "-X", "utf8", "-m", "contract_driven_ai_flow.research.probe_worker"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        threading.Thread(target=self._read, args=(self.process, self.messages), name="cdaf-probe-wire", daemon=True).start()
        if self.messages.get(timeout=3).get("type") != "ready":
            raise ValueError("Probe worker did not become ready")

    def request(self, value, timeout):
        encoded = json.dumps(value, allow_nan=False, ensure_ascii=False).encode("utf-8")
        if len(encoded) > 512 * 1024:
            raise ValueError("Probe frame exceeds byte budget")
        self.process.stdin.write(encoded + b"\n")
        self.process.stdin.flush()
        response = self.messages.get(timeout=timeout)
        if not isinstance(response, dict) or response.get("request_id") != value["request_id"]:
            raise ValueError("Probe protocol response is invalid")
        return response

    def evaluate(self, spec, snapshot, plugin):
        self.start()
        entrypoint = plugin["entrypoint"]
        if entrypoint not in self.prepared:
            prepared = self.request({"type": "prepare", "request_id": uuid.uuid4().hex, "entrypoint": entrypoint}, 3)
            if prepared.get("type") != "prepared":
                raise ValueError("Probe plugin failed to load")
            self.prepared.add(entrypoint)
        response = self.request({"type": "evaluate", "request_id": uuid.uuid4().hex, "entrypoint": entrypoint,
            "spec": spec.model_dump(mode="json"), "snapshot": snapshot.model_dump(mode="json"),
            "artifact_path": plugin.get("artifact_path")}, spec.budget_ms / 1000)
        evaluated = ProbeResult.model_validate(response["result"])
        if evaluated.probe_id != spec.id or evaluated.snapshot_id != snapshot.id:
            raise ValueError("Probe result identity does not match its request")
        return ProbeResult.model_validate(sanitize_json(evaluated.model_dump(mode="json")))

    def stop(self):
        process, self.process = self.process, None
        self.prepared.clear()
        if process is not None:
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            for stream in (process.stdin, process.stdout):
                if stream:
                    stream.close()


class ProbePool:
    def __init__(self, registry=None, *, max_workers=2, max_pending=16, artifact_root=None):
        if not 1 <= max_workers <= 2 or not 1 <= max_pending <= 128:
            raise ValueError("Probe pool limits are invalid")
        self.registry = registry or ProbeRegistry()
        self.artifact_root = Path(artifact_root).resolve() if artifact_root is not None else None
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="cdaf-probe")
        self._capacity = threading.BoundedSemaphore(max_pending)
        self._workers = queue.Queue()
        self._all_workers = [ProbeWorker() for _ in range(max_workers)]
        for worker in self._all_workers:
            self._workers.put(worker)
        self._closed = False

    def _evaluate(self, spec, snapshot):
        plugin = self.registry.plugin(spec.kind)
        if spec.kind in EXPENSIVE and spec.enabled and spec.parameters.get("enable_expensive") is True:
            if snapshot.descriptor.backend != "numpy" or not snapshot.artifact_ref or self.artifact_root is None:
                return result(spec, snapshot, "unknown", "Complete numeric history is required for this check")
            path = (self.artifact_root / snapshot.artifact_ref).resolve()
            if path == self.artifact_root or not path.is_relative_to(self.artifact_root) or path.suffix != ".npy":
                return result(spec, snapshot, "error", "Artifact path is outside the authorised numeric store")
            if not path.is_file():
                return result(spec, snapshot, "unknown", "Complete artifact is missing or expired")
            if path.stat().st_size > 64 * 1024 * 1024:
                return result(spec, snapshot, "error", "Complete artifact exceeds probe byte budget")
            plugin = {"entrypoint": "__builtin_numpy__", "artifact_path": str(path)}
        if plugin is None or not spec.enabled:
            return evaluate_probe(spec, snapshot)
        worker = self._workers.get()
        started = time.perf_counter()
        try:
            return worker.evaluate(spec, snapshot, plugin)
        except queue.Empty:
            worker.stop()
            return result(spec, snapshot, "error", "Isolated probe exceeded startup/evaluation budget", evidence={"reason": "timeout"}, duration=(time.perf_counter() - started) * 1000)
        except Exception as error:
            worker.stop()
            return result(spec, snapshot, "error", "Isolated probe failed", evidence={"reason": "worker_error", "error_type": type(error).__name__}, duration=(time.perf_counter() - started) * 1000)
        finally:
            self._workers.put(worker)

    def submit(self, spec, snapshot):
        if self._closed or not self._capacity.acquire(blocking=False):
            future = Future()
            future.set_result(result(spec, snapshot, "skipped", "Probe queue is full or closed", evidence={"reason": "queue_full"}))
            return future
        try:
            future = self._executor.submit(self._evaluate, spec, snapshot)
        except Exception:
            self._capacity.release()
            raise
        future.add_done_callback(lambda _: self._capacity.release())
        return future

    def evaluate(self, spec, snapshot):
        return self.submit(spec, snapshot).result()

    def close(self):
        self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=True)
        for worker in self._all_workers:
            worker.stop()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
