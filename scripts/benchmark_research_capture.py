"""Same-process SDK comparison in fresh, single-BLAS-thread subprocesses."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def peak_memory():
    if os.name == "nt":
        from ctypes import wintypes
        class MemoryInfo(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                *( (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage", "PrivateUsage"))]
        counters = MemoryInfo()
        counters.cb = ctypes.sizeof(counters)
        current = ctypes.windll.kernel32.GetCurrentProcess
        current.restype = wintypes.HANDLE
        read = ctypes.windll.psapi.GetProcessMemoryInfo
        read.argtypes = [wintypes.HANDLE, ctypes.POINTER(MemoryInfo), wintypes.DWORD]
        read.restype = wintypes.BOOL
        if not read(current(), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError()
        return counters.PeakWorkingSetSize
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


def child(args):
    import numpy as np
    from contract_driven_ai_flow.research.agent.sdk import TraceSession
    from contract_driven_ai_flow.research.agent.budget import CapturePolicy
    from contract_driven_ai_flow.research.agent.transport import EventTransport

    rng = np.random.default_rng(314159)
    left, right = rng.normal(size=(args.size, args.size)), rng.normal(size=(args.size, args.size))
    for _ in range(3):
        left @ right
    if args.mode == "calibrate":
        started = time.perf_counter()
        for _ in range(3):
            left @ right
        elapsed = (time.perf_counter() - started) / 3
        print(json.dumps({"iterations": max(3, int(args.duration / elapsed) + 1), "seconds_per_operation": elapsed}))
        return
    with tempfile.TemporaryDirectory(prefix="research-benchmark-") as folder:
        transport = EventTransport(lambda batch: None)
        trace = None if args.mode == "off" else TraceSession("benchmark", transport, CapturePolicy(level=args.mode), artifact_root=Path(folder))
        started = time.perf_counter()
        if trace:
            trace.watch("left", left)
            trace.watch("right", right)
        for _ in range(args.iterations):
            result = left @ right
            if trace:
                trace.watch("product", result)
        if trace:
            trace.finish()
        elapsed = time.perf_counter() - started
        print(json.dumps({"mode": args.mode, "elapsed_seconds": elapsed, "peak_memory_bytes": peak_memory(),
            "result_sha256": hashlib.sha256(result.tobytes()).hexdigest(), "dropped": transport.dropped,
            "capture_errors": trace.capture_errors if trace else 0, "artifact_bytes": trace.writer.written if trace else 0}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--mode", default="off")
    parser.add_argument("--duration", type=float, default=12)
    parser.add_argument("--iterations", type=int, default=0)
    parser.add_argument("--size", type=int, default=1536)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("docs/assets/research-sdk-performance.json"))
    args = parser.parse_args()
    if args.child:
        child(args)
        return
    if args.duration < 10 or args.repeats < 3:
        parser.error("Use at least 10 seconds and 3 repetitions for the release comparison")
    env = {**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    command = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--child", "--size", str(args.size), "--duration", str(args.duration)]
    calibration = json.loads(subprocess.check_output([*command, "--mode", "calibrate"], env=env, text=True))
    iterations = calibration["iterations"]
    report = {"measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "platform": platform.platform(),
        "processor": platform.processor(), "python": sys.version, "blas_threads": 1, "size": args.size,
        "iterations": iterations, "calibration": calibration, "runs": []}
    for repeat in range(args.repeats):
        for mode in ("off", "metadata", "summary", "full"):
            result = json.loads(subprocess.check_output([*command, "--mode", mode, "--iterations", str(iterations)], env=env, text=True))
            result["repeat"] = repeat + 1
            report["runs"].append(result)
            print(json.dumps(result), flush=True)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    baseline = statistics.median(r["elapsed_seconds"] for r in report["runs"] if r["mode"] == "off")
    report["summary"] = {mode: {"median_seconds": statistics.median(r["elapsed_seconds"] for r in report["runs"] if r["mode"] == mode),
        "overhead_percent": 100 * (statistics.median(r["elapsed_seconds"] for r in report["runs"] if r["mode"] == mode) / baseline - 1)}
        for mode in ("off", "metadata", "summary", "full")}
    report["same_output"] = len({r["result_sha256"] for r in report["runs"]}) == 1
    report["baseline_over_10_seconds"] = all(r["elapsed_seconds"] >= 10 for r in report["runs"] if r["mode"] == "off")
    report["sdk_summary_goal_met"] = report["same_output"] and report["baseline_over_10_seconds"] and report["summary"]["summary"]["overhead_percent"] <= 5
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
