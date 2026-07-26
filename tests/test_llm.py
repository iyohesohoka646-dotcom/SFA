"""Tests for the LLM client abstraction (mock + provider guards)."""
from __future__ import annotations

import os
import sys

import pytest

from sfa import llm as llm_mod
from sfa.config import SFAError


def _cfg(provider: str, **extra: object) -> dict:
    ai = {"provider": provider, "model": "test-model", "api_key_env": "TEST_KEY"}
    ai.update(extra)
    return {"ai": ai}


def test_get_client_mock() -> None:
    client = llm_mod.get_client(_cfg("mock"))
    assert isinstance(client, llm_mod.MockClient)


def test_get_client_invalid_provider() -> None:
    try:
        llm_mod.get_client(_cfg("bogus"))
    except SFAError as exc:
        assert "bogus" in str(exc)
        return
    raise AssertionError("expected SFAError for invalid provider")


def test_mock_client_returns_stub_with_signature() -> None:
    client = llm_mod.MockClient()
    user = "```python\ndef preprocess(data: list, scale: float = 1.0) -> dict:\n    \"\"\"Preprocess raw data.\"\"\"\n```\n"
    out = client.complete("sys", user)
    assert "def preprocess" in out
    assert "NotImplementedError" in out
    assert "SFA mock provider stub" in out


def test_mock_client_no_signature_fallback() -> None:
    client = llm_mod.MockClient()
    out = client.complete("sys", "no code block here")
    assert "NotImplementedError" in out


def test_openai_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_KEY", raising=False)
    try:
        llm_mod.OpenAIClient({"provider": "openai", "model": "gpt-4o", "api_key_env": "TEST_KEY"})
    except SFAError as exc:
        assert "TEST_KEY" in str(exc)
        return
    raise AssertionError("expected SFAError for missing API key")


def test_openai_missing_package(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_KEY", "sk-fake")
    # Simulate openai not installed.
    monkeypatch.setitem(sys.modules, "openai", None)
    try:
        llm_mod.OpenAIClient({"provider": "openai", "model": "gpt-4o", "api_key_env": "TEST_KEY"})
    except SFAError as exc:
        assert "openai" in str(exc)
        return
    raise AssertionError("expected SFAError for missing openai package")


def test_anthropic_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_KEY", raising=False)
    try:
        llm_mod.AnthropicClient({"provider": "anthropic", "model": "claude", "api_key_env": "TEST_KEY"})
    except SFAError as exc:
        assert "TEST_KEY" in str(exc)
        return
    raise AssertionError("expected SFAError for missing API key")


def test_openai_missing_model() -> None:
    try:
        llm_mod.OpenAIClient({"provider": "openai", "api_key_env": "TEST_KEY"})
    except SFAError as exc:
        assert "model" in str(exc)
        return
    raise AssertionError("expected SFAError for missing model")


def test_extract_entry_signature_async() -> None:
    user = "```python\nasync def fetch(url: str) -> bytes:\n    \"\"\"Fetch.\"\"\"\n```\n"
    out = llm_mod._extract_entry_signature(user)
    assert out is not None
    assert "async def fetch" in out
