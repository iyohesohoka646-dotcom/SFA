"""P2 finalizer safety: owned-run release, timeout, shared executor and launch faults."""

import socket as socket_module

import pytest

from contract_driven_ai_flow.research.projects.application import ProjectApplication
from contract_driven_ai_flow.research.service import ExecutionBudget, ResearchService


def single_file(tmp_path, body="X = 1\n"):
    script = tmp_path / "main.py"
    script.write_text(body, encoding="utf-8")
    return script


def test_final_receipt_write_failure_still_releases_owned_run(tmp_path, monkeypatch):
    budget = ExecutionBudget(1)
    service = ResearchService(tmp_path, budget=budget)
    script = single_file(tmp_path)
    append = service.store.append
    state = {"once": False}

    def interrupted(events):
        if not state["once"] and any(e.kind == "run.finished" and "probe_counts" in e.payload for e in events):
            state["once"] = True
            raise OSError("terminal receipt write interrupted")
        return append(events)

    monkeypatch.setattr(service.store, "append", interrupted)
    try:
        handle = service.start_analysis(script)
        with service._lock:
            active = service._active[handle.run_id]
        assert active.done.wait(6), "A terminal write fault stranded the owned run"
        assert handle.run_id not in service._active
        assert budget.acquire(), "A terminal write fault leaked the execution permit"
        budget.release()
        assert service.store.run(handle.run_id)["summary"].get("observer_error"), "The observation gap was hidden"
    finally:
        service.close()


def test_configured_timeout_returns_permit_and_reports_timeout(tmp_path):
    budget = ExecutionBudget(1)
    service = ResearchService(tmp_path, budget=budget)
    script = single_file(tmp_path, "import time\nX = 1\ntime.sleep(30)\n")
    try:
        handle = service.start_analysis(script, timeout_seconds=1)
        record = service.wait(handle.run_id, timeout=30)
        assert record["status"] == "timeout"
        assert budget.acquire(), "A timed-out run leaked the execution permit"
        budget.release()
    finally:
        service.close()


def test_project_jobs_share_application_owned_executor(tmp_path):
    app = ProjectApplication(tmp_path / "host")
    roots = []
    try:
        for name in ("a", "b"):
            root = tmp_path / name
            root.mkdir()
            (root / "main.py").write_text("X=1\n", encoding="utf-8")
            roots.append(app.open(root))
        first = app.workbench(roots[0].id).jobs
        second = app.workbench(roots[1].id).jobs
        assert first.executor is second.executor and first.admission is second.admission
        assert not first._owns_executor and not first._owns_admission
        first.close()
        task = second.submit("probe", lambda task, cancel: {})
        assert second.wait(task.id, 5).status == "completed"
    finally:
        app.close()


def test_prelaunch_socket_fault_returns_permit(tmp_path, monkeypatch):
    budget = ExecutionBudget(1)
    service = ResearchService(tmp_path, budget=budget)
    script = single_file(tmp_path)

    def unavailable(*args, **kwargs):
        raise OSError("listener unavailable")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(socket_module, "socket", unavailable)
            with pytest.raises(OSError):
                service.start_analysis(script)
        assert budget.acquire(), "A failed preparation leaked the only execution permit"
        budget.release()
        assert all(run["status"] == "failed" for run in service.store.runs())
    finally:
        service.close()


import logging

def test_final_receipt_failure_keeps_calculation_success_distinct(tmp_path, monkeypatch):
    service=ResearchService(tmp_path,budget=ExecutionBudget(1))
    script=tmp_path/'main.py';script.write_text('X=1\n')
    append=service.store.append; failed=False
    def interrupted(events):
        nonlocal failed
        if not failed and any(e.kind=='run.finished' and 'probe_counts' in e.payload for e in events):
            failed=True; raise OSError('receipt interrupted')
        return append(events)
    monkeypatch.setattr(service.store,'append',interrupted)
    try:
        handle=service.start_analysis(script); record=service.wait(handle.run_id,8)
        assert record['status']=='completed', 'Observation persistence must not invent a failed calculation'
        assert record['summary']['execution_status']=='completed'
        assert record['summary']['quality']=='degraded' and record['summary']['observer_error']
    finally:service.close()


def test_incomplete_child_project_receipt_degrades_observation_without_losing_success(tmp_path, monkeypatch):
    service=ResearchService(tmp_path);script=tmp_path/'main.py';script.write_text('X=1\n')
    ingest=service._ingest
    def incomplete(active,events):
        for event in events:
            if event['kind']=='run.finished':
                event['payload']['project_execution']={'complete':False,'project_id':'p','project_revision_id':'r'}
                event['payload']['quality']='pass'
        return ingest(active,events)
    monkeypatch.setattr(service,'_ingest',incomplete)
    try:
        handle=service.start_analysis(script); record=service.wait(handle.run_id,8)
        assert record['status']=='completed'
        assert record['summary']['quality']=='degraded', record['summary']
    finally:service.close()


def test_double_receipt_write_failure_is_reported_and_releases_capacity(tmp_path, monkeypatch, caplog):
    service=ResearchService(tmp_path,budget=ExecutionBudget(1));script=tmp_path/'main.py';script.write_text('X=1\n')
    append=service.store.append
    def unavailable(events):
        if any(e.kind=='run.finished' and 'probe_counts' in e.payload for e in events):
            raise OSError('receipt store unavailable')
        return append(events)
    monkeypatch.setattr(service.store,'append',unavailable)
    try:
        with caplog.at_level(logging.ERROR):
            handle=service.start_analysis(script)
            with service._lock:active=service._active[handle.run_id]
            assert active.done.wait(8)
        assert service._budget.acquire();service._budget.release()
        assert 'receipt' in caplog.text.lower() and ('persist' in caplog.text.lower() or 'unavailable' in caplog.text.lower()), 'Double persistence failure was silently discarded'
    finally:service.close()
