"""Non-blocking, bounded publication with observable loss and terminal priority."""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from datetime import datetime, timezone


class EventTransport:
    def __init__(self, sink=None, *, max_queue_events=2048, publish_interval_ms=100, max_queue_bytes=8 * 1024 * 1024):
        if not 1 <= max_queue_events <= 10000 or not 1 <= publish_interval_ms <= 10000 or not 1 <= max_queue_bytes <= 64 * 1024 * 1024:
            raise ValueError("Transport budget is outside supported bounds")
        self.sink = sink
        self.max_queue_events = max_queue_events
        self.max_queue_bytes = max_queue_bytes
        self.interval = publish_interval_ms / 1000
        self._normal = deque()
        self._critical = deque()
        self._bytes = 0
        self._ordinal = 0
        self._dropped_since = 0
        self.dropped = 0
        self.last_error = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._closing = False
        self._closed = False
        self._inflight = False
        self._run_id = ""
        self._thread = None
        if sink is not None:
            self._thread = threading.Thread(target=self._worker, name="cdaf-research-events", daemon=True)
            self._thread.start()

    def emit(self, event: dict, critical: bool = False) -> None:
        # Copy only bounded wire data: later mutation cannot rewrite history.
        encoded = json.dumps(event, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
        size = len(encoded.encode("utf-8"))
        if size > 512 * 1024:
            raise ValueError("Capture event exceeds 512 KiB")
        value = json.loads(encoded)
        with self._lock:
            if self._closed:
                self._drop()
                return
            self._run_id = value.get("run_id", self._run_id)
            self._ordinal += 1
            item = (self._ordinal, size, value)
            if critical:
                # A separate bounded reserve prevents normal traffic from
                # displacing errors/termination. An abusive critical flood is
                # summarised explicitly instead of growing memory forever.
                if len(self._critical) >= 128:
                    previous = self._critical.popleft()
                    self._bytes -= previous[1]
                    self._drop()
                self._critical.append(item)
            else:
                while self._normal and (len(self._normal) >= self.max_queue_events or self._bytes + size > self.max_queue_bytes):
                    previous = self._normal.popleft()
                    self._bytes -= previous[1]
                    self._drop()
                if self._bytes + size > self.max_queue_bytes:
                    self._drop()
                    return
                self._normal.append(item)
            self._bytes += size
        if critical or self._closing:
            self._wake.set()

    def _drop(self):
        self.dropped += 1
        self._dropped_since += 1

    def drain(self, *, max_bytes=None, _publishing=False) -> list[dict]:
        with self._lock:
            ordered = sorted((*self._normal, *self._critical), key=lambda item: item[0])
            chosen, byte_count = [], 0
            for item in ordered:
                if chosen and max_bytes is not None and byte_count + item[1] > max_bytes:
                    break
                chosen.append(item)
                byte_count += item[1]
            ids = {item[0] for item in chosen}
            self._normal = deque(item for item in self._normal if item[0] not in ids)
            self._critical = deque(item for item in self._critical if item[0] not in ids)
            self._bytes -= byte_count
            events = [item[2] for item in chosen]
            if self._dropped_since:
                notice = {"schema_version": 1, "run_id": self._run_id, "sequence": 0, "kind": "capture.dropped",
                          "timestamp": datetime.now(timezone.utc).isoformat(), "payload": {"count": self._dropped_since, "total": self.dropped}}
                self._dropped_since = 0
                events.insert(0, notice)
            if events and _publishing:
                self._inflight = True
            return events

    def _worker(self):
        while True:
            self._wake.wait(self.interval)
            self._wake.clear()
            events = self.drain(max_bytes=512 * 1024, _publishing=True)
            if events:
                try:
                    self.sink(events)
                except Exception as error:
                    # Consumers can disconnect: observation never stalls the
                    # analysis; the supervisor also owns terminal recovery.
                    self.last_error = type(error).__name__
                    with self._lock:
                        for _ in events:
                            self._drop()
                finally:
                    with self._lock:
                        self._inflight = False
            with self._lock:
                pending = bool(self._normal or self._critical or self._inflight)
            if self._closing and not pending:
                break
            if pending and self._closing:
                self._wake.set()
        self._closed = True

    def flush(self, timeout=3) -> bool:
        if self._thread is None:
            return True
        self._wake.set()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                pending = bool(self._normal or self._critical or self._inflight)
            if not pending:
                return self.last_error is None
            time.sleep(0.005)
        return False

    def close(self, timeout=3) -> bool:
        self._closing = True
        self._wake.set()
        if self._thread is None:
            self._closed = True
            return True
        self._thread.join(timeout)
        return not self._thread.is_alive() and self.last_error is None
