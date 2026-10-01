"""Private duplex JSON control; ordinary observation has no UI dependency."""
from __future__ import annotations

import _thread
import fnmatch
import json
import socket
import threading


class AgentChannel:
    def __init__(self, port, token, run_id, gates):
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.socket.settimeout(None)
        self.writer = self.socket.makefile("wb")
        self.reader = self.socket.makefile("rb")
        self.lock = threading.Lock()
        self.gates = tuple(gates)
        self.responses = {}
        self.condition = threading.Condition()
        self.disconnected = False
        self.cancelled = False
        self.send({"type": "hello", "token": token, "run_id": run_id, "protocol_version": 1})
        self.listener = threading.Thread(target=self._listen, name="cdaf-analysis-control", daemon=True)
        self.listener.start()

    def send(self, value):
        encoded = json.dumps(value, allow_nan=False, ensure_ascii=False).encode("utf-8")
        if len(encoded) > 1024 * 1024:
            raise ValueError("Agent protocol frame is too large")
        with self.lock:
            self.writer.write(encoded + b"\n")
            self.writer.flush()

    def publish(self, events):
        self.send({"type": "events", "events": events})

    def requires_gate(self, name, binding):
        return any(fnmatch.fnmatchcase(name, pattern) or fnmatch.fnmatchcase(binding, pattern) for pattern in self.gates)

    def _listen(self):
        try:
            while True:
                line = self.reader.readline(65537)
                if not line or len(line) > 65536:
                    break
                message = json.loads(line)
                action = message.get("action")
                if action == "cancel":
                    self.cancelled = True
                    with self.condition:
                        self.condition.notify_all()
                    _thread.interrupt_main()
                elif action in ("continue", "resume"):
                    with self.condition:
                        self.responses[message["snapshot_id"]] = action
                        self.condition.notify_all()
        except Exception:
            pass
        finally:
            with self.condition:
                self.disconnected = True
                self.condition.notify_all()

    def boundary(self, snapshot, trace):
        if not self.requires_gate(snapshot["name"], snapshot["binding_id"]):
            return
        trace.emit("boundary.waiting", {"snapshot_id": snapshot["id"]}, snapshot_id=snapshot["id"], critical=True)
        with self.condition:
            while snapshot["id"] not in self.responses:
                if self.cancelled:
                    raise KeyboardInterrupt
                if self.disconnected:
                    raise RuntimeError("Analysis controller disconnected during a required check")
                self.condition.wait(0.1)
            self.responses.pop(snapshot["id"])

    def close(self):
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.reader.close()
        self.writer.close()
        self.socket.close()
