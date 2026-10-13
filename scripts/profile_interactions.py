"""Measure the shipped UI in a disposable workspace, never the user's projects."""
from pathlib import Path
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen


def main():
    from contract_driven_ai_flow.workspace import Workspace
    from contract_driven_ai_flow.models import ProjectSpec
    from contract_driven_ai_flow.storage import Store

    base = Path(__file__).resolve().parents[1]
    root = Path(tempfile.mkdtemp(prefix="research-profile-", dir=base / ".work"))
    workspace = Workspace(root)
    small = workspace.create("Small analysis", "data-pipeline")
    large_path = root / "large"
    modules = []
    for i in range(30):
        parent = f"group_{i}"
        modules.append({"id": parent, "kind": "composite"})
        modules.extend({"id": f"step_{i}_{j}", "parent": parent, "symbol": {"path": "analysis.py", "qualname": "step"}} for j in range(20))
    store = Store(large_path)
    store.save(ProjectSpec(name="Large analysis", modules=modules), None)
    store.save_views({"collapsed": [f"group_{i}" for i in range(30)], "positions": {}, "theme": "dark"}, store.views()["revision"])
    large = workspace.add(large_path)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    token = secrets.token_urlsafe(32)
    private_env = {**os.environ, "CDAF_PROFILE_SESSION": token}
    code = "import os,sys,uvicorn;from pathlib import Path;from contract_driven_ai_flow.workspace import create_workspace_app;uvicorn.run(create_workspace_app(Path(sys.argv[1]),token=os.environ['CDAF_PROFILE_SESSION'],port=int(sys.argv[2])),host='127.0.0.1',port=int(sys.argv[2]),access_log=False)"
    with (root / "profile-server.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, "-X", "utf8", "-c", code, str(root), str(port)], env=private_env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic()+20
            while time.monotonic()<deadline:
                try:
                    with urlopen(Request(f"http://127.0.0.1:{port}/api/v1/studio", headers={"Authorization": "Bearer " + token}), timeout=1) as response:
                        json.load(response)
                    break
                except OSError:
                    time.sleep(.1)
            else:
                raise RuntimeError("Profiling server did not start")
            env = {**private_env, "PROFILE_URL": f"http://127.0.0.1:{port}", "PROFILE_SMALL": small["id"], "PROFILE_LARGE": large["id"], "PROFILE_OUTPUT": str(base / ".work/profile-private-session.json")}
            subprocess.run(["node", str(base / "scripts/profile_interactions.mjs")], env=env, check=True, cwd=base)
        finally:
            process.terminate(); process.wait(timeout=10)


if __name__ == "__main__":
    main()
