"""Scientific application service shared by HTTP, batch CLI and other clients."""
from __future__ import annotations

import fnmatch
import errno
import hashlib
import hmac
import json
import logging
import math
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


class ExecutionBudget:
    """One global at-most-N computation budget shared by project services.

    The owning application passes one instance to every attached service so the
    cap covers project services and the legacy service together.
    """

    def __init__(self, limit: int = 4):
        self.limit = int(limit)
        self._semaphore = threading.BoundedSemaphore(self.limit)

    def acquire(self) -> bool:
        return self._semaphore.acquire(blocking=False)

    def release(self) -> None:
        try:
            self._semaphore.release()
        except ValueError:
            pass


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
    budget: object = None
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
    timeout_seconds: float | None = None
    timed_out: bool = False
    timer: object = None

    def __post_init__(self):
        self.probe_condition = threading.Condition(self.lock)


class ResearchService:
    def __init__(
        self,
        root: Path,
        *,
        probe_registry=None,
        runner_registry=None,
        budget=None,
        job_executor=None,
        task_admission=None,
        task_admission_limit=16,
    ):
        self.root = Path(root).resolve()
        self._budget = budget
        # Optional application-owned shared background resources. Standalone
        # services keep their own legacy JobManager defaults.
        self._job_executor = job_executor
        self._task_admission = task_admission
        self._task_admission_limit = task_admission_limit
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
        # The project application is attached by its lifecycle owner (the HTTP
        # server) or lazily created and then owned by this standalone service.
        self.project_application = None
        self._owns_project_application = False

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

    @staticmethod
    def _validate_timeout(timeout_seconds):
        if timeout_seconds is None:
            return None
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
            raise ValueError("timeout_seconds must be a positive finite number of seconds")
        value = float(timeout_seconds)
        if not math.isfinite(value) or value <= 0 or value > 86400:
            raise ValueError(
                "timeout_seconds must be a positive finite number of seconds no greater than 86400"
            )
        return value

    def start_analysis(self, script: Path, *, interpreter=None, arguments=(), mode="summary", probes=None,
                       adapters=(), watched_names=(), watched_lines=(), instrument="auto", capture=None, runner="python", expected_digest=None,
                       cwd=None, env=None, project_job=None, run_environment=None, timeout_seconds=None):
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
        timeout_value = self._validate_timeout(timeout_seconds)
        if self._budget is not None:
            if not self._budget.acquire():
                raise ValueError("At most four analyses can run across the application")
            budget_held = True
        else:
            budget_held = False
        # Every owned resource and the permit are released exactly once by the
        # single preparation/launch guard below; a failed launch still marks the
        # created run failed with its sanitized actual reason.
        run = None
        listener = None
        job_file = None
        process = None
        tree = None
        active = None
        try:
            run = self.store.create_run(source.path, interpreter=str(python), source_digest=source.digest, name=Path(source.path).stem,
                environment=dict(run_environment) if run_environment else None)
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
            if cwd is not None:
                configuration["cwd"] = str(cwd)
            if env:
                configuration["env"] = {str(k): str(v) for k, v in dict(env).items()}
            if project_job:
                configuration.update(project_job)
            with os.fdopen(os.open(job_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w", encoding="utf-8") as stream:
                stream.write(encode(configuration))
            process = implementation.launch(configuration, job_file)
            tree = ProcessTree(process)
            active = ActiveRun(run["id"], process, tree, listener, token, job_file, configured, probes is None,
                budget=self._budget if budget_held else None, timeout_seconds=timeout_value)
            with self._lock:
                self._active[active.id] = active
            for name, pipe in (("stdout", process.stdout), ("stderr", process.stderr)):
                thread = threading.Thread(target=self._drain_output, args=(active, name, pipe), daemon=True)
                active.output_threads.append(thread)
                thread.start()
            if timeout_value:
                active.timer = threading.Timer(timeout_value, self._expire_run, args=(active,))
                active.timer.daemon = True
                active.timer.start()
            threading.Thread(target=self._supervise, args=(active,), name="cdaf-analysis-" + active.id[:8], daemon=True).start()
            return RunHandle(active.id, "queued", str(python), source.digest, mode)
        except BaseException as error:
            self._fail_start(run, active, process, tree, listener, job_file, budget_held, error)
            raise

    def _fail_start(self, run, active, process, tree, listener, job_file, budget_held, error):
        if active is not None:
            with self._lock:
                self._active.pop(active.id, None)
            timer = getattr(active, "timer", None)
            if timer is not None:
                try:
                    timer.cancel()
                except Exception:
                    pass
        if tree is not None:
            try:
                tree.terminate()
            except Exception:
                pass
            try:
                tree.close()
            except Exception:
                pass
        elif process is not None:
            try:
                process.kill()
            except Exception:
                pass
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        if job_file is not None:
            try:
                job_file.unlink(missing_ok=True)
            except OSError:
                pass
        if run is not None:
            reason = clean_text(str(error), 512) or type(error).__name__
            try:
                self.store.append([ObservationEvent(run_id=run["id"], kind="run.finished", payload={"status": "failed", "reason": reason})])
            except Exception:
                pass
        if budget_held and self._budget is not None:
            self._budget.release()

    def _expire_run(self, active):
        with active.lock:
            if active.done.is_set():
                return
            active.timed_out = True
        try:
            active.tree.terminate()
        except Exception:
            pass

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
            except (OSError, ValueError):
                # A teardown/peer race can close the writer between the None check
                # and the write; a closed pipe raises OSError and a closed file
                # object raises ValueError. Real application errors still surface.
                active.observer_error = active.observer_error or "control_channel_disconnected"

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
            active.observer_error = active.observer_error or "collector_disconnected"
            # An abrupt native exit closes TCP before Windows publishes its exit
            # code. Preserve the analysis code rather than replacing it by 130.
            try:
                active.process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                active.tree.terminate()
        except BaseException as error:
            active.observer_error = active.observer_error or ("collector_error:" + type(error).__name__)
            try:
                active.tree.terminate()
            except BaseException:
                pass
        finally:
            # Unconditional teardown and finalization. Every owned listener,
            # connection/writer/reader, process tree, output thread, probe permit,
            # job file, timer, active-map entry and execution budget is handled
            # exactly once here: a failure in one guarded step can never skip the
            # rest, and the terminal receipt is written no matter which stage failed.
            stage = "teardown"
            errors = []
            failed = object()

            def guard(label, action):
                nonlocal stage
                stage = label
                try:
                    return action()
                except BaseException as error:
                    errors.append(label + ":" + type(error).__name__)
                    detail = clean_text(str(error), 200) or type(error).__name__
                    active.observer_error = active.observer_error or (label + ":" + detail)
                    return failed

            guard("listener_close", active.listener.close)
            connection = active.connection
            if connection is not None:
                def shutdown_connection():
                    try:
                        connection.shutdown(socket.SHUT_RDWR)
                    except OSError as error:
                        if error.errno != errno.ENOTCONN:
                            raise
                guard("connection_shutdown", shutdown_connection)
            for stream in (reader, active.writer):
                if stream is not None:
                    guard("stream_close", stream.close)
            if connection is not None:
                guard("connection_close", connection.close)
            waited = guard("process_wait", active.process.wait)
            if waited is failed:
                guard("process_terminate", active.tree.terminate)
                code = 1
            else:
                code = waited if isinstance(waited, int) else 1
            guard("tree_close", active.tree.close)
            for thread in active.output_threads:
                guard("output_join", lambda thread=thread: thread.join(1))
            probe_deadline = time.monotonic() + 36

            def wait_probes():
                with active.probe_condition:
                    while active.pending_probes and time.monotonic() < probe_deadline:
                        active.probe_condition.wait(max(0.01, probe_deadline - time.monotonic()))

            guard("probe_wait", wait_probes)
            if active.pending_probes:
                active.observer_error = active.observer_error or "probe_wait_failed"
            # The child terminal payload (including project_execution and its own
            # observer_error) is preserved; the finalizer never blanks it with a
            # later None/pass. A timeout or cancel still wins over the child status.
            terminal = dict(active.terminal or {})
            if active.cancelled:
                status = "cancelled"
            elif active.timed_out:
                status = "timeout"
            else:
                status = terminal.get("status", "completed" if code == 0 and not active.observer_error else "failed")
            execution_status = status if status in ("timeout", "cancelled") else terminal.get("execution_status", "completed" if code == 0 else "failed")
            observer_error = active.observer_error or terminal.get("observer_error")
            receipt = terminal.get("project_execution")
            if isinstance(receipt, dict) and receipt.get("complete") is False:
                observer_error = observer_error or "project_evidence_incomplete"
            quality = "fail" if active.counts["fail"] else "degraded" if observer_error or active.counts["error"] or active.counts["unknown"] or active.counts["skipped"] else "pass" if sum(active.counts.values()) else "unconfigured"
            if terminal.get("quality") == "fail":
                quality = "fail"
            elif quality in ("pass", "unconfigured") and terminal.get("quality") == "degraded":
                quality = "degraded"
            payload = {**terminal, "status": status, "exit_code": code, "quality": quality,
                "execution_status": execution_status, "probe_counts": active.counts,
                "output_bytes": active.output_bytes, "observer_error": observer_error}
            stage = "finalize"
            try:
                self.store.append([ObservationEvent(run_id=active.id, kind="run.finished", payload=payload)])
            except BaseException as error:
                detail = clean_text(str(error), 200) or type(error).__name__
                active.observer_error = active.observer_error or ("terminal_receipt:" + detail)
                errors.append("terminal_receipt:" + type(error).__name__)
                # Exactly one best-effort fallback terminal write carrying the
                # actual error; an unpersisted completion is never reported as a
                # pass, and the observer gap stays visible on the live run.
                fallback = {**payload, "observer_error": active.observer_error,
                    "quality": "fail" if payload.get("quality") == "fail" else "degraded"}
                try:
                    self.store.append([ObservationEvent(run_id=active.id, kind="run.finished", payload=fallback)])
                except BaseException as second:
                    errors.append("terminal_receipt_fallback:" + type(second).__name__)
                    active.observer_error = active.observer_error or ("terminal_receipt_unpersisted:" + type(second).__name__)
                    logging.getLogger(__name__).error("Run %s terminal receipt could not be persisted (%s)", active.id, type(second).__name__)
            # Ordered cleanup: the done flag is set only after the active entry and
            # the execution permit are gone, so a waiting client sees capacity.
            stage = "cleanup"
            guard("pool_release_run", lambda: self.pool.release_run(active.id))
            guard("job_file_unlink", lambda: active.job_file.unlink(missing_ok=True))
            timer = getattr(active, "timer", None)
            if timer is not None:
                guard("timer_cancel", timer.cancel)
            with self._lock:
                self._active.pop(active.id, None)
            if active.budget is not None:
                budget, active.budget = active.budget, None
                guard("budget_release", budget.release)
            active.done.set()

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
        timer = getattr(active, "timer", None)
        if timer is not None:
            timer.cancel()
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

    def ensure_project_application(self, models=None):
        """Return the shared ProjectApplication, creating and owning one lazily.

        A service that already has an application attached by its lifecycle
        owner (the HTTP server) reuses it unchanged; a standalone service
        creates one and closes only that application. The created application
        shares this service's computation budget so the two never double-count
        the same subprocess/admission limits.
        """
        with self._lock:
            if self.project_application is not None:
                return self.project_application
            from .projects.application import ProjectApplication

            budget = self._budget
            if budget is None:
                budget = ExecutionBudget(4)
                self._budget = budget
            application = ProjectApplication(self.root, models=models)
            # Rebinding before any per-project service exists keeps the exact
            # same budget object shared with legacy analysis execution.
            application.budget = budget
            self.project_application = application
            self._owns_project_application = True
            return application

    def close(self):
        if self._closed:
            return
        self._closed = True
        application = self.project_application
        owned = self._owns_project_application
        if self._workbench is not None:
            self._workbench.close()
        with self._lock:
            identifiers = list(self._active)
        for run_id in identifiers:
            self.cancel(run_id)
        self.pool.close()
        # Only an application this service created is closed here. An attached
        # application belongs to its HTTP/terminal lifecycle owner, and a child
        # service created by an application never recursively closes it.
        self.project_application = None
        self._owns_project_application = False
        if owned and application is not None:
            application.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
