"""UI-neutral background tasks. Geometry changes never submit jobs."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time

from ..models import timestamp
from .models import TaskRecord
from .ownership import current_owner


class JobManager:
    def __init__(self, store, *, max_workers=3):
        self.store = store
        self.owner = current_owner()
        self.store.recover()
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='cdaf-workbench')
        self._active = {}
        self._lock = threading.RLock()
        self._closed = False

    def update(self, task_id, **updates):
        with self._lock:
            task = self.get(task_id).model_copy(update={**updates, 'updated_at': timestamp()})
            self.store.put('tasks', task_id, task)
            return task

    def submit(self, kind, function, *, plan_id=None, receipt=None):
        with self._lock:
            if self._closed or len(self._active) >= 16:
                raise ValueError('Task queue is full or closed')
            task = TaskRecord(kind=kind, plan_id=plan_id, receipt={**(receipt or {}), '_owner': self.owner})
            self.store.put('tasks', task.id, task)
            cancel = threading.Event()
            self._active[task.id] = (cancel, None)
            future = self.executor.submit(self._run, task, cancel, function)
            if task.id in self._active:
                self._active[task.id] = (cancel, future)
            return task

    def _run(self, task, cancel, function):
        try:
            if cancel.is_set():
                raise InterruptedError()
            task = self.update(task.id, status='running')
            result = function(task, cancel) or {}
            if cancel.is_set():
                raise InterruptedError()
            self.update(task.id, **{**result, 'status': result.get('status', 'completed'), 'progress': 1})
        except InterruptedError:
            self.update(task.id, status='cancelled', message='Task cancelled')
        except Exception as error:
            self.update(task.id, status='failed', message=f'Task failed ({type(error).__name__})')
        finally:
            with self._lock:
                self._active.pop(task.id, None)

    def get(self, task_id):
        return TaskRecord.model_validate(self.store.get('tasks', task_id))

    def list(self):
        return self.store.list('tasks')

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
            if task.status not in ('queued', 'running'):
                return task
            threading.Event().wait(.02)
        raise TimeoutError('Task is still active')

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for cancel, _ in self._active.values():
                cancel.set()
        self.executor.shutdown(wait=True)
