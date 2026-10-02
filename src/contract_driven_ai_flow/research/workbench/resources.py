"""Declarative resource intake is separate from probe binding and execution."""

from __future__ import annotations

import re
import hashlib
import json
import sys
import threading
from .planning import fingerprint
from .process import run_process
from pathlib import Path
from jsonschema import Draft202012Validator, SchemaError
from .models import ProbeResource
from .store import WorkbenchStore


class ResourceManager:
    def __init__(self, root, catalog, tools=None):
        self.root = Path(root).resolve()
        self.store = WorkbenchStore(root)
        self.catalog = catalog
        self.tools = tools
        self._mutation_lock = threading.RLock()
        for raw in self.store.list("resources", limit=1000):
            resource = ProbeResource.model_validate(raw)
            if resource.status == "installed":
                try:
                    self._activate(resource)
                except ValueError as error:
                    resource.status = "error"
                    resource.diagnostics = [str(error)]
                    self.store.put("resources", resource.id, resource)

    def validate(self, resource):
        ids = set()
        for definition in resource.definitions:
            if (
                not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_.-]{0,127}", definition.id)
                or definition.id in ids
            ):
                raise ValueError(
                    "Resource definition identities must be valid and unique"
                )
            ids.add(definition.id)
            try:
                Draft202012Validator.check_schema(definition.parameter_schema)
            except SchemaError as error:
                raise ValueError("Invalid parameter schema") from error
            if definition.entrypoint and not re.fullmatch(
                r"[a-zA-Z_][\w.]*:[a-zA-Z_][\w.]*", definition.entrypoint
            ):
                raise ValueError("Program entry must be module:qualified_symbol")
        return resource

    def import_manifest(self, raw):
        resource = self.validate(ProbeResource.model_validate(raw)).model_copy(
            deep=True, update={"status": "draft", "review_digest": ""}
        )
        for definition in resource.definitions:
            definition.resource_id = resource.id
        with self._mutation_lock:
            try:
                active = ProbeResource.model_validate(
                    self.store.get("resources", resource.id)
                )
            except KeyError:
                active = None
            self.store.put(
                (
                    "resource_drafts"
                    if active and active.status == "installed"
                    else "resources"
                ),
                resource.id,
                resource,
            )
        return resource

    def _activate(self, resource):
        # Verify every collision before mutating the live registry.
        known = {definition.id: definition for definition in self.catalog.definitions()}
        for definition in resource.definitions:
            if (
                definition.id in known
                and known[definition.id].resource_id != resource.id
            ):
                raise ValueError("Resource cannot replace an existing probe definition")
        self.catalog.unregister_resource(resource.id)
        for definition in resource.definitions:
            self.catalog.register(
                definition.model_copy(
                    deep=True,
                    update={
                        "resource_id": resource.id,
                        "resource_version": resource.version,
                    },
                )
            )

    def enable(self, key, *, expected_digest=None):
        try:
            raw = self.store.get("resource_drafts", key)
        except KeyError:
            raw = self.store.get("resources", key)
        if expected_digest is not None and fingerprint(raw) != expected_digest:
            raise ValueError("Resource changed after review; reload its draft")
        reviewed_digest = fingerprint(raw)
        resource = self.validate(ProbeResource.model_validate(raw))
        from .configuration import ConfigurationStore

        interpreter = ConfigurationStore(self.root).load().interpreter or sys.executable
        dependencies = sorted(
            set(
                resource.dependencies
                + [dep for d in resource.definitions for dep in d.dependencies]
            )
        )
        if dependencies and not any(d.entrypoint for d in resource.definitions):
            code, stdout, stderr = run_process(
                [
                    interpreter,
                    "-X",
                    "utf8",
                    str(Path(__file__).with_name("program_worker.py")),
                ],
                input=json.dumps(
                    {
                        "root": str(self.root),
                        "action": "dependencies",
                        "dependencies": dependencies,
                    }
                ).encode(),
                cwd=self.root,
                cancel=threading.Event(),
                timeout=10,
            )
            if code:
                raise ValueError(
                    "Dependency validation failed: "
                    + stderr.decode("utf-8", errors="replace")[-1200:]
                )
        for definition in resource.definitions:
            if definition.entrypoint:
                request = {
                    "root": str(self.root),
                    "entrypoint": definition.entrypoint,
                    "action": "describe",
                    "dependencies": dependencies,
                }
                code, stdout, stderr = run_process(
                    [
                        interpreter,
                        "-X",
                        "utf8",
                        str(Path(__file__).with_name("program_worker.py")),
                    ],
                    input=json.dumps(request).encode(),
                    cwd=self.root,
                    cancel=threading.Event(),
                    timeout=10,
                )
                if code:
                    raise ValueError(
                        "Program entry validation failed: "
                        + stderr.decode("utf-8", errors="replace")[-1200:]
                    )
                receipt = json.loads(stdout)
                if not receipt.get("program_digest"):
                    raise ValueError("Program entry has no verifiable file")
                definition.implementation_digest = receipt["program_digest"]
        with self._mutation_lock:
            try:
                current = self.store.get("resource_drafts", key)
            except KeyError:
                current = self.store.get("resources", key)
            if fingerprint(current) != reviewed_digest:
                raise ValueError(
                    "Resource changed during validation; reload its draft for review"
                )
            self._activate(resource)
            resource.status = "installed"
            self.store.put("resources", key, resource)
            self.store.delete("resource_drafts", key)
        return resource

    def disable(self, key):
        resource = ProbeResource.model_validate(self.store.get("resources", key))
        self.catalog.unregister_resource(key)
        resource.status = "disabled"
        self.store.put("resources", key, resource)
        return resource

    def resources(self):
        records = self.store.list("resources", limit=1000)
        drafts = {r["id"]: r for r in self.store.list("resource_drafts", limit=1000)}
        for record in records:
            record["review_digest"] = fingerprint(drafts.get(record["id"], record))
            if record["id"] in drafts:
                record["pending_version"] = drafts[record["id"]]["version"]
        builtin = [
            definition
            for definition in self.catalog.definitions()
            if not definition.resource_id and not definition.tool_id
        ]
        records.append(
            ProbeResource(
                id="builtin",
                label="内置探针",
                version="3",
                source="builtin",
                status="installed",
                definitions=builtin,
            ).model_dump(mode="json")
        )
        if self.tools is not None:
            for tool in self.tools.catalog():
                records.append(
                    ProbeResource(
                        id="adapter." + tool["id"],
                        label=tool["label"],
                        source="public",
                        kind="adapter",
                        version=tool.get("version") or "uninstalled",
                        status=(
                            "installed"
                            if tool.get("available") and tool.get("enabled")
                            else "disabled" if tool.get("available") else "available"
                        ),
                        url=tool.get("url"),
                        definitions=[
                            definition
                            for definition in self.catalog.definitions()
                            if definition.tool_id == tool["id"]
                        ],
                    ).model_dump(mode="json")
                )
        return records
