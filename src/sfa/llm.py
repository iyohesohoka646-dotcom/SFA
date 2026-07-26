"""LLM client abstraction with pluggable providers.

Supports ``openai``, ``anthropic`` and a built-in ``mock`` provider.  The
real SDK clients are imported lazily so the base install stays dependency
free; ``mock`` is always available for tests and offline demos.
"""
from __future__ import annotations

import os
import re
from typing import Any, Protocol

from .config import SFAError

_VALID_PROVIDERS = {"openai", "anthropic", "mock"}

_INSTALL_HINT = (
    "可操作建议：安装 AI 可选依赖：`pip install -e \".[ai]\"`，"
    "或改用 `mock` 提供方（在 sfa.yml 中设置 `ai.provider: mock`）进行离线演示。"
)


class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str:
        ...


def get_client(cfg: dict[str, Any]) -> LLMClient:
    """Build an LLM client from the ``ai`` section of *cfg*."""
    ai = cfg.get("ai") or {}
    provider = str(ai.get("provider", "")).strip().lower()
    if provider not in _VALID_PROVIDERS:
        raise SFAError(
            f"未知的 AI 提供方：{provider!r}\n"
            f"可操作建议：在 sfa.yml 的 ai.provider 中使用以下之一："
            f"{', '.join(sorted(_VALID_PROVIDERS))}。"
        )
    if provider == "mock":
        return MockClient()
    if provider == "openai":
        return OpenAIClient(ai)
    return AnthropicClient(ai)


def _require_api_key(ai: dict[str, Any], provider_name: str) -> str:
    env_name = str(ai.get("api_key_env", "")).strip()
    if not env_name:
        raise SFAError(
            f"{provider_name} 提供方未配置 api_key_env。\n"
            "可操作建议：在 sfa.yml 的 ai 段添加 `api_key_env: <环境变量名>`。"
        )
    key = os.environ.get(env_name, "").strip()
    if not key:
        raise SFAError(
            f"未找到 API key：环境变量 {env_name} 未设置或为空。\n"
            f"可操作建议：设置该环境变量后再试，或改用 `mock` 提供方进行离线演示。"
        )
    return key


class MockClient:
    """Deterministic, dependency-free stub client.

    Inspects the user prompt for a clearly-marked entry signature
    (a fenced block containing a ``def`` line) and returns a stub
    implementation that preserves the signature and raises
    ``NotImplementedError``.
    """

    def complete(self, system: str, user: str) -> str:
        signature = _extract_entry_signature(user)
        if signature is None:
            return '```python\nraise NotImplementedError("SFA mock provider stub")\n```'
        return signature

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "MockClient()"


_SIGNATURE_RE = re.compile(r"^(\s*(?:async\s+)?def\s+\w+.*?:)\s*$")


def _extract_entry_signature(user: str) -> str | None:
    """Pull the entry ``def`` line + its docstring from the prompt.

    The ai.py module marks the target entry signature as the *last*
    fenced ```python block in the user prompt (upstream source blocks,
    if any, appear earlier).  We therefore take the final fenced block
    and locate the ``def`` line within it.
    """
    from .ai import parse_fenced_blocks

    blocks = parse_fenced_blocks(user)
    candidates = (blocks[-1] if blocks else []) or user.splitlines()
    def_idx = None
    for i, line in enumerate(candidates):
        if _SIGNATURE_RE.match(line):
            def_idx = i
            break
    if def_idx is None:
        return None

    header = candidates[def_idx].rstrip()
    # Determine the indentation of the signature line (usually column 0).
    indent_unit = "    "
    # Capture a docstring if present immediately after the def line.
    body_lines: list[str] = []
    j = def_idx + 1
    docstring: str | None = None
    if j < len(candidates):
        maybe = candidates[j].strip()
        if maybe.startswith('"""') or maybe.startswith("'''"):
            quote = maybe[:3]
            if maybe.endswith(quote) and len(maybe) >= 6:
                docstring = maybe[3:-3]
            else:
                doc = [maybe[3:]]
                j += 1
                while j < len(candidates):
                    if candidates[j].strip().endswith(quote):
                        doc.append(candidates[j].strip()[:-3])
                        break
                    doc.append(candidates[j].strip())
                    j += 1
                docstring = "\n".join(d for d in doc if d).strip()

    out = [header]
    if docstring:
        out.append(f'{indent_unit}"""{docstring}"""')
    out.append(f'{indent_unit}raise NotImplementedError("SFA mock provider stub")')
    return "\n".join(out)


class _RealLLMClient:
    """Shared base for SDK-backed providers.

    Handles model validation, API-key retrieval and lazy SDK import so
    provider subclasses only differ in client instantiation and the
    ``complete`` call shape.
    """

    _provider_name: str = ""
    _module_name: str = ""

    def __init__(self, ai: dict[str, Any]) -> None:
        self._ai = ai
        self._model = str(ai.get("model", "")).strip()
        if not self._model:
            raise SFAError(
                f"{self._provider_name} 提供方未配置 model。\n"
                "可操作建议：在 sfa.yml 的 ai 段添加 `model: <模型名>`。"
            )
        self._key = _require_api_key(ai, self._provider_name)
        sdk = self._import_sdk()
        self._client = self._instantiate_client(sdk)

    def _import_sdk(self) -> Any:
        try:
            return __import__(self._module_name)
        except ImportError as exc:
            raise SFAError(
                f"未安装 {self._module_name} SDK：{exc}\n"
                f"相关配置：ai.provider={self._provider_name.lower()}\n"
                f"{_INSTALL_HINT}"
            ) from exc

    def _instantiate_client(self, sdk: Any) -> Any:
        raise NotImplementedError


class OpenAIClient(_RealLLMClient):
    _provider_name = "OpenAI"
    _module_name = "openai"

    def _instantiate_client(self, sdk: Any) -> Any:
        return sdk.OpenAI(api_key=self._key)

    def complete(self, system: str, user: str) -> str:
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except Exception as exc:  # noqa: BLE001 - surface actionable error
            raise SFAError(
                f"OpenAI 调用失败：{exc}\n"
                f"相关配置：ai.provider=openai, model={self._model}\n"
                "可操作建议：检查网络、API key 与模型名是否正确。"
            ) from exc
        content = resp.choices[0].message.content
        if content is None:
            raise SFAError(
                f"OpenAI 返回空内容。\n"
                f"相关配置：ai.provider=openai, model={self._model}\n"
                "可操作建议：重试，或更换模型。"
            )
        return content


class AnthropicClient(_RealLLMClient):
    _provider_name = "Anthropic"
    _module_name = "anthropic"

    def _instantiate_client(self, sdk: Any) -> Any:
        return sdk.Anthropic(api_key=self._key)

    def complete(self, system: str, user: str) -> str:
        try:
            resp = self._client.messages.create(
                model=self._model,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as exc:  # noqa: BLE001
            raise SFAError(
                f"Anthropic 调用失败：{exc}\n"
                f"相关配置：ai.provider=anthropic, model={self._model}\n"
                "可操作建议：检查网络、API key 与模型名是否正确。"
            ) from exc
        if not resp.content:
            raise SFAError(
                "Anthropic 返回空内容。\n"
                f"相关配置：ai.provider=anthropic, model={self._model}\n"
                "可操作建议：重试，或更换模型。"
            )
        text_parts: list[str] = []
        for block in resp.content:
            block_text = getattr(block, "text", None)
            if isinstance(block_text, str):
                text_parts.append(block_text)
        text = "".join(text_parts)
        if not text:
            raise SFAError(
                "Anthropic 返回无可读文本。\n"
                f"相关配置：ai.provider=anthropic, model={self._model}\n"
                "可操作建议：重试，或更换模型。"
            )
        return text


__all__ = [
    "LLMClient",
    "MockClient",
    "OpenAIClient",
    "AnthropicClient",
    "get_client",
]
