"""UI-neutral background tasks. Geometry changes never submit jobs."""

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
import threading
import time

from ..agent.privacy import clean_text
from ..models import timestamp
from .models import TaskRecord
from .ownership import current_owner

QUEUE_LIMIT = 16


class JobManager:
    def __init__(
        self,
        store,
        *,
        max_workers=3,
        executor=None,
        admission=None,
        admission_limit=QUEUE_LIMIT,
    ):
        self.store = store
        self.owner = current_owner()
        self.store.recover()
        # A shared application-owned executor/admission budget keeps the
        # background worker cap application-wide instead of per project. A
        # standalone manager keeps the legacy private 3-thread / 16-queue
        # defaults and owns (and shuts) its own executor.
        self._owns_executor = executor is None
        self.executor = executor or ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="cdaf-workbench"
        )
        self._owns_admission = admission is None
        self.admission = admission or threading.BoundedSemaphore(int(admission_limit))
        self._active = {}
        # Tasks whose durable work is already committed; a late cancellation
        # must never rewrite them as cancelled. Process-local, cleared on finish.
        self._committed: set = set()
        self._lock = threading.RLock()
        self._closed = False

    def update(self, task_id, **updates):
        with self._lock:
            task = self.get(task_id).model_copy(
                update={**updates, "updated_at": timestamp()}
            )
            self.store.put("tasks", task_id, task)
            return task

    def submit(self, kind, function, *, plan_id=None, receipt=None):
        with self._lock:
            if self._closed:
                raise ValueError("Task queue is full or closed")
        # The queue permit is taken before the task is durable so a full queue is
        # rejected explicitly instead of silently piling up unbounded work.
        if not self.admission.acquire(blocking=False):
            raise ValueError("Task queue is full or closed")
        task = None
        persisted = False
        released = False
        try:
            with self._lock:
                if self._closed:
                    raise ValueError("Task queue is full or closed")
                task = TaskRecord(
                    kind=kind,
                    plan_id=plan_id,
                    receipt={**(receipt or {}), "_owner": self.owner},
                )
                # A store failure here happens before any future exists and
                # before the task is durable: only the permit must be returned.
                self.store.put("tasks", task.id, task)
                persisted = True
                cancel = threading.Event()
                self._active[task.id] = (cancel, None)
                # A route may use request-bound project services. A fresh copy
                # per job survives request teardown without sharing later requests.
                future = self.executor.submit(copy_context().run, self._run, task, cancel, function)
                if task.id in self._active:
                    self._active[task.id] = (cancel, future)
            return task
        except BaseException as error:
            # Own only this submission's placeholder: pop it so a rejected
            # executor never leaves a phantom active owner behind.
            with self._lock:
                if task is not None:
                    self._active.pop(task.id, None)
            # Persist an honest failed state, but only for a task that actually
            # reached the store; a pre-durable store fault must not fabricate one.
            if persisted:
                try:
                    reason = clean_text(str(error), 512) or type(error).__name__
                    self.update(
                        task.id,
                        status="failed",
                        message=f"Task failed to start ({type(error).__name__}): {reason}",
                    )
                except BaseException:
                    pass
            # The future never owned the permit on this path, so the submitting
            # thread returns it exactly once.
            if not released:
                released = True
                self.admission.release()
            raise

    def _run(self, task, cancel, function):
        try:
            if cancel.is_set():
                raise InterruptedError()
            task = self.update(task.id, status="running")
            result = function(task, cancel) or {}
            with self._lock:
                committed = task.id in self._committed
            if cancel.is_set() and not committed:
                raise InterruptedError()
            self.update(
                task.id,
                **{
                    **result,
                    "status": result.get("status", "completed"),
                    "progress": 1,
                },
            )
        except InterruptedError:
            self.update(task.id, status="cancelled", message="Task cancelled")
        except Exception as error:
            reason = clean_text(str(error), 512) or type(error).__name__
            self.update(
                task.id,
                status="failed",
                message=f"Task failed ({type(error).__name__}): {reason}",
            )
        finally:
            with self._lock:
                self._active.pop(task.id, None)
                self._committed.discard(task.id)
            # Cancelled queued work holds its permit until it is finalized here.
            self.admission.release()

    def mark_committed(self, task_id) -> None:
        """Record that a task's durable side effects are already committed.

        A cancellation that arrives after this point must not rewrite a real
        completion as cancelled, so the final recorded status stays truthful.
        """
        with self._lock:
            self._committed.add(task_id)

    def has_active(self) -> bool:
        """True while any queued or running task still owns this manager."""
        with self._lock:
            return bool(self._active)

    def get(self, task_id):
        return TaskRecord.model_validate(self.store.get("tasks", task_id))

    def list(self):
        return self.store.list("tasks")

    def cancel(self, task_id):
        with self._lock:
            active = self._active.get(task_id)
            if active:
                active[0].set()
        return self.get(task_id)

    def wait(self, task_id, timeout=120):
        started = time.monotonic()
        while time.monotonic() - started < timeout:
            task = self.get(task_id)
            if task.status not in ("queued", "running"):
                return task
            threading.Event().wait(0.02)
        raise TimeoutError("Task is still active")

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            active = dict(self._active)
        for cancel, _ in active.values():
            cancel.set()
        # Wait only for this manager's own futures; another project's queued or
        # running work is never cancelled and the shared executor is never shut.
        for _, future in active.values():
            if future is None:
                continue
            try:
                future.result()
            except BaseException:
                pass
        if self._owns_executor:
            self.executor.shutdown(wait=True)
