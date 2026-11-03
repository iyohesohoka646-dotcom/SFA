"""Fresh-user workspace for browser acceptance; no user directories are touched."""
from pathlib import Path
import tempfile
import uvicorn

from contract_driven_ai_flow.workspace import create_workspace_app
from browser_session import fixture_session


if __name__ == "__main__":
    base = Path(__file__).resolve().parents[1] / ".work"
    base.mkdir(exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="browser-workspace-", dir=base))
    uvicorn.run(create_workspace_app(root, token=fixture_session(), port=8878), host="127.0.0.1", port=8878, access_log=False)
