"""Owned, interactive PTY sessions. Terminal contents never enter observation storage."""

from __future__ import annotations

import asyncio
import codecs
import hmac
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import Field
from ..models import WireModel
from ..processes import ProcessTree


class TerminalSession(WireModel):
    id: str
    profile: str
    cwd: str
    status: str = "running"
    pid: int | None = None
    rows: int = 24
    cols: int = 80
    error: str | None = None


class _WindowsPTY:
    def __init__(self, argv, cwd, env, rows, cols):
        from winpty import PtyProcess, Backend

        self.process = PtyProcess.spawn(
            argv, cwd=str(cwd), env=env, dimensions=(rows, cols), backend=Backend.ConPTY
        )
        from ctypes import WinDLL, get_last_error, WinError
        from ctypes import wintypes

        kernel = WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        self._handle = kernel.OpenProcess(0x1101, False, self.process.pid)
        if not self._handle:
            self.process.close(force=True)
            raise WinError(get_last_error())
        self.kernel = kernel
        try:
            self.tree = ProcessTree(self)
        except BaseException:
            self.close()
            raise

    @property
    def pid(self):
        return self.process.pid

    def poll(self):
        return None if self.process.isalive() else 0

    def kill(self):
        self.process.terminate(force=True)

    def read(self):
        return self.process.read(8192)

    def write(self, data):
        self.process.write(data)

    def resize(self, rows, cols):
        self.process.setwinsize(rows, cols)

    def close(self):
        if getattr(self, "tree", None):
            self.tree.terminate()
            self.tree.close()
            self.tree = None
        self.process.close(force=True)
        if self._handle:
            import ctypes

            self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            self.kernel.CloseHandle(self._handle)
            self._handle = None


class _PosixPTY:
    def __init__(self, argv, cwd, env, rows, cols):
        import pty

        self.fd, slave = pty.openpty()
        try:
            self.resize(rows, cols)
            self.process = subprocess.Popen(
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    str(Path(__file__).with_name("terminal_host.py")),
                    *argv,
                ],
                cwd=cwd,
                env=env,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                start_new_session=True,
            )
        except BaseException:
            os.close(self.fd)
            raise
        finally:
            os.close(slave)
        self.tree = ProcessTree(self.process)
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.resize(rows, cols)

    @property
    def pid(self):
        return self.process.pid

    def poll(self):
        return self.process.poll()

    def read(self):
        while True:
            data = os.read(self.fd, 8192)
            if not data:
                raise EOFError()
            decoded = self.decoder.decode(data)
            if decoded:
                return decoded

    def write(self, data):
        view = memoryview(data.encode("utf-8"))
        while view:
            view = view[os.write(self.fd, view) :]

    def resize(self, rows, cols):
        import fcntl, struct, termios

        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def close(self):
        if self.fd < 0:
            return
        import signal
        import time

        def owned_session():
            # Session identity survives a shell leader's exit and includes jobs
            # in separate foreground/background groups. Never target other sessions.
            rows = subprocess.run(
                ["ps", "-A", "-o", "pid="],
                capture_output=True,
                text=True,
                check=True,
                timeout=2,
            ).stdout.split()
            owned = []
            for row in rows:
                try:
                    pid = int(row)
                    if os.getsid(pid) == self.pid:
                        owned.append(pid)
                except (ProcessLookupError, PermissionError):
                    pass
            return owned

        def send(pids, sig):
            for pid in pids:
                try:
                    if os.getsid(pid) == self.pid:
                        os.kill(pid, sig)
                except (ProcessLookupError, PermissionError):
                    pass

        send(owned_session(), signal.SIGTERM)
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=0.3)
        except subprocess.TimeoutExpired:
            pass
        # Escalate independently of leader state; descendants may ignore TERM.
        time.sleep(0.05)
        send(owned_session(), signal.SIGKILL)
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=2)
        self.tree.close()
        os.close(self.fd)
        self.fd = -1


class TerminalService:
    def __init__(self, root: Path, *, buffer_chars=262144, url="", token=""):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.buffer_chars = max(4096, min(2 * 1024 * 1024, buffer_chars))
        self.url, self.token = url, token
        self._sessions = {}
        self._lock = threading.RLock()
        self._closed = False

    def create(self, profile="shell", interpreter=None, rows=24, cols=80):
        if profile not in ("shell", "python", "cli"):
            raise ValueError("Unknown terminal profile")
        if not 2 <= rows <= 500 or not 2 <= cols <= 1000:
            raise ValueError("Invalid terminal dimensions")
        with self._lock:
            if self._closed:
                raise ValueError("Terminal service has ended")
            expired = [
                key
                for key, entry in self._sessions.items()
                if entry["session"].status != "running"
                and (entry["thread"] is None or not entry["thread"].is_alive())
            ]
            for key in expired[:-24]:
                self._sessions.pop(key)
            if (
                sum(s["session"].status == "running" for s in self._sessions.values())
                >= 8
            ):
                raise ValueError(
                    "End a terminal before opening more than eight sessions"
                )
            session = TerminalSession(
                id=uuid.uuid4().hex,
                profile=profile,
                cwd=str(self.root),
                rows=rows,
                cols=cols,
            )
            entry = {
                "session": session,
                "pty": None,
                "data": "",
                "cursor": 0,
                "thread": None,
                "connected": False,
            }
            self._sessions[session.id] = entry
            env = dict(
                os.environ,
                TERM="xterm-256color",
                PYTHONIOENCODING="utf-8",
                PYTHONUTF8="1",
            )
            python = interpreter or sys.executable
            if profile == "python":
                argv = [python, "-X", "utf8", "-i"]
            elif profile == "cli":
                argv = [
                    python,
                    "-X",
                    "utf8",
                    "-m",
                    "contract_driven_ai_flow",
                    "terminal",
                    "--project",
                    str(self.root),
                ]
                if self.url:
                    argv += [
                        "--connect",
                        self.url,
                        "--token-env",
                        "CDAF_TERMINAL_SESSION",
                    ]
                    env["CDAF_TERMINAL_SESSION"] = self.token
            else:
                argv = (
                    [
                        shutil.which("pwsh")
                        or shutil.which("powershell")
                        or "powershell.exe",
                        "-NoLogo",
                        "-NoProfile",
                    ]
                    if os.name == "nt"
                    else [os.environ.get("SHELL") or "/bin/bash", "-i"]
                )
            try:
                if shutil.which(argv[0], path=env.get("PATH")) is None:
                    raise FileNotFoundError(
                        "Terminal executable is unavailable: " + argv[0]
                    )
                command = [
                    sys.executable,
                    "-X",
                    "utf8",
                    str(Path(__file__).with_name("terminal_host.py")),
                    *argv,
                ]
                pty = (
                    _WindowsPTY(command, self.root, env, rows, cols)
                    if os.name == "nt"
                    else _PosixPTY(argv, self.root, env, rows, cols)
                )
                entry["pty"] = pty
                session.pid = pty.pid
                reader = threading.Thread(
                    target=self._drain,
                    args=(session.id,),
                    daemon=True,
                    name="terminal-" + session.id[:6],
                )
                entry["thread"] = reader
                reader.start()
            except Exception as error:
                session.status, session.error = (
                    "error",
                    f"{type(error).__name__}: {error}",
                )
            return session.model_dump(mode="json")

    def _entry(self, key):
        if key not in self._sessions:
            raise LookupError("Terminal session unavailable")
        return self._sessions[key]

    def _drain(self, key):
        entry = self._entry(key)
        try:
            while True:
                data = entry["pty"].read()
                if not data:
                    break
                with self._lock:
                    entry["cursor"] += len(data)
                    entry["data"] = (entry["data"] + data)[-self.buffer_chars :]
        except (EOFError, OSError):
            pass
        except Exception as error:
            with self._lock:
                if entry["session"].status == "running":
                    entry["session"].error = f"{type(error).__name__}: {error}"
        finally:
            with self._lock:
                if entry["session"].status == "running":
                    entry["session"].status = "ended"
            self.end(key)

    def get(self, key):
        with self._lock:
            return self._entry(key)["session"].model_dump(mode="json")

    def list(self):
        with self._lock:
            return [
                s["session"].model_dump(mode="json")
                for s in list(self._sessions.values())[-32:]
            ]

    def alive(self, key):
        pty = self._entry(key)["pty"]
        return pty is not None and pty.poll() is None

    def connect(self, key):
        with self._lock:
            entry = self._entry(key)
            replay = entry["connected"]
            entry["connected"] = True
            return replay

    def read(self, key, after=0):
        if not isinstance(after, int) or after < 0:
            raise ValueError("Invalid terminal cursor")
        with self._lock:
            s = self._entry(key)
            start = s["cursor"] - len(s["data"])
            if after > s["cursor"]:
                raise ValueError("Terminal cursor exceeds current output")
            return {
                "type": "output",
                "data": s["data"][max(0, after - start) :],
                "start": start,
                "cursor": s["cursor"],
                "truncated": after < start,
                "status": s["session"].status,
                "error": s["session"].error,
            }

    def write(self, key, data):
        if not isinstance(data, str) or len(data) > 65536:
            raise ValueError("Terminal input exceeds 64 KiB")
        with self._lock:
            s = self._entry(key)
            if s["session"].status != "running":
                raise ValueError("Terminal is not running")
            s["pty"].write(data)

    def resize(self, key, rows, cols):
        if (
            not isinstance(rows, int)
            or not isinstance(cols, int)
            or not 2 <= rows <= 500
            or not 2 <= cols <= 1000
        ):
            raise ValueError("Invalid terminal dimensions")
        with self._lock:
            s = self._entry(key)
            if s["session"].status != "running":
                raise ValueError("Terminal is not running")
            s["pty"].resize(rows, cols)
            s["session"].rows, s["session"].cols = rows, cols

    def end(self, key):
        with self._lock:
            s = self._entry(key)
            s["session"].status = "ended"
            pty = s["pty"]
            s["pty"] = None
        if pty:
            pty.close()
        if s["thread"] and s["thread"] is not threading.current_thread():
            s["thread"].join(timeout=2)
        return self.get(key)

    def close(self):
        with self._lock:
            self._closed = True
            keys = list(self._sessions)
        for key in keys:
            self.end(key)


class StartTerminal(WireModel):
    profile: str = "shell"
    interpreter: str | None = Field(default=None, max_length=4096)
    rows: int = Field(default=24, ge=2, le=500)
    cols: int = Field(default=80, ge=2, le=1000)


def attach_terminal_routes(app, research):
    service = TerminalService(
        research.root,
        buffer_chars=research.workbench.preferences.load()["values"]["terminal"][
            "buffer_chars"
        ],
        url=f"http://127.0.0.1:{app.state.local_port}",
        token=app.state.session_token,
    )
    research.workbench.terminals = service
    app.state.terminals = service
    router = APIRouter(prefix="/api/v1/research/terminals")

    @router.get("")
    def sessions():
        return service.list()

    @router.post("")
    def start(body: StartTerminal):
        return service.create(**body.model_dump())

    @router.get("/{key}")
    def session(key: str):
        return service.get(key)

    @router.post("/{key}/end")
    def end(key: str):
        return service.end(key)

    @router.websocket("/{key}/socket")
    async def socket(ws: WebSocket, key: str):
        expected = {
            f"http://127.0.0.1:{app.state.local_port}",
            f"http://localhost:{app.state.local_port}",
        }
        if ws.headers.get("origin") not in expected or ws.headers.get("host", "").split(
            ":"
        )[0] not in ("127.0.0.1", "localhost", "testserver"):
            await ws.close(code=1008)
            return
        await ws.accept()
        try:

            async def receive():
                raw = await ws.receive_text()
                if len(raw) > 65536:
                    raise ValueError("Terminal frame exceeds 64 KiB")
                return json.loads(raw)

            auth = await asyncio.wait_for(receive(), timeout=5)
            if (
                not isinstance(auth, dict)
                or auth.get("type") != "authenticate"
                or not isinstance(auth.get("token"), str)
                or not hmac.compare_digest(auth["token"], app.state.session_token)
            ):
                await ws.close(code=4401)
                return
            after = auth.get("after", 0)
            service.read(key, after)
            # A new PTY's buffered output contains unanswered initialization
            # queries. Only an already attached terminal is history replay.
            reconnect = service.connect(key)

            async def output():
                nonlocal after
                last = None
                initial = True
                while True:
                    frame = service.read(key, after)
                    signature = (frame["cursor"], frame["status"], frame["error"])
                    if signature != last:
                        await ws.send_json({**frame, "replay": initial and reconnect})
                        initial = False
                        after = frame["cursor"]
                        last = signature
                    await asyncio.sleep(0.04)

            sender = asyncio.create_task(output())
            try:
                while True:
                    body = await receive()
                    if body.get("type") == "input":
                        await asyncio.to_thread(service.write, key, body.get("data"))
                    elif body.get("type") == "resize":
                        await asyncio.to_thread(
                            service.resize, key, body.get("rows"), body.get("cols")
                        )
                    elif body.get("type") == "end":
                        await asyncio.to_thread(service.end, key)
                    else:
                        raise ValueError("Unknown terminal operation")
            finally:
                sender.cancel()
                await asyncio.gather(sender, return_exceptions=True)
        except WebSocketDisconnect:
            pass
        except (
            ValueError,
            LookupError,
            asyncio.TimeoutError,
            TypeError,
            AttributeError,
        ) as error:
            try:
                await ws.send_json({"type": "error", "error": str(error)})
                await ws.close(code=1008)
            except (WebSocketDisconnect, RuntimeError):
                pass

    app.include_router(router)
