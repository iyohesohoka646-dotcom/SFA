"""Optional model providers; offline fixtures are the default, keys stay in the environment."""
from __future__ import annotations

import ast
import os
import time
from pathlib import Path

from .changes import propose_architecture, propose_implementation
from .context import build_context
from .models import ProjectSpec, canonical
from .paths import FlowError
from .storage import Store


def fixture_candidate(context: dict) -> str:
    """A deterministic example-backed implementation, explicitly limited to fixtures."""
    entry = context["entries"][0]
    tree = ast.parse(entry["source"])
    function = tree.body[0]
    examples = entry["contract"].get("examples", [])
    if not examples:
        raise FlowError("Offline generation needs contract examples containing input and output")
    args = [a.arg for a in function.args.posonlyargs + function.args.args + function.args.kwonlyargs]
    kwargs = "{" + ", ".join(repr(a) + ": " + a for a in args) + "}"
    body = []
    for example in examples:
        if "input" not in example or "output" not in example:
            raise FlowError("Each offline fixture requires input and output")
        if "[REDACTED" in canonical(example):
            raise FlowError("Redacted fixtures cannot be converted into implementation code")
        body.extend(ast.parse(f"if {kwargs} == {example['input']!r}:\n    return {example['output']!r}\n").body)
    body.extend(ast.parse("raise ValueError('Input is outside the reviewed offline fixtures')").body)
    function.body = body
    return ast.unparse(tree) + "\n"


def complete(context: dict, provider: str, model: str | None, timeout: float = 60, retries: int = 1) -> tuple[str, dict]:
    if not 0 < timeout <= 300 or not 0 <= retries <= 3:
        raise FlowError("Provider timeout/retry bounds exceeded")
    if provider == "mock":
        return fixture_candidate(context), {"provider": "mock", "mode": "contract_fixtures", "input_bytes": context["bytes"], "requests": 0}
    if provider not in ("openai", "anthropic") or not model:
        raise FlowError("Specify provider=openai|anthropic and an explicit model, or use mock")
    env_name = "OPENAI_API_KEY" if provider == "openai" else "ANTHROPIC_API_KEY"
    if not os.environ.get(env_name):
        raise FlowError(f"{env_name} is not configured in the process environment")
    system = "Implement only the approved Python function body. Preserve exact signature and decorators. Return one Python function. Follow the supplied contract and import policy."
    started = time.monotonic()
    try:
        if provider == "openai":
            from openai import OpenAI
            client = OpenAI(timeout=timeout, max_retries=retries)
            result = client.chat.completions.create(model=model, messages=[{"role": "system", "content": system}, {"role": "user", "content": canonical(context)}])
            text = result.choices[0].message.content or ""
        else:
            from anthropic import Anthropic
            client = Anthropic(timeout=timeout, max_retries=retries)
            result = client.messages.create(model=model, max_tokens=8192, system=system, messages=[{"role": "user", "content": canonical(context)}])
            text = "\n".join(c.text for c in result.content if hasattr(c, "text"))
        usage = result.usage.model_dump() if result.usage else {}
        return text, {"provider": provider, "model": model, "duration_ms": (time.monotonic() - started) * 1000, "usage": usage, "retry_limit": retries}
    except ImportError as exc:
        raise FlowError("Install the optional [ai] dependencies for this provider") from exc
    except Exception as exc:
        raise FlowError(f"Provider request failed ({type(exc).__name__}); credentials and response bodies are omitted") from exc


def generate(root: Path, module: str, level="L2", provider="mock", model=None):
    context = build_context(root, module, level)
    candidate, usage = complete(context, provider, model)
    return propose_implementation(root, module, candidate, title=f"{provider} implementation: {module}", usage=usage)
