"""Scientific application service shared by HTTP, batch CLI and other clients."""
from __future__ import annotations

import fnmatch
import hashlib
import hmac
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .agent.budget import CapturePolicy
from .agent.privacy import clean_text, sanitize_json
from .agent.source import read_source
from .models import ObservationEvent, ProbeSpec, SnapshotRef
from .probe_registry import ProbeRegistry
from .probes import ProbePool, control_action
from .processes import ProcessTree
from .runners import RunnerRegistry
from .store import ExperimentStore, encode

TERMINAL = {"completed", "failed", "cancelled", "interrupted", "timeout"}


@dataclass(frozen=True)
class RunHandle:
    run_id: str
    status: str
    interpreter: str
    source_digest: str
    capture_mode: str


@dataclass
class ActiveRun:
    id: str
    process: object
    tree: object
    listener: object
    token: str
    job_file: Path
    probes: list
    implicit_probes: bool
    connection: object = None
    writer: object = None
    write_lock: object = field(default_factory=threading.Lock)
    lock: object = field(default_factory=threading.RLock)
    done: object = field(default_factory=threading.Event)
    cancelled: bool = False
    paused_snapshot: str | None = None
    gates: dict = field(default_factory=dict)
    pending_probes: int = 0
    probe_condition: object = None
    terminal: dict | None = None
    counts: dict = field(default_factory=lambda: {"pass": 0, "fail": 0, "error": 0, "unknown": 0, "skipped": 0})
    output_bytes: dict = field(default_factory=lambda: {"stdout": 0, "stderr": 0})
    output_threads: list = field(default_factory=list)
    observer_error: str | None = None

    def __post_init__(self):
        self.probe_condition = threading.Condition(self.lock)


class ResearchService:
    def __init__(self, root: Path, *, probe_registry=None, runner_registry=None):
        self.root = Path(root).resolve()
        self.store = ExperimentStore(self.root)
        self.store.recover_runs()
        self.store.expire_artifacts()
        self.registry = probe_registry or ProbeRegistry()
        self.runners = runner_registry or RunnerRegistry()
        self.pool = ProbePool(self.registry, artifact_root=self.store.state)
        self._active = {}
        self._lock = threading.RLock()
        self._closed = False
        self._workbench = None

    @property
    def workbench(self):
        from .workbench.service import WorkbenchService
        with self._lock:
            if self._closed:
                raise ValueError('Scientific service is closed')
            if self._workbench is None:
                self._workbench = WorkbenchService(self)
            return self._workbench

    def calculation_status(self, run_id):
        with self._lock:
            active = self._active.get(run_id)
        if active is not None:
            with active.lock:
                if active.paused_snapshot is not None:
                    return 'paused'
        return self.store.run(run_id)['status']

    def start_analysis(self, script: Path, *, interpreter=None, arguments=(), mode="summary", probes=None,
                       adapters=(), watched_names=(), watched_lines=(), instrument="auto", capture=None, runner="python", expected_digest=None):
        if self._closed:
            raise ValueError("Research service is closed")
        with self._lock:
            if len(self._active) >= 4:
                raise ValueError("At most four analyses can run in one service")
        implementation = self.runners.resolve(runner)
        if Path(script).stat().st_size > 10 * 1024 * 1024:
            raise ValueError("Choose a Python script of at most 10 MiB")
        source = read_source(script)
        if expected_digest is not None and source.digest != expected_digest:
            raise ValueError('Source changed before launch; import and plan again')
        if Path(source.path).suffix != ".py" or len(source.text.encode("utf-8")) > 10 * 1024 * 1024:
            raise ValueError("Choose a Python script of at most 10 MiB")
        # Resolving a POSIX venv executable symlink selects the base interpreter
        # and silently changes sys.prefix and installed scientific dependencies.
        python = Path(interpreter or sys.executable).expanduser().absolute()
        if not python.is_file():
            raise ValueError("Selected Python interpreter is not a file")
        if len(arguments) > 256 or any(type(a) is not str or len(a) > 4096 for a in arguments):
            raise ValueError("Analysis arguments are too large")
        policy = CapturePolicy(**{**(capture or {}), "level": mode})
        configured = [ProbeSpec(id="default-finite", binding="*")] if probes is None else [ProbeSpec.model_validate(p) for p in probes]
        if len(configured) > 128:
            raise ValueError("An analysis can configure at most 128 probes")
        run = self.store.create_run(source.path, interpreter=str(python), source_digest=source.digest, name=Path(source.path).stem)
        self.store.archive_source(source.digest, source.text)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(2)
        listener.settimeout(0.5)
        token = secrets.token_urlsafe(32)
        jobs = self.store.state / "jobs"
        jobs.mkdir(exist_ok=True)
        job_file = jobs / (run["id"] + ".json")
        configuration = {"protocol_version": 1, "run_id": run["id"], "port": listener.getsockname()[1], "token": token,
            "interpreter": str(python), "runner": runner,
            "name": run["name"], "script": source.path, "source_digest": source.digest, "capture": asdict(policy),
            "artifact_root": str(self.store.state), "arguments": list(arguments), "adapters": list(adapters),
            "watched_names": list(watched_names), "watched_lines": list(watched_lines), "instrument": instrument,
            "gates": [{'binding': p.binding, 'target_keys': p.target_keys, 'excluded_keys': p.excluded_keys} for p in configured if p.enabled and p.policy != "continue"]}
        with os.fdopen(os.open(job_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w", encoding="utf-8") as stream:
            stream.write(encode(configuration))
        try:
            process = implementation.launch(configuration, job_file)
            tree = ProcessTree(process)
        except Exception:
            listener.close()
            job_file.unlink(missing_ok=True)
            self.store.append([ObservationEvent(run_id=run["id"], kind="run.finished", payload={"status": "failed", "reason": "process_start_failed"})])
            raise
        active = ActiveRun(run["id"], process, tree, listener, token, job_file, configured, probes is None)
        with self._lock:
            self._active[active.id] = active
        for name, pipe in (("stdout", process.stdout), ("stderr", process.stderr)):
            thread = threading.Thread(target=self._drain_output, args=(active, name, pipe), daemon=True)
            active.output_threads.append(thread)
            thread.start()
        threading.Thread(target=self._supervise, args=(active,), name="cdaf-analysis-" + active.id[:8], daemon=True).start()
        return RunHandle(active.id, "queued", str(python), source.digest, mode)

    @staticmethod
    def _drain_output(active, name, pipe):
        try:
            for chunk in iter(lambda: pipe.read(8192), b""):
                active.output_bytes[name] += len(chunk)
        finally:
            pipe.close()

    def _control(self, active, action, snapshot_id=None):
        if active.writer is not None:
            try:
                with active.write_lock:
                    active.writer.write(encode({"action": action, "snapshot_id": snapshot_id}).encode() + b"\n")
                    active.writer.flush()
            except OSError:
                active.observer_error = "control_channel_disconnected"

    def _resolve_gate(self, active, snapshot_id):
        with active.lock:
            gate = active.gates.get(snapshot_id)
            if not gate or gate["pending"] or not gate["arrived"] or gate.get("resolved"):
                return
            gate["resolved"] = True
            if "cancel" in gate["actions"]:
                active.cancelled = True
                self._control(active, "cancel", snapshot_id)
                self.store.append([ObservationEvent(run_id=active.id, kind="control.cancel_requested", snapshot_id=snapshot_id)])
            elif "pause" in gate["actions"]:
                active.paused_snapshot = snapshot_id
                self.store.append([ObservationEvent(run_id=active.id, kind="control.paused", snapshot_id=snapshot_id, payload={"reason": "probe_gate"})])
            else:
                self._control(active, "continue", snapshot_id)
                active.gates.pop(snapshot_id, None)

    def _probe_done(self, active, spec, snapshot, future):
        try:
            evaluated = future.result()
            self.store.append([ObservationEvent(run_id=active.id, kind="probe.evaluated", snapshot_id=snapshot.id,
                payload={"result": evaluated.model_dump(mode="json"), "probe": spec.model_dump(mode="json")})])
            with active.lock:
                active.counts[evaluated.status] += 1
                if spec.policy != "continue":
                    gate = active.gates[snapshot.id]
                    gate["pending"] -= 1
                    action = control_action(spec, evaluated)
                    if action:
                        gate["actions"].append(action)
            self._resolve_gate(active, snapshot.id)
        except Exception as error:
            active.observer_error = "probe_result_persistence:" + type(error).__name__
        finally:
            with active.probe_condition:
                active.pending_probes -= 1
                active.probe_condition.notify_all()

    def _observe(self, active, snapshot):
        from .agent.source import matches_probe
        matched = [p for p in active.probes if p.enabled and matches_probe(p.model_dump(mode='json'), snapshot.model_dump(mode='json'))]
        if active.implicit_probes and "finite_count" not in snapshot.statistics:
            matched = []
        gates = [p for p in matched if p.policy != "continue"]
        if gates:
            active.gates[snapshot.id] = {"pending": len(gates), "actions": [], "arrived": False}
        for spec in matched:
            with active.probe_condition:
                active.pending_probes += 1
            future = self.pool.submit(spec, snapshot)
            future.add_done_callback(lambda f, p=spec, s=snapshot: self._probe_done(active, p, s, f))

    def _ingest(self, active, events):
        if not isinstance(events, list) or len(events) > 2048:
            raise ValueError("Invalid scientific event batch")
        validated = []
        for raw in events:
            event = ObservationEvent.model_validate(sanitize_json(raw))
            if event.run_id != active.id:
                raise ValueError("Scientific event belongs to a different run")
            if event.kind == "run.finished":
                active.terminal = event.payload
            else:
                validated.append(event)
        self.store.append(validated)
        for event in validated:
            if event.kind == "value.observed":
                self._observe(active, SnapshotRef.model_validate(event.payload["snapshot"]))
            elif event.kind == "boundary.waiting":
                with active.lock:
                    gate = active.gates.get(event.snapshot_id)
                    if gate:
                        gate["arrived"] = True
                    else:
                        self._control(active, "continue", event.snapshot_id)
                self._resolve_gate(active, event.snapshot_id)

    def _supervise(self, active):
        reader = None
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    connection, address = active.listener.accept()
                except socket.timeout:
                    if active.process.poll() is not None:
                        break
                    continue
                candidate, authenticated = None, False
                try:
                    connection.settimeout(2)
                    candidate = connection.makefile("rb")
                    hello_line = candidate.readline(65537)
                    if len(hello_line) <= 65536 and hello_line.endswith(b"\n"):
                        hello = json.loads(hello_line)
                        authenticated = (isinstance(hello, dict) and address[0] == "127.0.0.1"
                            and hello.get("type") == "hello" and hello.get("protocol_version") == 1
                            and type(hello.get("run_id")) is str and hello["run_id"] == active.id
                            and type(hello.get("token")) is str and hmac.compare_digest(hello["token"], active.token))
                except (OSError, ValueError, TypeError):
                    pass
                finally:
                    if not authenticated:
                        if candidate:
                            candidate.close()
                        connection.close()
                if authenticated:
                    connection.settimeout(None)
                    active.connection, reader = connection, candidate
                    active.writer = connection.makefile("wb")
                    break
            active.listener.close()
            if reader is not None:
                if active.cancelled:
                    self._control(active, "cancel")
                while True:
                    line = reader.readline(1024 * 1024 + 1)
                    if not line:
                        break
                    if len(line) > 1024 * 1024 or not line.endswith(b"\n"):
                        raise ValueError("Scientific protocol frame exceeds byte limit")
                    message = json.loads(line, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Non-finite scientific JSON")))
                    if message.get("type") != "events":
                        raise ValueError("Unknown scientific message type")
                    self._ingest(active, message["events"])
            elif active.process.poll() is None:
                active.observer_error = "agent_startup_timeout"
                active.tree.terminate()
        except ConnectionResetError:
            active.observer_error = "collector_disconnected"
            # An abrupt native exit closes TCP before Windows publishes its exit
            # code. Preserve the analysis code rather than replacing it by 130.
            try:
                active.process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                active.tree.terminate()
        except Exception as error:
            active.observer_error = "collector_error:" + type(error).__name__
            active.tree.terminate()
        finally:
            active.listener.close()
            if active.connection:
                try:
                    active.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            for stream in (reader, active.writer):
                if stream:
                    stream.close()
            if active.connection:
                active.connection.close()
            code = active.process.wait()
            active.tree.close()
            for thread in active.output_threads:
                thread.join(1)
            deadline = time.monotonic() + 36
            with active.probe_condition:
                while active.pending_probes and time.monotonic() < deadline:
                    active.probe_condition.wait(max(0.01, deadline - time.monotonic()))
                if active.pending_probes:
                    active.observer_error = active.observer_error or "probe_wait_failed"
            status = "cancelled" if active.cancelled else (active.terminal or {}).get("status", "completed" if code == 0 and not active.observer_error else "failed")
            quality = "fail" if active.counts["fail"] else "degraded" if active.observer_error or active.counts["error"] or active.counts["unknown"] or active.counts["skipped"] else "pass" if sum(active.counts.values()) else "unconfigured"
            payload = {**(active.terminal or {}), "status": status, "exit_code": code, "quality": quality,
                "execution_status": (active.terminal or {}).get("status", "completed" if code == 0 else "failed"),
                "probe_counts": active.counts, "output_bytes": active.output_bytes, "observer_error": active.observer_error}
            self.store.append([ObservationEvent(run_id=active.id, kind="run.finished", payload=payload)])
            self.pool.release_run(active.id)
            active.job_file.unlink(missing_ok=True)
            active.done.set()
            with self._lock:
                self._active.pop(active.id, None)

    def wait(self, run_id, timeout=None):
        with self._lock:
            active = self._active.get(run_id)
        if active and not active.done.wait(timeout):
            raise TimeoutError("Scientific run is still active")
        return self.store.run(run_id)

    def cancel(self, run_id):
        with self._lock:
            active = self._active.get(run_id)
        if active is None:
            if self.store.run(run_id)["status"] in TERMINAL:
                return
            raise ValueError("This client does not own the active analysis; use its owning service")
        active.cancelled = True
        self.pool.cancel_run(run_id)
        self._control(active, "cancel")
        if not active.done.wait(2):
            active.tree.terminate()
            active.done.wait(3)

    def resume(self, run_id):
        with self._lock:
            active = self._active.get(run_id)
        if active is None or active.paused_snapshot is None:
            raise ValueError("Analysis is not paused in this service")
        snapshot_id, active.paused_snapshot = active.paused_snapshot, None
        self.store.append([ObservationEvent(run_id=run_id, kind="control.resumed", snapshot_id=snapshot_id)])
        self._control(active, "resume", snapshot_id)
        active.gates.pop(snapshot_id, None)

    def events(self, run_id, after=0, limit=1000):
        return [event.model_dump(mode="json") for event in self.store.events(run_id, after, limit)]

    def get_snapshot(self, snapshot_id):
        return self.store.snapshot(snapshot_id).model_dump(mode="json")

    def slice(self, snapshot_id, selectors):
        return self.store.slice(snapshot_id, selectors)

    def source(self, run_id):
        run = self.store.run(run_id)
        archive = self.store.state / 'sources' / (run['source_digest'] + '.txt')
        # Preserve CRLF: universal newline decoding changes version evidence.
        return {"path": run["script"], "digest": run["source_digest"], "code": archive.read_bytes().decode('utf-8')}

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._workbench is not None:
            self._workbench.close()
        with self._lock:
            identifiers = list(self._active)
        for run_id in identifiers:
            self.cancel(run_id)
        self.pool.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
