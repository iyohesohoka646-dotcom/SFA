"""A terminal status can commit between an empty event page and the status read."""
import json
import sys

import pytest
from fastapi.testclient import TestClient

from contract_driven_ai_flow.research.models import ObservationEvent
from contract_driven_ai_flow.research.routes import create_research_app


@pytest.mark.parametrize("project_scope", [False, True])
@pytest.mark.parametrize("tail_size", [1, 600])
def test_stream_drains_final_events_after_observing_terminal_state(
    tmp_path, monkeypatch, project_scope, tail_size
):
    with TestClient(create_research_app(tmp_path / "host", token="stream-race")) as client:
        prefix = "/api/v1/research"
        service = client.app.state.research
        if project_scope:
            root = tmp_path / "lab"
            root.mkdir()
            (root / "main.py").write_text("X=7\n")
            project = client.app.state.projects.open(root)
            service = client.app.state.projects.research(project.id)
            prefix += "/projects/" + project.id
        run = service.store.create_run("main.py", interpreter=sys.executable, source_digest="frozen")
        original = service.events
        first = True

        def finish_after_empty_page(run_id, after=0, limit=256):
            nonlocal first
            if first:
                first = False
                assert original(run_id, after, limit) == []
                service.store.append([
                    *[ObservationEvent(run_id=run_id, kind="diagnostic", payload={"ordinal": i}) for i in range(tail_size - 1)],
                    ObservationEvent(run_id=run_id, kind="run.finished", payload={"status": "completed"}),
                ])
                return []
            return original(run_id, after, limit)

        monkeypatch.setattr(service, "events", finish_after_empty_page)
        response = client.get(prefix + "/runs/" + run["id"] + "/events", headers={"Authorization": "Bearer stream-race"})
        assert response.status_code == 200
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        assert len(events) == tail_size
        assert events[-1]["kind"] == "run.finished"
        assert len({event["sequence"] for event in events}) == tail_size
