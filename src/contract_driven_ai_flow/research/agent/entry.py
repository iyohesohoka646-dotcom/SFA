"""Bootstrap in the chosen scientific interpreter; standard-library imports."""
import json
import platform
import sys
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path

from .budget import CapturePolicy
from .control import AgentChannel
from .instrument import InstrumentPolicy
from .registry import AdapterRegistry
from .runner import run_script
from .sdk import TraceSession
from .transport import EventTransport


def main():
    job_file = Path(sys.argv[1])
    if job_file.stat().st_size > 128 * 1024:
        raise ValueError("Agent job configuration is too large")
    job = json.loads(job_file.read_text(encoding="utf-8"))
    channel = AgentChannel(job["port"], job["token"], job["run_id"], job.get("gates", []))
    try:
        policy = CapturePolicy(**job["capture"])
        registry = AdapterRegistry()
        registry.enable(job.get("adapters", []))
        transport = EventTransport(channel.publish, max_queue_events=policy.max_queue_events,
            publish_interval_ms=policy.publish_interval_ms, max_queue_bytes=policy.max_queue_bytes)
        trace = TraceSession(job["name"], transport, policy, run_id=job["run_id"], registry=registry,
            artifact_root=Path(job["artifact_root"]), observer=channel)
        dependencies = {}
        for name in ("numpy", "pandas", "scipy", "torch", "xarray", "pyarrow"):
            try:
                dependencies[name] = version(name)
            except PackageNotFoundError:
                pass
        trace.emit("environment.observed", {"executable": sys.executable, "python": platform.python_version(),
            "platform": platform.platform(), "dependencies": dependencies}, critical=True)
        instrument_policy = InstrumentPolicy(mode=job.get("instrument", "auto"), watched_names=tuple(job.get("watched_names", [])),
            watched_lines=tuple(job.get("watched_lines", [])), capture_policy=policy)
        if job.get("mode") == "project":
            # Project jobs carry an immutable manifest pointer, not the full
            # manifest, so the 128 KiB job document cap stays intact.
            from dataclasses import replace
            from .project_runner import run_project
            manifest_path = Path(job["manifest_path"])
            if manifest_path.stat().st_size > 32 * 1024 * 1024:
                raise ValueError("Project manifest is too large")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            project_policy = replace(instrument_policy, allowed_files=tuple(manifest))
            code = run_project(Path(job["root"]), job["entry"], session=trace, manifest=manifest,
                arguments=job.get("arguments", []), policy=project_policy, cwd=job.get("cwd"))
        else:
            code = run_script(Path(job["script"]), arguments=job.get("arguments", []), session=trace,
                policy=instrument_policy, expected_digest=job["source_digest"])
        raise SystemExit(code)
    finally:
        channel.close()


if __name__ == "__main__":
    main()
