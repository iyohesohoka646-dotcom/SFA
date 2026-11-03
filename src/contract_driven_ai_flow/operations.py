"""User operations and discovery shared by installed CLI and Web adapters."""
from __future__ import annotations

import importlib.util
import os
import platform
import sys
from pathlib import Path

from . import __version__
from .compiler import compile_project
from .storage import Store


FEATURES = [
    {"id": "projects", "name": "Projects and examples", "web": "Workspace", "cli": "cdaf projects --help", "description": "Create blank or example projects, register existing folders, and unlink without deleting files."},
    {"id": "studio", "name": "Local Web UI", "web": "Workspace / connection", "cli": "cdaf studio --help", "description": "Start, reuse, inspect and stop an independent loopback service."},
    {"id": "init", "name": "Contract-first setup", "web": "Workspace / Create project", "cli": "cdaf init --help", "description": "Create authored definitions without overwriting an existing project."},
    {"id": "demo", "name": "Runnable examples", "web": "Workspace / Example templates", "cli": "cdaf demo --help", "description": "Three local examples with explicit success and quality-failure inputs."},
    {"id": "check", "name": "Compile diagnostics", "web": "Architecture / Validate", "cli": "cdaf check --help", "description": "Check bindings, schemas, hierarchy, expressions and cycles before execution."},
    {"id": "plan", "name": "Execution plan", "web": "Project tools / Plan", "cli": "cdaf plan --help", "description": "Inspect the compiled structure without executing project code."},
    {"id": "scan", "name": "Existing Python symbols", "web": "New module / Import or Project tools / Scan", "cli": "cdaf scan --help", "description": "File-qualified source candidates; inferred dependencies remain candidates."},
    {"id": "propose", "name": "Architecture editing", "web": "Architecture / Review & save or Project tools / Import proposal", "cli": "cdaf propose --help", "description": "Review module contracts, composites, explicit ports, guards and capture settings."},
    {"id": "run", "name": "Execution and evidence", "web": "Runs", "cli": "cdaf run --help", "description": "New isolated execution with revision-bound contract and quality evidence."},
    {"id": "runs", "name": "History and controls", "web": "Runs / Timeline", "cli": "cdaf runs --help", "description": "List history, inspect events, and control runs owned by the managed Studio."},
    {"id": "probe", "name": "Probes", "web": "Probes", "cli": "cdaf probe --help", "description": "Preview read-only rules; create, edit, disable or remove them through architecture review."},
    {"id": "context", "name": "AI visibility", "web": "Module / Context", "cli": "cdaf context --help", "description": "Inspect exact L1–L4 input, subject to binding caps and redaction."},
    {"id": "generate", "name": "Bounded code proposals", "web": "Module / Context", "cli": "cdaf generate --help", "description": "Fixture-based offline generation, configured providers or externally supplied code."},
    {"id": "review", "name": "Review and rollback", "web": "Review", "cli": "cdaf review --help", "description": "Inspect diffs and diagnostics, accept or reject, and propose inverse code patches."},
    {"id": "export", "name": "Portable exports", "web": "Export / Project tools", "cli": "cdaf export --help", "description": "Sanitized HTML, SVG, PNG, Mermaid, JSON, OTLP and optional pinned Archify rendering."},
    {"id": "migrate", "name": "Legacy migration", "web": "Workspace / Migration or Project tools", "cli": "cdaf migrate --help", "description": "Preview ambiguity, supply resolutions and write a separate destination with backup."},
    {"id": "clean", "name": "Storage maintenance", "web": "Project tools / Storage", "cli": "cdaf clean --help", "description": "Clear cache or explicitly prune completed runs; preserve authored definitions."},
    {"id": "doctor", "name": "Installation diagnosis", "web": "Project tools / Installation", "cli": "cdaf doctor --help", "description": "Check Python, shipped Web assets, architecture and optional provider readiness."},
    {"id": "shortcut", "name": "Launch shortcuts", "web": "Workspace / Shortcuts", "cli": "cdaf shortcut --help", "description": "Create launch/stop shortcuts bound to the installed interpreter."},
    {"id": "view", "name": "View preferences", "web": "Canvas / Save view", "cli": "cdaf view --help", "description": "Inspect or save graph positions, collapsed groups and theme independently of semantics."},
]


def capabilities():
    return {"version": __version__, "api_version": "v1", "features": FEATURES,
            "exports": ["html", "svg", "png", "mermaid", "json", "otel", "archify-json", "archify"],
            "templates": ["blank", "data-pipeline", "business-flow", "nested-composite"],
            "provider_credentials": "process environment", "legacy": "sfa legacy --help"}


def providers():
    return [{"id": "mock", "name": "Offline contract fixtures", "installed": True, "configured": True, "requires_model": False},
            *[{"id": name, "name": name.title(), "installed": importlib.util.find_spec(name) is not None,
               "configured": bool(os.environ.get(name.upper() + "_API_KEY")), "requires_model": True,
               "credential_environment": name.upper() + "_API_KEY"} for name in ("openai", "anthropic")]]


def doctor(root: Path | None = None):
    static = Path(__file__).parent / "static"
    checks = [{"name": "Python", "status": "passed" if sys.version_info >= (3, 11) else "failed", "detail": platform.python_version()},
              {"name": "Bundled Web UI", "status": "passed" if (static / "index.html").is_file() and any((static / "assets").glob("index-*.js")) else "failed",
               "detail": "Included in the Python installation", "remedy": "Reinstall a built release package; source developers run npm ci && npm run build in web/"}]
    if root is not None:
        plan = compile_project(Store(root).load())
        checks.append({"name": "Project compilation", "status": "passed" if plan.valid else "failed", "detail": str(root.resolve()),
                       "diagnostics": [d.model_dump() for d in plan.diagnostics], "remedy": "Inspect Architecture / Validate or cdaf check"})
    return {"version": __version__, "python": sys.executable, "checks": checks, "providers": providers(),
            "healthy": all(item["status"] == "passed" for item in checks)}
