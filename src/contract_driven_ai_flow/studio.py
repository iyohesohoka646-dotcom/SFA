"""Independent local Web UI lifecycle, with authenticated readiness and shutdown."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from urllib.request import Request, urlopen

from .paths import FlowError
from .storage import Store, atomic_write


def read_state(root: Path) -> dict | None:
    try:
        value = json.loads((root / ".cdaf/studio.json").read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not isinstance(value.get("port"), int) or not 1024 <= value["port"] <= 65535:
            return None
        if not isinstance(value.get("pid"), int) or not isinstance(value.get("token"), str):
            return None
        return value
    except (OSError, ValueError):
        return None


def request(state: dict, method: str = "GET") -> dict:
    route = "/api/v1/studio/shutdown" if method == "POST" else "/api/v1/studio"
    address = f"http://127.0.0.1:{state['port']}{route}"
    with urlopen(Request(address, headers={"Authorization": "Bearer " + state["token"]}, method=method), timeout=1) as response:
        return json.load(response)


def active(root: Path, state: dict | None) -> bool:
    if not state:
        return False
    try:
        response = request(state)
        return response.get("pid") == state["pid"] and response.get("project") == str(root.resolve())
    except (OSError, ValueError):
        return False


def public_state(root: Path, state: dict, *, reused: bool) -> dict:
    return {"url": f"http://127.0.0.1:{state['port']}/#session={state['token']}",
            "pid": state["pid"], "port": state["port"], "project": str(root),
            "log": str(root / ".cdaf/studio.log"), "reused": reused}


@contextmanager
def launch_lock(root: Path):
    """Repeated shortcut launches serialize before creating or replacing state."""
    path = root / ".cdaf/studio-launch.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        deadline = time.monotonic() + 30
        while True:
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise FlowError("Another Studio launch is still in progress; retry after it becomes ready")
                time.sleep(.1)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def start(root: Path, port: int | None = None, *, workspace: bool = False) -> dict:
    root = root.resolve()
    with launch_lock(root):
        # Project locks prevent duplicate instances; this user-wide lock also
        # reserves port selection until a different project's server is ready.
        with launch_lock(Path(tempfile.gettempdir()) / "contract-driven-ai-flow-ports"):
            return _start(root, port, workspace=workspace)


def _start(root: Path, port: int | None, *, workspace: bool) -> dict:
    root = root.resolve()
    if workspace:
        from .workspace import Workspace
        Workspace(root).bootstrap()
    else:
        Store(root).load()
    state = read_state(root)
    if active(root, state):
        if port is not None and state["port"] != port:
            raise FlowError(f"Studio already runs on port {state['port']}; stop it before changing ports")
        return public_state(root, state, reused=True)
    if port is None:
        for candidate in range(8765, 8786):
            with socket.socket() as handle:
                try:
                    handle.bind(("127.0.0.1", candidate))
                except OSError:
                    continue
                port = candidate
                break
        if port is None:
            raise FlowError("Ports 8765–8785 are occupied; choose an explicit --port")
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=.5):
            raise FlowError(f"Port {port} is already occupied; use --port with a free port")
    except (ConnectionRefusedError, TimeoutError):
        pass
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_BREAKAWAY_FROM_JOB
    launch_id = secrets.token_hex(16)
    with (root / ".cdaf/studio.log").open("ab") as log:
        child = subprocess.Popen(
            [sys.executable, "-X", "utf8", "-m", "contract_driven_ai_flow.studio", str(root), str(port), launch_id, "workspace" if workspace else "project"],
            cwd=root, env={**os.environ, "PYTHONUTF8": "1"},
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            creationflags=flags, start_new_session=os.name != "nt", close_fds=True,
        )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        state = read_state(root)
        if state and state.get("launch_id") == launch_id and active(root, state):
            return public_state(root, state, reused=False)
        if child.poll() is not None:
            raise FlowError(f"Studio exited during startup; inspect {root / '.cdaf/studio.log'}")
        time.sleep(.1)
    child.terminate()
    child.wait(timeout=5)
    raise FlowError(f"Studio did not become ready within 20 seconds; inspect {root / '.cdaf/studio.log'}")


def stop(root: Path) -> dict:
    root = root.resolve()
    with launch_lock(root):
        return _stop(root)


def _stop(root: Path) -> dict:
    root = root.resolve()
    state = read_state(root)
    path = root / ".cdaf/studio.json"
    if not active(root, state):
        path.unlink(missing_ok=True)
        return {"stopped": False, "detail": "No managed Studio is running for this project"}
    request(state, "POST")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if read_state(root) != state:
            return {"stopped": True, "port": state["port"]}
        time.sleep(.1)
    raise FlowError(f"Studio is still shutting down; inspect {root / '.cdaf/studio.log'}")


def serve(root: Path, port: int = 8765, *, token: str | None = None, managed: bool = False, launch_id: str | None = None, workspace: bool = False):
    import uvicorn
    from .api import create_app

    root = root.resolve()
    token = token or secrets.token_urlsafe(32)

    def shutdown():
        server.should_exit = True

    if workspace:
        from .workspace import create_workspace_app
        application = create_workspace_app(root, token=token, port=port, shutdown=shutdown)
    else:
        application = create_app(root, token=token, port=port, shutdown=shutdown)
    server = uvicorn.Server(uvicorn.Config(application, host="127.0.0.1", port=port, access_log=False))
    state = {"pid": os.getpid(), "port": port, "token": token, "project": str(root), "launch_id": launch_id}
    path = root / ".cdaf/studio.json"
    if managed:
        atomic_write(path, json.dumps(state))
    try:
        server.run()
    finally:
        if managed and read_state(root) == state:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    serve(Path(sys.argv[1]), int(sys.argv[2]), managed=True, launch_id=sys.argv[3], workspace=len(sys.argv) > 4 and sys.argv[4] == "workspace")
