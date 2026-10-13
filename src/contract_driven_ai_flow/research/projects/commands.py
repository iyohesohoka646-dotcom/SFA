"""P3 adapter: project commands compose the accepted ProjectApplication only.

Shared by the batch CLI and the interactive/HTTP dispatch. Every command is
keyed by an explicit ``project_id`` (``open`` carries a ``path`` instead); no
ambient current project ever participates. Indexing, planning and execution are
never re-implemented here, they are delegated to ``ProjectApplication``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ..workbench.models import RunConfiguration


def _scrub(value):
    """Remove the concrete machine interpreter from public plan JSON."""
    interpreter = sys.executable
    if isinstance(value, dict):
        return {key: _scrub(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    if isinstance(value, str) and interpreter and interpreter in value:
        return value.replace(interpreter, "<authored-interpreter>")
    return value


def _load_json_argument(value):
    if value is None or value == "":
        return None
    if isinstance(value, (dict, list)):
        return value
    text = str(value).strip()
    if text[:1] in ("{", "["):
        return json.loads(text)
    return json.loads(Path(text).read_text(encoding="utf-8-sig"))


def _scope_selector(value):
    raw = _load_json_argument(value)
    if raw is None:
        return None
    if isinstance(raw, list):
        return {"mode": "selection", "targets": raw}
    if not isinstance(raw, dict):
        raise ValueError("Plan targets must be a selector object or a target list")
    return raw


def _entries_list(value):
    raw = _load_json_argument(value)
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError("Run configuration entries must be a JSON array")
    return [RunConfiguration.model_validate(item) for item in raw]


def _plan_public(plan):
    return _scrub(plan.model_dump(mode="json"))


def _info(application, project_id):
    project = application.projects.project(project_id)
    data = project.model_dump(mode="json")
    data["entries"] = [
        entry.model_dump(mode="json") for entry in application.projects.entries(project_id)
    ]
    return data


def _entries(application, arguments):
    project_id = arguments["project_id"]
    config = application.workbench(project_id).configurations.load()
    entries = _entries_list(arguments.get("entries", arguments.get("save")))
    if entries is not None:
        saved = application.save_entries(
            project_id, entries, expected_revision=config.revision
        )
        return saved.model_dump(mode="json")
    revision_id = arguments.get("revision_id") or application.projects.project(
        project_id
    ).latest_revision_id
    return {
        "project_id": project_id,
        "revision_id": revision_id or "",
        "config_revision": config.revision,
        "entries": [
            entry.model_dump(mode="json")
            for entry in application.projects.entries(project_id)
        ],
        "candidates": [
            candidate.model_dump(mode="json")
            for candidate in application.entry_candidates(project_id, revision_id)
        ],
    }


def execute_command(command, arguments, application, settings=None):
    """Run one project command against ``application`` and return JSON data."""
    if command == "open":
        return application.open(arguments["path"]).model_dump(mode="json")
    project_id = arguments.get("project_id")
    if command == "index":
        return application.index(project_id).model_dump(mode="json")
    if command == "info":
        return _info(application, project_id)
    if command == "graph":
        # Same query semantics as the HTTP graph route: boundaries, projections
        # and limits, never a raw ProjectService slice.
        from .queries import ProjectQueryService

        queries = ProjectQueryService(application.projects, application)
        sliced = queries.graph(
            project_id,
            revision_id=arguments.get("revision_id") or None,
            scope_id=arguments.get("scope_id") or None,
            view=arguments.get("view") or "code",
            limit=arguments.get("limit") or 350,
        )
        return sliced.model_dump(mode="json")
    if command == "entries":
        return _entries(application, arguments)
    if command == "plan":
        plan = application.plan(
            project_id,
            arguments["configuration_id"],
            revision_id=arguments.get("revision_id") or None,
            scope=arguments.get("scope") or "compute",
            run_id=arguments.get("run_id") or None,
            snapshot_ids=arguments.get("snapshot_ids") or (),
            instance_ids=_load_json_argument(arguments.get("instances", arguments.get("instance_ids"))),
            target_scope=_scope_selector(arguments.get("target_scope", arguments.get("targets"))),
        )
        return _plan_public(plan)
    if command == "run":
        task = application.execute(project_id, arguments["plan_id"])
        return task.model_dump(mode="json")
    raise ValueError("Unknown project command: " + str(command))

