"""Profile persistence and cancellable protocol calls shared by all clients."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

import httpx

from ..research.agent.privacy import clean_text
from .credentials import SystemCredentials
from .models import ConnectionResult, ModelReply, ProviderProfile, PublicProviderProfile


class ModelSettingsService:
    def __init__(self, root: Path, *, credentials=None, transport=None):
        self.root = Path(root).resolve()
        self.path = self.root / ".cdaf/settings/models.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.credentials = credentials if credentials is not None else SystemCredentials()
        self.transport = transport
        self._tasks = {}
        self._lock = threading.RLock()
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS profiles(id TEXT PRIMARY KEY, body TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS calls(id INTEGER PRIMARY KEY, profile TEXT, body TEXT)")

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def profile(self, identifier):
        if identifier == "offline":
            return ProviderProfile(id="offline", protocol="offline", models=["rules"], default_model="rules")
        with self.connect() as db:
            row = db.execute("SELECT body FROM profiles WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise LookupError("Model profile is unavailable")
        return ProviderProfile.model_validate_json(row[0])

    def secret(self, profile):
        reference = profile.credential_ref
        if not reference:
            return None
        if reference.startswith("env:"):
            return os.environ.get(reference[4:])
        return self.credentials.get(reference)

    def _public(self, profile):
        return PublicProviderProfile(**profile.model_dump(), configured=profile.protocol == "offline" or bool(self.secret(profile)))

    def list(self):
        with self.connect() as db:
            profiles = [ProviderProfile.model_validate_json(row[0]) for row in db.execute("SELECT body FROM profiles ORDER BY id")]
        return [self._public(self.profile("offline")), *[self._public(p) for p in profiles]]

    def save(self, profile: ProviderProfile, secret: str | None = None):
        profile = ProviderProfile.model_validate(profile)
        if profile.id == "offline":
            raise ValueError("The offline rule profile is built in")
        try:
            old = self.profile(profile.id)
        except LookupError:
            old = None
        if secret is not None:
            if not secret or len(secret) > 16384:
                raise ValueError("Invalid model credential")
            prefix = hashlib.sha256(str(self.root).encode()).hexdigest()[:16]
            reference = "keyring:" + prefix + ":" + profile.id + ":" + uuid.uuid4().hex
            try:
                self.credentials.put(reference, secret)
            except Exception as error:
                raise ValueError("System credential store unavailable; no plaintext credential was saved") from error
            profile = profile.model_copy(update={"credential_ref": reference})
        try:
            with self.connect() as db:
                db.execute("INSERT INTO profiles VALUES (?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body", (profile.id, profile.model_dump_json()))
        except Exception:
            if secret is not None and callable(getattr(self.credentials, "delete", None)):
                self.credentials.delete(profile.credential_ref)
            raise
        if old and old.credential_ref and old.credential_ref.startswith("keyring:") and old.credential_ref != profile.credential_ref and callable(getattr(self.credentials, "delete", None)):
            self.credentials.delete(old.credential_ref)
        return self._public(profile)

    def delete(self, identifier):
        profile = self.profile(identifier)
        if identifier == "offline":
            raise ValueError("The offline rule profile is built in")
        with self.connect() as db:
            db.execute("DELETE FROM profiles WHERE id=?", (identifier,))
        if profile.credential_ref and profile.credential_ref.startswith("keyring:") and callable(getattr(self.credentials, "delete", None)):
            self.credentials.delete(profile.credential_ref)

    def cancel(self, operation_id):
        with self._lock:
            operation = self._tasks.get(operation_id)
        if not operation:
            return False
        loop, task = operation
        loop.call_soon_threadsafe(task.cancel)
        return True

    def close(self):
        with self._lock:
            identifiers = list(self._tasks)
        for identifier in identifiers:
            self.cancel(identifier)

    @staticmethod
    def _usage(body):
        allowed = ("prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
        return {k: v for k, v in body.get("usage", {}).items() if k in allowed and type(v) is int and v >= 0}

    async def _call(self, profile, *, inference=False, messages=None, model=None, operation_id=None):
        identifier = operation_id or uuid.uuid4().hex
        with self._lock:
            if identifier in self._tasks:
                raise ValueError("Model operation is already active")
            self._tasks[identifier] = (asyncio.get_running_loop(), asyncio.current_task())
        started, count = time.monotonic(), 0
        result = ModelReply(status="error", operation_id=identifier, inference=inference)
        secret = self.secret(profile)
        try:
            if profile.protocol == "offline":
                result.status, result.models, result.message = "offline", ["rules"], "Offline mathematical rules require no model or credential"
                return result
            headers = {"Accept": "application/json"}
            if profile.protocol == "anthropic":
                headers["anthropic-version"] = "2023-06-01"
                if secret:
                    headers["x-api-key"] = secret
            elif secret:
                headers["Authorization"] = "Bearer " + secret
            payload = None
            endpoint, method = "/models", "GET"
            if inference:
                selected = model or profile.default_model
                if not selected:
                    raise ValueError("Choose a model ID before sending inference")
                if profile.protocol == "anthropic":
                    endpoint = "/messages"
                    payload = {"model": selected, "max_tokens": 2048,
                        "system": "\n".join(m["content"] for m in messages if m["role"] == "system"),
                        "messages": [m for m in messages if m["role"] != "system"]}
                else:
                    endpoint = "/chat/completions"
                    payload = {"model": selected, "messages": messages, "max_tokens": 2048, "stream": False}
                method = "POST"
            async with asyncio.timeout(profile.timeout_seconds):
                async with httpx.AsyncClient(transport=self.transport, timeout=profile.timeout_seconds, follow_redirects=False, trust_env=False) as client:
                    for attempt in range(2):
                        count += 1
                        async with client.stream(method, profile.base_url + endpoint, headers=headers, json=payload) as response:
                            if response.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                                await asyncio.sleep(.2)
                                continue
                            if response.status_code >= 300:
                                raise ValueError("Model service returned HTTP " + str(response.status_code))
                            chunks, size = [], 0
                            async for chunk in response.aiter_bytes():
                                size += len(chunk)
                                if size > 1024 * 1024:
                                    raise ValueError("Model response exceeds the 1 MiB limit")
                                chunks.append(chunk)
                            body = json.loads(b"".join(chunks))
                            break
            if inference:
                text = "\n".join(b["text"] for b in body.get("content", []) if b.get("type") == "text") if profile.protocol == "anthropic" else body["choices"][0]["message"]["content"]
                if type(text) is not str:
                    raise ValueError("Model service did not return text")
                result.text = clean_text(text.replace(secret, "[REDACTED]") if secret else text, 65536)
                result.usage = self._usage(body)
                result.message = "Inference request completed; a test message was sent"
            else:
                result.models = sorted({str(m["id"]) for m in body["data"] if type(m.get("id")) is str and 0 < len(m["id"]) <= 256})[:2000]
                result.message = "Model-list connection succeeded; no inference was sent"
                updated = profile.model_copy(update={"models": result.models})
                # Discovery must never undo a concurrent edit or recreate a deleted profile.
                with self.connect() as db:
                    db.execute("UPDATE profiles SET body=? WHERE id=? AND body=?",
                               (updated.model_dump_json(), profile.id, profile.model_dump_json()))
            result.status = "connected"
        except asyncio.CancelledError:
            result.status, result.message = "cancelled", "Model request cancelled"
        except Exception as error:
            result.message = str(error) if type(error) is ValueError and str(error).startswith(("Model service returned HTTP", "Choose a model ID", "Model response exceeds")) else "Model request failed (" + type(error).__name__ + "); check address, credential and protocol"
        finally:
            result.duration_ms = (time.monotonic() - started) * 1000
            result.requests = count
            with self._lock:
                self._tasks.pop(identifier, None)
            record = result.model_dump(exclude={"text", "models"})
            with self.connect() as db:
                db.execute("INSERT INTO calls(profile,body) VALUES (?,?)", (profile.id, json.dumps(record, allow_nan=False)))
        return result

    async def test(self, profile_id, *, inference=False, model=None, operation_id=None):
        messages = [{"role": "system", "content": "Reply briefly to this connection test."}, {"role": "user", "content": "Reply OK."}]
        response = await self._call(self.profile(profile_id), inference=inference, messages=messages, model=model, operation_id=operation_id)
        return ConnectionResult.model_validate(response.model_dump(exclude={"text"}))

    async def complete(self, profile_id, messages, *, model=None, operation_id=None):
        return await self._call(self.profile(profile_id), inference=True, messages=messages, model=model, operation_id=operation_id)
