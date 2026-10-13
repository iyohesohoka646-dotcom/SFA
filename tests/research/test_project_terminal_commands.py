"""P3 terminal command tests: explicit project ownership, never ambient state."""

import asyncio
import types

import pytest

from contract_driven_ai_flow.application.commands import dispatch
from contract_driven_ai_flow.research.service import ExecutionBudget, ResearchService
from contract_driven_ai_flow.terminal.commands import parse_command


def test_parse_project_info_preserves_explicit_project_id():
    name, args = parse_command('/project info {"project_id": "p123"}')
    assert name == "project.info"
    assert args == {"project_id": "p123"}


def test_parse_project_open_uses_path_only():
    name, args = parse_command('/project open {"path": "C:\\\\lab dir\\\\p"}')
    assert name == "project.open"
    assert args["path"] == "C:\\lab dir\\p"


def test_parse_project_rejects_non_object_arguments():
    with pytest.raises(ValueError):
        parse_command("/project info []")


class _Recorded(types.SimpleNamespace):
    def model_dump(self, mode="json"):
        return vars(self)


class _FakeApplication:
    def __init__(self):
        self.opened = []

    def open(self, path):
        self.opened.append(path)
        return _Recorded(id="p-open", root=str(path))


def test_dispatch_project_reuses_attached_application(tmp_path):
    application = _FakeApplication()
    service = types.SimpleNamespace(root=tmp_path, project_application=application, budget=None)
    result = asyncio.run(dispatch("project.open", {"path": str(tmp_path / "p")}, service=service, settings=None))
    assert result.status == "ok"
    assert result.data["id"] == "p-open"
    assert application.opened == [str(tmp_path / "p")]


def test_research_service_owns_lazily_created_project_application(tmp_path):
    budget = ExecutionBudget(4)
    service = ResearchService(tmp_path, budget=budget)
    try:
        application = service.ensure_project_application()
        assert service.project_application is application
        assert application.budget is budget
    finally:
        service.close()


def test_research_service_does_not_close_attached_application(tmp_path):
    closed = []
    service = ResearchService(tmp_path)
    service.project_application = types.SimpleNamespace(close=lambda: closed.append(True))
    service.close()
    assert closed == []



def _fake_project_client():
    import types as _types

    from contract_driven_ai_flow.application.commands import CommandResult

    class FakeClient:
        def __init__(self):
            self.calls = []
            self.events_calls = []

        async def command(self, name, arguments):
            self.calls.append((name, dict(arguments)))
            if name == "project.open":
                return CommandResult(status="ok", data={"id": arguments["path"]})
            if name == "project.run":
                return CommandResult(
                    status="ok",
                    data={"id": "task-1", "status": "running"},
                    run_id="run-B",
                    project_id=arguments["project_id"],
                )
            return CommandResult(
                status="ok",
                data={},
                run_id=arguments.get("run_id"),
                project_id=arguments.get("project_id"),
            )

        async def events(self, run_id, after=0, project_id=None):
            self.events_calls.append((run_id, project_id))
            if False:  # pragma: no cover - keeps this an async generator
                yield None

        async def close(self):
            pass

    return FakeClient()


def test_terminal_project_run_replaces_previous_ownership(tmp_path):
    from contract_driven_ai_flow.terminal.app import ResearchTerminal

    async def scenario():
        client = _fake_project_client()
        terminal = ResearchTerminal(client)
        async with terminal.run_test(size=(120, 36)) as pilot:
            await terminal.execute("project.open", {"path": "A"})
            assert terminal.project_id == "A"
            await terminal.execute("project.run", {"project_id": "B", "plan_id": "p1"})
            assert terminal.project_id == "B"
            for _ in range(40):
                await pilot.pause(0.02)
                if client.events_calls:
                    break
            assert client.events_calls[-1] == ("run-B", "B")
            # Opening a new project must not silently retarget the run routing.
            await terminal.execute("project.open", {"path": "C"})
            assert terminal.project_id == "C"
            await terminal.execute("vars", {"project_id": "B", "run_id": "run-B"})
            assert client.calls[-1] == ("vars", {"project_id": "B", "run_id": "run-B"})

    asyncio.run(scenario())


def test_terminal_direct_handlers_carry_project_scope(tmp_path):
    import types

    from contract_driven_ai_flow.terminal.app import ResearchTerminal

    async def scenario():
        client = _fake_project_client()
        terminal = ResearchTerminal(client)
        async with terminal.run_test(size=(120, 36)) as pilot:
            terminal.project_id = "B"
            terminal.run_id = "run-B"
            terminal.on_data_table_row_selected(
                types.SimpleNamespace(row_key=types.SimpleNamespace(value="snap-1"))
            )
            for _ in range(40):
                await pilot.pause(0.02)
                if any(call[0] == "inspect" for call in client.calls):
                    break
            inspect = [call for call in client.calls if call[0] == "inspect"][-1]
            assert inspect[1]["snapshot_id"] == "snap-1"
            assert inspect[1]["project_id"] == "B"
            terminal._last_interrupt = 0
            await terminal.action_cancel_or_quit()
            cancel = [call for call in client.calls if call[0] == "cancel"][-1]
            assert cancel[1] == {"run_id": "run-B", "project_id": "B"}

    asyncio.run(scenario())

def test_local_client_events_choose_owned_project_and_legacy_service(tmp_path):
    import types

    from contract_driven_ai_flow.terminal.client import LocalResearchClient

    class Store:
        def run(self, run_id):
            return {"status": "completed"}

    def page():
        return [{"sequence": 1, "kind": "run.finished", "payload": {"status": "completed"}}]

    class FakeResearch:
        def __init__(self, project_id):
            self.project_id = project_id
            self.store = Store()

        def events(self, run_id, after=0, limit=256):
            return page()

    class FakeApplication:
        def __init__(self):
            self.requested = []

        def research(self, project_id):
            self.requested.append(project_id)
            return FakeResearch(project_id)

    class LegacyService:
        root = tmp_path

        def __init__(self):
            self.store = Store()
            self.project_application = None

        def events(self, run_id, after=0, limit=256):
            return page()

    application = FakeApplication()
    service = types.SimpleNamespace(root=tmp_path, project_application=application, budget=None)
    client = LocalResearchClient(service, settings=None)

    async def project_events():
        return [event async for event in client.events("run-1", project_id="p-B")]

    events = asyncio.run(project_events())
    assert application.requested == ["p-B"]
    assert events[0]["kind"] == "run.finished"

    legacy = LocalResearchClient(LegacyService(), settings=None)

    async def legacy_events():
        return [event async for event in legacy.events("run-1")]

    assert asyncio.run(legacy_events())[0]["kind"] == "run.finished"


def test_remote_client_uses_explicit_project_event_prefix():
    from contract_driven_ai_flow.terminal.client import ResearchClient

    assert ResearchClient._paths("r1", "p1") == (
        "/api/v1/research/projects/p1/runs/r1/events",
        "/api/v1/research/projects/p1/runs/r1",
    )
    assert ResearchClient._paths("r1", None) == (
        "/api/v1/research/runs/r1/events",
        "/api/v1/research/runs/r1",
    )