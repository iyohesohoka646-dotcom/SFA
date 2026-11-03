"""Private JSON pipe worker; no live arrays or pickle cross this boundary."""
from __future__ import annotations

import contextlib
import hashlib
import importlib
import importlib.util
import json
import sys
import time
from pathlib import Path

from .models import ProbeResult, ProbeSpec, SnapshotRef
from .probes import ProbeContext, threshold


def send(value):
    encoded = json.dumps(value, allow_nan=False, ensure_ascii=False).encode("utf-8")
    if len(encoded) > 512 * 1024:
        raise ValueError("Probe response exceeds byte budget")
    sys.stdout.buffer.write(encoded + b"\n")
    sys.stdout.buffer.flush()


def load(entrypoint):
    if entrypoint == "__builtin_numpy__":
        import numpy as np
        return np
    name, _, attribute = entrypoint.rpartition(":")
    if name.endswith(".py"):
        path = Path(name).resolve(strict=True)
        module_id = "cdaf_probe_" + hashlib.sha256(str(path).encode()).hexdigest()
        spec = importlib.util.spec_from_file_location(module_id, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_id] = module
        spec.loader.exec_module(module)
    else:
        module = importlib.import_module(name)
    plugin = getattr(module, attribute)()
    if getattr(plugin, "protocol_version", None) != 1 or not callable(getattr(plugin, "evaluate", None)):
        raise ValueError("Probe plugin must implement protocol version 1")
    return plugin


def numerical_probe(np, spec, snapshot, path):
    from .agent.privacy import cell, finite_number
    array = np.load(path, mmap_mode="r", allow_pickle=False)
    if array.ndim != 2 or array.dtype.kind not in "biufc":
        raise ValueError("This check requires a complete 2D numeric matrix")
    evidence = {"shape": list(array.shape)}
    low, high = threshold(spec.parameters, "min"), threshold(spec.parameters, "max")
    if spec.kind == "rank":
        number = int(np.linalg.matrix_rank(array))
        evidence["rank"] = number
    elif spec.kind == "condition":
        number = float(np.linalg.cond(array))
        evidence.update(condition=finite_number(number), finite=bool(np.isfinite(number)))
    else:
        values = np.linalg.eigvalsh(array) if spec.parameters.get("hermitian") is True else np.linalg.eigvals(array)
        evidence.update(values=[cell(v) for v in values[:32]], count=len(values), truncated=len(values) > 32)
        number = None
    failed = number is not None and (low is not None and number < low or high is not None and number > high)
    return ProbeResult(probe_id=spec.id, snapshot_id=snapshot.id, status="fail" if failed else "pass",
        fidelity="exact", message="Computed from this observation's saved numeric artifact", evidence=evidence)


def main():
    plugins = {}
    send({"type": "ready", "protocol_version": 1})
    while True:
        line = sys.stdin.buffer.readline(512 * 1024 + 1)
        if not line:
            return
        if len(line) > 512 * 1024 or not line.endswith(b"\n"):
            return
        message = json.loads(line)
        request_id = message["request_id"]
        if message["type"] == "prepare":
            try:
                with contextlib.redirect_stdout(sys.stderr):
                    plugins[message["entrypoint"]] = load(message["entrypoint"])
                send({"type": "prepared", "request_id": request_id})
            except Exception as error:
                send({"type": "prepare_error", "request_id": request_id, "error_type": type(error).__name__})
        elif message["type"] == "evaluate":
            spec, snapshot = ProbeSpec.model_validate(message["spec"]), SnapshotRef.model_validate(message["snapshot"])
            started = time.perf_counter()
            try:
                with contextlib.redirect_stdout(sys.stderr):
                    if message["entrypoint"] == "__builtin_numpy__":
                        result = numerical_probe(plugins[message["entrypoint"]], spec, snapshot, message["artifact_path"])
                    else:
                        result = plugins[message["entrypoint"]].evaluate(ProbeContext.from_wire(spec, snapshot))
                result = ProbeResult.model_validate(result)
                # Force strict encoding inside the protected evaluation boundary.
                json.dumps(result.model_dump(mode="json"), allow_nan=False)
            except Exception as error:
                result = ProbeResult(probe_id=spec.id, snapshot_id=snapshot.id, status="error", message="Probe evaluation failed", evidence={"error_type": type(error).__name__})
            result.duration_ms = (time.perf_counter() - started) * 1000
            send({"type": "result", "request_id": request_id, "result": result.model_dump(mode="json")})


if __name__ == "__main__":
    main()
