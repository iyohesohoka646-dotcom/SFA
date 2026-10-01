"""Isolated local server used by Playwright; never points at a user's project."""
from pathlib import Path
import tempfile
import uvicorn
from contract_driven_ai_flow.api import create_app
from contract_driven_ai_flow.examples import create_example, definition
from contract_driven_ai_flow.runtime import Runner


if __name__ == "__main__":
    base = Path(__file__).resolve().parents[1] / ".work"
    base.mkdir(exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="browser-", dir=base)) / "demo"
    create_example(root)
    _, _, success, failure = definition("data-pipeline")
    Runner(root).run(success)
    Runner(root).run(failure)
    uvicorn.run(create_app(root, token="browser-test-session", port=8877), host="127.0.0.1", port=8877, access_log=False)
