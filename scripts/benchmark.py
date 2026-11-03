"""Measure capture and SQLite costs separately from Python process startup."""
import json
import platform
import statistics
import tempfile
import time
from pathlib import Path

from contract_driven_ai_flow.models import CapturePolicy, ProjectSpec, RunEvent, canonical
from contract_driven_ai_flow.privacy import capture
from contract_driven_ai_flow.storage import Store, atomic_write, now


def measure(function, count=300):
    times = []
    for _ in range(count):
        started = time.perf_counter_ns()
        function()
        times.append((time.perf_counter_ns() - started) / 1000)
    return {"iterations": count, "median_us": statistics.median(times), "p95_us": sorted(times)[int(count * .95)]}


def main():
    repo = Path(__file__).resolve().parents[1]
    value = {"values": list(range(1000)), "password": "synthetic-secret", "email": "synthetic@example.com"}
    costs = {"json_only": measure(lambda: canonical(value))}
    for level in ("metadata", "summary", "sample", "full"):
        policy = CapturePolicy(level=level)
        costs[level] = {**measure(lambda: capture(value, policy)), "captured_bytes": len(canonical(capture(value, policy)).encode())}
    with tempfile.TemporaryDirectory(prefix="cdaf-benchmark-") as temporary:
        store = Store(Path(temporary))
        spec = ProjectSpec()
        rid = store.create_run(spec, {})
        costs["sqlite_event"] = measure(lambda: store.event(RunEvent(run_id=rid, revision=spec.revision, time=now(), kind="benchmark", data={"count": 1000}), []), 100)
    atomic_write(repo / "docs/assets/capture-performance.json", json.dumps({"measured_at": now(), "platform": platform.platform(), "input_items": 1000, "costs": costs, "note": "Microbenchmarks in this host; no universal performance threshold. Worker startup is included in module duration, measured separately by the real examples."}, indent=2))
    print(json.dumps(costs, indent=2))


if __name__ == "__main__":
    main()
