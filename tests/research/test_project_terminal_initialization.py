"""Concurrent terminal list/create must share one owned session registry."""
from concurrent.futures import ThreadPoolExecutor
import threading

from fastapi.testclient import TestClient

from contract_driven_ai_flow.research.routes import create_research_app
from contract_driven_ai_flow.research.workbench import terminal


def test_concurrent_first_terminal_requests_keep_the_created_session(tmp_path, monkeypatch):
    entered, release, second = threading.Event(), threading.Event(), threading.Event()
    instances = []

    class Registry:
        def __init__(self, *args, **kwargs):
            self.sessions = []
            instances.append(self)
            if len(instances) == 1:
                entered.set()
                assert release.wait(5)
            else:
                second.set()

        def list(self):
            return self.sessions

        def create(self, **kwargs):
            self.sessions.append({"id": "owned-session", "profile": "python"})
            return self.sessions[-1]

        def get(self, key):
            return next(s for s in self.sessions if s["id"] == key)

        def close(self):
            pass

    with TestClient(create_research_app(tmp_path / "host", token="terminal-race")) as client:
        root = tmp_path / "lab"
        root.mkdir()
        (root / "main.py").write_text("X=7\n")
        project = client.app.state.projects.open(root)
        monkeypatch.setattr(terminal, "TerminalService", Registry)
        url = "/api/v1/research/projects/" + project.id + "/terminals"
        headers = {"Authorization": "Bearer terminal-race"}
        with ThreadPoolExecutor(max_workers=2) as executor:
            listing = executor.submit(client.get, url, headers=headers)
            assert entered.wait(5)
            creating = executor.submit(client.post, url, headers=headers, json={"profile": "python"})
            # The old implementation constructs a second registry while the
            # first is still initializing. Correct code waits for its owner.
            second.wait(.3)
            release.set()
            assert listing.result(5).status_code == creating.result(5).status_code == 200
        assert len(instances) == 1
        assert client.get(url, headers=headers).json()[0]["id"] == "owned-session"
