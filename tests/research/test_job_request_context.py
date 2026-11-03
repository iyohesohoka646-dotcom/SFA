"""Deferred route jobs retain their submitting project context, never a later one."""
from contextvars import ContextVar
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from contract_driven_ai_flow.research.workbench.jobs import JobManager
from contract_driven_ai_flow.research.workbench.store import WorkbenchStore


def test_background_jobs_freeze_independent_request_contexts(tmp_path):
    owner = ContextVar('test-project-owner')
    release = Event()
    with ThreadPoolExecutor(max_workers=1) as executor:
        blocker = executor.submit(release.wait, 10)
        jobs = JobManager(WorkbenchStore(tmp_path), executor=executor)
        try:
            token = owner.set('project-A')
            a = jobs.submit('context-A', lambda job, cancel: {'receipt': {'owner': owner.get()}})
            owner.reset(token)
            token = owner.set('project-B')
            b = jobs.submit('context-B', lambda job, cancel: {'receipt': {'owner': owner.get()}})
            owner.reset(token)
            release.set()
            assert jobs.wait(a.id, 10).receipt['owner'] == 'project-A'
            assert jobs.wait(b.id, 10).receipt['owner'] == 'project-B'
        finally:
            release.set()
            jobs.close()
