"""Bounded, schema-validated project tools for the P4 intelligence loop.

Every tool is read-only or inert. There is deliberately no run/accept/terminal
tool, even under an ``allow_execute`` policy: project execution stays an explicit
human action outside the model loop.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import jsonschema

from ..agent.privacy import clean_text, sanitize_json

__all__ = ["ProjectToolRegistry"]

LIMIT_MAX = 32
MAX_READ_LINES = 200
MAX_READ_BYTES = 8192
MAX_TOTAL_READ_BYTES = 262144
MAX_READS = 128

_CHANGE_ROLE = "code"


def _object(properties, required=()):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


_PAGE = {
    "offset": {"type": "integer", "minimum": 0},
    "limit": {"type": "integer", "minimum": 1, "maximum": LIMIT_MAX},
}


class ProjectToolRegistry:
    def __init__(self, application, request, context, skills, changes):
        self.application = application
        self.request = request
        self.context = context
        self.skills = skills
        self.changes = changes
        self._lock = threading.RLock()
        self._cache: dict = {}
        self._suggestions: dict = {}
        self._reads = 0
        self._read_bytes = 0
        self._query = None

    # -- catalog -------------------------------------------------------
    def _definitions(self):
        tools = [
            {
                "name": "project.describe",
                "description": "Describe this project revision, entry intent and read permission summary.",
                "arguments": _object({}),
            },
            {
                "name": "symbols.search",
                "description": "Search indexed symbols/functions by name within the frozen revision.",
                "arguments": _object({"query": {"type": "string", "minLength": 1, "maxLength": 256}, **_PAGE}, ["query"]),
            },
            {
                "name": "references.find",
                "description": "Find candidate inferred references; candidates never grant source access.",
                "arguments": _object(
                    {
                        "file_id": {"type": "string", "maxLength": 128},
                        "logical_key": {"type": "string", "maxLength": 512},
                        **_PAGE,
                    }
                ),
            },
            {
                "name": "source.read",
                "description": "Read an authorized, indexed source range at the frozen digest (never executes it).",
                "arguments": _object(
                    {
                        "file_id": {"type": "string", "maxLength": 128},
                        "start_line": {"type": "integer", "minimum": 1},
                        "end_line": {"type": "integer", "minimum": 1},
                    },
                    ["file_id", "start_line", "end_line"],
                ),
            },
            {
                "name": "evidence.describe",
                "description": "Describe an authorized snapshot's metadata; raw samples require an explicit policy.",
                "arguments": _object({"snapshot_id": {"type": "string", "maxLength": 128}}, ["snapshot_id"]),
            },
            {
                "name": "probe.catalog",
                "description": "List registered probe definitions and their inert parameters.",
                "arguments": _object({}),
            },
            {
                "name": "probe.suggest",
                "description": "Validate and retain an inert probe binding suggestion; never applies configuration.",
                "arguments": _object(
                    {
                        "definition_id": {"type": "string", "maxLength": 128},
                        "targets": {"type": "array", "maxItems": 32, "items": {"type": "string", "maxLength": 512}},
                        "parameters": {"type": "object"},
                    },
                    ["definition_id", "targets", "parameters"],
                ),
            },
        ]
        if self.request.policy.role == _CHANGE_ROLE:
            tools.append(
                {
                    "name": "changes.propose",
                    "description": "Stage an inert multi-file change proposal for human review; never applies or runs it.",
                    "arguments": _object(
                        {
                            "edits": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 32,
                                "items": _object(
                                    {
                                        "path": {"type": "string", "maxLength": 512},
                                        "content": {"type": "string"},
                                        "operation": {"enum": ["modify", "create", "format"]},
                                    },
                                    ["path", "content"],
                                ),
                            }
                        },
                        ["edits"],
                    ),
                }
            )
        if self.skills.list():
            tools.append(
                {
                    "name": "skill.read",
                    "description": "Read an explicitly registered Skill snapshot; it grants no extra permissions.",
                    "arguments": _object({"skill_id": {"type": "string", "maxLength": 128}}, ["skill_id"]),
                }
            )
        return tools

    def describe(self, request):
        return self._definitions()

    # -- dispatch ------------------------------------------------------
    def call(self, name, arguments, request):
        if (
            request.project_id != self.request.project_id
            or request.project_revision_id != self.request.project_revision_id
        ):
            raise ValueError(
                "Tool request does not match this registry's bound project revision"
            )
        definitions = {tool["name"]: tool for tool in self._definitions()}
        if name not in definitions:
            raise ValueError("Tool is not registered for this task role")
        jsonschema.validate(arguments, definitions[name]["arguments"])
        handler = getattr(self, "_call_" + name.replace(".", "_"))
        receipt = handler(arguments)
        bounded = sanitize_json(receipt, string_limit=8192)
        return bounded

    def _receipt(self, reference, tool, data, coverage="", target=""):
        return {
            "reference": reference,
            "data": data,
            "receipt": {
                "reference": reference,
                "tool": tool,
                "project_id": self.context.project_id,
                "project_revision_id": self.context.project_revision_id,
                "coverage": coverage,
                "target": target,
            },
        }

    # -- project -------------------------------------------------------
    def _call_project_describe(self, arguments):
        plan = self.context.validate_request(self.request)
        allowed = plan["allowed"]
        data = {
            "project_id": self.context.project_id,
            "project_revision_id": self.context.project_revision_id,
            "revision": {"files": len(plan["rows"])},
            "entry": plan["entry"],
            "scope": {"mode": plan["mode"], "readable_files": len(allowed)},
            "permission_summary": (
                f"{len(allowed)} of {len(plan['rows'])} indexed files readable; "
                "non-indexed files and directory traversal denied"
            ),
        }
        reference = (
            "project:" + self.context.project_id + ":" + self.context.project_revision_id
        )
        return self._receipt(reference, "project.describe", data, coverage="frozen_revision")

    # -- symbols / references -----------------------------------------
    def _query_service(self):
        if self._query is None:
            from .queries import ProjectQueryService

            self._query = ProjectQueryService(self.application.projects, self.application)
        return self._query

    def _call_symbols_search(self, arguments):
        page = self._query_service().symbols(
            self.context.project_id,
            self.context.project_revision_id,
            q=arguments["query"],
            offset=arguments.get("offset", 0),
            limit=min(arguments.get("limit", 16), LIMIT_MAX),
        )
        data = {
            "items": [
                {
                    "name": item.name,
                    "kind": item.kind,
                    "scope": item.scope,
                    "line": item.line,
                    "end_line": item.end_line,
                    "logical_key": item.logical_key,
                    "file_id": item.source.file_id,
                    "path": item.source.path,
                    "digest": item.source.digest,
                }
                for item in page.items
            ],
            "total": page.total,
            "offset": page.offset,
            "limit": page.limit,
        }
        reference = (
            "symbols:" + self.context.project_revision_id + ":" + arguments["query"]
        )
        return self._receipt(reference, "symbols.search", data, coverage="indexed_revision")

    def _call_references_find(self, arguments):
        page = self._query_service().references(
            self.context.project_id,
            self.context.project_revision_id,
            file_id=arguments.get("file_id"),
            logical_key=arguments.get("logical_key"),
            offset=arguments.get("offset", 0),
            limit=min(arguments.get("limit", 16), LIMIT_MAX),
        )
        data = {
            "items": [
                {
                    "kind": item.kind,
                    "name": item.name,
                    "logical_key": item.logical_key,
                    "provenance": item.provenance,
                    "path": item.source.path,
                    "line": item.source.line,
                    "file_id": item.source.file_id,
                    "target_file_id": item.target.file_id if item.target else None,
                    "target_path": item.target.path if item.target else None,
                }
                for item in page.items
            ],
            "total": page.total,
            "offset": page.offset,
            "limit": page.limit,
            "note": "inferred candidates only; references do not grant source access",
        }
        reference = (
            "references:"
            + self.context.project_revision_id
            + ":"
            + (arguments.get("file_id") or "*")
            + ":"
            + (arguments.get("logical_key") or "*")
        )
        return self._receipt(reference, "references.find", data, coverage="inferred_candidates")

    # -- source --------------------------------------------------------
    def _call_source_read(self, arguments):
        file_id = arguments["file_id"]
        if not self.context.is_authorized(file_id):
            raise ValueError("Requested file is outside this task's authorized read scope")
        plan = self.context._plan_dict()
        row = plan["by_id"].get(file_id)
        if row is None:
            raise LookupError("Unknown file in the frozen revision")
        start = int(arguments["start_line"])
        end = int(arguments["end_line"])
        if end < start:
            raise ValueError("Source range end_line must not precede start_line")
        if end - start + 1 > MAX_READ_LINES:
            raise ValueError("Source read exceeds the 200-line task budget")
        ranges = self.context.authorized_ranges(file_id)
        if ranges is not None and not any(
            start >= low and end <= high for low, high in ranges
        ):
            raise ValueError("Requested lines are outside the authorized span")
        # Recheck disk identity even on a cache hit: a stale answer is never acceptable.
        self.context.assert_file_current(file_id)
        key = (file_id, row["digest"], start, end)
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None:
            return cached
        source = self.application.projects.source(
            self.context.project_id, file_id, self.context.project_revision_id
        )
        code = source.get("code")
        if code is None:
            raise ValueError("Archived source is unavailable for this file (coverage gap)")
        lines = code.splitlines()
        if start > len(lines) + 1:
            raise ValueError("Source range starts beyond the end of the file")
        chunk = "\n".join(lines[start - 1 : end])
        encoded = chunk.encode("utf-8")
        if len(encoded) > MAX_READ_BYTES:
            raise ValueError("Source range exceeds the 8 KiB task budget")
        with self._lock:
            if self._reads >= MAX_READS or self._read_bytes + len(encoded) > MAX_TOTAL_READ_BYTES:
                raise ValueError("Cumulative source read budget exhausted")
            self._reads += 1
            self._read_bytes += len(encoded)
        self.context.mark_read(file_id)
        data = {
            "file_id": file_id,
            "path": row["relative_path"],
            "project_id": self.context.project_id,
            "project_revision_id": self.context.project_revision_id,
            "digest": row["digest"],
            "start_line": start,
            "end_line": end,
            "code": clean_text(chunk, MAX_READ_BYTES),
            "coverage": "exact_indexed_revision",
        }
        reference = (
            "source:"
            + self.context.project_id
            + ":"
            + self.context.project_revision_id
            + ":"
            + file_id
            + ":"
            + row["digest"]
            + f":{start}-{end}"
        )
        receipt = self._receipt(
            reference, "source.read", data, coverage="exact_indexed_revision", target=row["relative_path"]
        )
        with self._lock:
            self._cache[key] = receipt
        return receipt

    # -- evidence ------------------------------------------------------
    def _call_evidence_describe(self, arguments):
        snapshot_id = arguments["snapshot_id"]
        if self.request.snapshot_id is not None and snapshot_id != self.request.snapshot_id:
            raise ValueError("Snapshot is outside this task's authorized evidence scope")
        store = self.application.workbench(self.context.project_id).research.store
        snapshot = store.snapshot(snapshot_id)
        if self.request.run_id is not None and snapshot.run_id != self.request.run_id:
            raise ValueError("Snapshot belongs to a different run than this task")
        source = snapshot.source
        if (
            source is None
            or source.project_id != self.context.project_id
            or source.project_revision_id != self.context.project_revision_id
        ):
            raise ValueError("Snapshot does not belong to this project revision")
        if not self.context.is_authorized(source.file_id):
            raise ValueError("Snapshot source file is outside this task's read scope")
        ranges = self.context.authorized_ranges(source.file_id)
        if ranges is not None:
            line = source.line or source.end_line
            if line <= 0 or not any(low <= line <= high for low, high in ranges):
                raise ValueError("Snapshot source is outside the task's authorized span")
        data = {
            "snapshot_id": snapshot.id,
            "run_id": snapshot.run_id,
            "name": snapshot.name,
            "version": snapshot.version,
            "descriptor": snapshot.descriptor.model_dump(mode="json"),
            "fidelity": snapshot.fidelity,
            "coverage": sanitize_json(snapshot.coverage),
            "truncation": list(snapshot.truncation),
            "redacted": bool(snapshot.redacted),
        }
        if self.request.policy.include_samples:
            data["sample"] = sanitize_json(snapshot.sample, string_limit=2048)
            data["sample_authorized"] = True
        reference = "evidence:" + snapshot.id + ":" + str(snapshot.version)
        return self._receipt(
            reference, "evidence.describe", data, coverage=snapshot.fidelity, target=snapshot.id
        )
    # -- probes --------------------------------------------------------
    def _call_probe_catalog(self, arguments):
        definitions = self.application.workbench(self.context.project_id).catalog.definitions()
        data = {
            "items": [
                {
                    "id": item.id,
                    "label": item.label,
                    "capability": item.capability,
                    "execution": item.execution,
                    "version": item.version,
                    "evidence": item.evidence,
                    "input_mode": item.input_mode,
                    "output_kinds": list(item.output_kinds),
                    "tool_id": item.tool_id,
                }
                for item in definitions[:64]
            ]
        }
        reference = "probe-catalog:" + self.context.project_revision_id
        return self._receipt(reference, "probe.catalog", data, coverage="registered_definitions")

    def _call_probe_suggest(self, arguments):
        catalog = self.application.workbench(self.context.project_id).catalog
        definition = catalog.resolve(arguments["definition_id"])
        parameters = arguments.get("parameters", {})
        if not isinstance(parameters, dict):
            raise ValueError("Probe parameters must be a mapping")
        schema = definition.parameter_schema or {}
        if schema:
            jsonschema.validate(parameters, schema)
        self._assert_targets_authorized(arguments["targets"])
        key = hashlib.sha256(
            json.dumps(
                {
                    "definition": definition.id,
                    "targets": arguments["targets"],
                    "parameters": parameters,
                },
                sort_keys=True,
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()[:24]
        suggestion = {
            "id": key,
            "definition_id": definition.id,
            "targets": list(arguments["targets"]),
            "parameters": sanitize_json(parameters),
            "status": "suggested",
            "applied": False,
        }
        with self._lock:
            self._suggestions[key] = suggestion
        reference = "probe-suggestion:" + self.context.project_revision_id + ":" + key
        return self._receipt(
            reference, "probe.suggest", suggestion, coverage="inert_suggestion"
        )

    def _assert_targets_authorized(self, targets):
        """A probe target must resolve to an identity inside the read scope.

        Unrecognized or name-guessed targets are rejected outright; a resolved
        function/variable target must fit inside the authorized spans, so mere
        file overlap is not enough.
        """
        if not isinstance(targets, list):
            raise ValueError("Probe targets must be a list")
        plan = self.context._plan_dict()
        for target in targets:
            if not isinstance(target, str) or not target.strip():
                raise ValueError("Probe targets must be non-empty strings")
            token = target.strip()
            resolved = self.context._scope_id_constraint(
                token, plan["rows"], plan["by_id"], plan["by_path"]
            )
            for file_id, span in resolved.items():
                if file_id not in plan["allowed"]:
                    raise ValueError(
                        "Probe target is outside this task's authorized scope: " + token
                    )
                allowed = plan["allowed"][file_id]
                if allowed is None:
                    continue
                if span is None:
                    raise ValueError(
                        "Probe target grants a whole file but only a span is authorized: "
                        + token
                    )
                for low, high in span:
                    if not any(lo <= low and high <= hi for lo, hi in allowed):
                        raise ValueError(
                            "Probe target span is outside this task's authorized span: "
                            + token
                        )

    # -- changes -------------------------------------------------------
    @staticmethod
    def _covered(ranges, start, end):
        return any(lo <= start and end <= hi for lo, hi in ranges)

    def _change_within_spans(self, file_id, candidate, ranges):
        """True only when every changed original line lies inside the span.

        Deletions/replacements must be fully inside a span; insertions must be
        anchored by covered neighbours. Ambiguous boundary insertions are denied
        conservatively with an explicit reason.
        """
        if ranges is None:
            return True, ""
        if not ranges:
            return False, "no line span is authorized in this file"
        plan = self.context._plan_dict()
        row = plan["by_id"].get(file_id)
        if row is None:
            raise ValueError("Unknown file in the frozen revision")
        root = Path(self.application.projects.project(self.context.project_id).root).resolve()
        target = root / row["relative_path"]
        if not target.is_file():
            raise ValueError("Project source is unavailable for span checking")
        # The archived source is redacted for display; line accounting must use
        # the actual current bytes that the change service will diff against.
        original = target.read_bytes().decode("utf-8", "replace")
        import difflib

        before = original.splitlines()
        after = candidate.splitlines()
        matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
        for tag, i1, i2, _j1, _j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            if tag in ("replace", "delete"):
                if i2 > i1 and not self._covered(ranges, i1 + 1, i2):
                    return False, "changed lines fall outside the authorized span"
            elif tag == "insert":
                if not self._insert_anchored(ranges, i1, len(before)):
                    return False, "inserted lines fall outside the authorized span"
        return True, ""

    def _insert_anchored(self, ranges, index, total):
        if total == 0:
            return False
        if index == 0:
            return self._covered(ranges, 1, 1)
        if index >= total:
            return self._covered(ranges, total, total)
        return self._covered(ranges, index, index) and self._covered(
            ranges, index + 1, index + 1
        )

    def _call_changes_propose(self, arguments):
        if self.request.policy.role != _CHANGE_ROLE:
            raise ValueError("Change proposals require the code task role")
        plan = self.context._plan_dict()
        allowed = self.context.authorized_paths()
        create_dirs = plan["create_dirs"]
        for edit in arguments["edits"]:
            if not isinstance(edit, dict):
                raise ValueError("Each edit must be a mapping")
            raw = str(edit.get("path", "")).replace("\\", "/")
            operation = edit.get("operation", "modify")
            if operation in ("modify", "format"):
                if raw not in allowed:
                    raise ValueError(
                        "Change target is outside the authorized read scope: " + raw
                    )
                file_id = allowed[raw]
                ok, reason = self._change_within_spans(
                    file_id,
                    edit.get("content", ""),
                    self.context.authorized_ranges(file_id),
                )
                if not ok:
                    raise ValueError(
                        "Change to " + raw + " rejected before staging: " + reason
                    )
            elif operation == "create":
                parent = raw.rsplit("/", 1)[0] if "/" in raw else ""
                if "" not in create_dirs and not any(
                    parent == directory or parent.startswith(directory + "/")
                    for directory in create_dirs
                ):
                    raise ValueError(
                        "New file parent is outside the authorized create scope: " + raw
                    )
            else:
                raise ValueError("Unsupported change operation")
        change = self.changes.propose(
            self.context.project_id,
            self.context.project_revision_id,
            list(arguments["edits"]),
        )
        data = {
            "id": change.id,
            "status": change.status,
            "base_revision": change.base_revision,
            "files": [
                {
                    "path": item.path,
                    "operation": item.operation,
                    "before_digest": item.before_digest,
                    "after_digest": item.after_digest,
                    "diagnostics": list(item.diagnostics),
                }
                for item in change.files
            ],
            "validation": [
                {"kind": item.kind, "status": item.status, "detail": item.detail}
                for item in change.validation
            ],
            "applied": False,
            "note": "Inert proposal staged for separate human acceptance; never run by the model.",
        }
        reference = "change-proposal:" + change.id
        return self._receipt(reference, "changes.propose", data, coverage="inert_proposal")
    # -- skills --------------------------------------------------------
    def _call_skill_read(self, arguments):
        skill = self.skills.load(arguments["skill_id"])
        data = {
            "id": skill["id"],
            "title": skill["title"],
            "version": skill["version"],
            "instructions": clean_text(skill["instructions"], 16384),
            "grants_capabilities": False,
        }
        reference = "skill:" + skill["id"]
        return self._receipt(reference, "skill.read", data, coverage="registered_skill")

