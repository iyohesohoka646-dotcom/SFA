"""Machine-only local runtime settings for project launch references.

Interpreter paths and private environment values live in the host state
directory and are never written into project ``workbench.yaml``, public
plans or HTTP-facing receipts. Project documents only carry symbolic
references (``interpreter_ref`` / ``environment`` names).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def settings_path(host_root: Path) -> Path:
    return Path(host_root).resolve() / ".cdaf" / "runtime.json"


def load_machine_settings(host_root: Path) -> dict:
    path = settings_path(host_root)
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def resolve_interpreter(host_root: Path, interpreter_ref: str | None) -> str:
    """Resolve a symbolic interpreter reference; default to this interpreter."""
    settings = load_machine_settings(host_root)
    interpreters = settings.get("interpreters", {})
    reference = (interpreter_ref or "").strip()
    if not reference:
        if "default" in interpreters:
            return str(interpreters["default"])
        return sys.executable
    if not isinstance(interpreters, dict) or reference not in interpreters:
        raise ValueError("Unknown interpreter reference: " + reference)
    return str(interpreters[reference])


def resolve_environment(host_root: Path, names) -> dict:
    """Resolve symbolic environment references into private values."""
    settings = load_machine_settings(host_root)
    environment = settings.get("environment", {})
    resolved: dict = {}
    for name in names or ():
        if not isinstance(environment, dict) or name not in environment:
            raise ValueError("Unknown environment reference: " + str(name))
        resolved[str(name)] = str(environment[name])
    return resolved


def environment_summary(interpreter_ref: str | None, names) -> dict:
    """Public, secret-free description frozen onto a plan."""
    return {
        "interpreter_ref": (interpreter_ref or "").strip(),
        "environment": [str(name) for name in (names or ())],
    }