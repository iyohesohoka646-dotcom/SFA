"""Project TUI must attach to a live run instead of waiting for completion."""
import asyncio
from pathlib import Path

from contract_driven_ai_flow.research.service import ResearchService
from contract_driven_ai_flow.research.workbench.models import RunConfiguration
from contract_driven_ai_flow.terminal.app import ResearchTerminal
from contract_driven_ai_flow.terminal.client import LocalResearchClient


def test_project_terminal_observes_values_before_run_finishes(tmp_path):
    async def scenario():
        root = tmp_path / "lab"
        root.mkdir()
        (root / "main.py").write_text("import time\nX=7\ntime.sleep(10)\nY=X*2\n", encoding="utf-8")
        with ResearchService(tmp_path / "host") as service:
            application = service.ensure_project_application()
            project = application.open(root)
            revision = application.index(project.id)
            config = application.configuration(project.id)
            application.save_entries(project.id, [RunConfiguration(id="main", name="Main", kind="script", target="main.py")], expected_revision=config.revision)
            plan = application.plan(project.id, "main", revision_id=revision.id)
            terminal = ResearchTerminal(LocalResearchClient(service, None))
            async with terminal.run_test(size=(120, 36)) as pilot:
                try:
                    await asyncio.wait_for(terminal.execute("project.run", {"project_id": project.id, "plan_id": plan.id}), 5)
                    for _ in range(80):
                        await pilot.pause(0.025)
                        if any(v["name"] == "X" for v in terminal.values.values()):
                            break
                    assert any(v["name"] == "X" for v in terminal.values.values())
                    assert application.research(project.id).store.run(terminal.run_id)["status"] == "running"
                finally:
                    if terminal.run_id:
                        application.research(project.id).cancel(terminal.run_id)
    asyncio.run(scenario())
