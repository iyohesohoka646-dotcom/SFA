from __future__ import annotations

import ipaddress
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from ..research.models import WireModel


class ProviderProfile(WireModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")
    protocol: Literal["offline", "openai-compatible", "anthropic"] = "offline"
    base_url: str = Field(default="", max_length=4096)
    models: list[str] = Field(default_factory=list, max_length=2000)
    default_model: str = Field(default="", max_length=256)
    timeout_seconds: float = Field(default=60, ge=1, le=300)
    credential_ref: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def endpoints_and_references(self):
        if any(not model or len(model) > 256 for model in self.models):
            raise ValueError("Model IDs must be bounded non-empty strings")
        self.models = sorted(set(self.models))
        if self.protocol != "offline":
            url = urlsplit(self.base_url)
            if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError("Use an HTTP(S) service URL without credentials, query or fragment")
            local = url.hostname == "localhost"
            try:
                local = local or ipaddress.ip_address(url.hostname).is_loopback
            except ValueError:
                pass
            if url.scheme == "http" and not local:
                raise ValueError("Remote model services require HTTPS")
            self.base_url = self.base_url.rstrip("/")
        if self.credential_ref:
            if self.credential_ref.startswith("env:"):
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", self.credential_ref[4:]):
                    raise ValueError("Invalid credential environment reference")
            elif not re.fullmatch(r"keyring:[a-zA-Z0-9_.:-]{1,240}", self.credential_ref):
                raise ValueError("Unknown credential reference")
        return self


class PublicProviderProfile(ProviderProfile):
    configured: bool = False


class ConnectionResult(WireModel):
    status: Literal["connected", "error", "cancelled", "offline"]
    operation_id: str = ""
    message: str = ""
    models: list[str] = Field(default_factory=list)
    inference: bool = False
    usage: dict[str, int] = Field(default_factory=dict)
    duration_ms: float = 0
    requests: int = 0


class ModelReply(ConnectionResult):
    text: str = ""
