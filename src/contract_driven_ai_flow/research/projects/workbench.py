"""Project-scoped WorkbenchService branch.

Reuses the P1 WorkbenchService probe catalog, configuration/templates,
evaluation, outputs, semantics/tools and jobs. Only planning and execution are
extended so a project entry (with cross-file observation) runs through the P2a
``run_project`` runtime instead of the single-script path.

Planning stays compact: a plan freezes the compact selector, the authored
configuration and the registered definitions (plus a manifest pointer) and
never materialises every project object as invocations. After a run the exact
captured evidence is projected back onto the per-file indexes and the frozen
effective probes are instantiated over it, so a later configuration edit can
never silently change an already prepared computation.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ..agent.privacy import clean_text
from ..agent.source import read_source
from ..models import ProbeSpec, SourceRef
from ..workbench.models import AnalysisDocument, ExecutionPlan, WorkbenchConfig
from ..workbench.planning import fingerprint
from ..workbench.scopes import source_targets
from ..workbench.semantic_models import GraphBlock, GraphEdge, ScopeSelector, SemanticGraph
from ..workbench.service import WorkbenchService
from . import local_runtime, runtime
from .resolver import _folders_for, _id

MAX_CONTEXT_FILES = 256


class ProjectWorkbenchService(WorkbenchService):
    def __init__(
        self,
        research,
        *,
        project_id: str,
        project_root,
        host_root,
        projects=None,
        models=None,
    ):
        super().__init__(research)
        self.project_id = project_id
        self.project_root = Path(project_root).resolve()
        self.host_root = Path(host_root).resolve()
        self.projects = projects
        if models is not None:
            # Shared, caller-owned model settings: never close what we do not own.
            self.models = models
            self._owns_models = False
        # Bounded per-plan postprocessing context; never persisted.
        self._contexts: dict = {}

    # -- authored entries ---------------------------------------------
    def entry(self, configuration_id: str):
        config = self.configurations.load()
        entry = next(
            (c for c in config.run_configurations if c.id == configuration_id), None
        )
        if entry is None:
            raise LookupError("Unknown run configuration: " + configuration_id)
        return config, entry

    def save_entries(self, entries, *, expected_revision):
        config = self.configurations.load()
        updated = config.model_copy(deep=True, update={"run_configurations": list(entries)})
        return self.configurations.save(updated, expected_revision=expected_revision)

    # -- indexed per-file reads ---------------------------------------
    def _project_analysis(self, analysis_id, revision_id=None):
        if self.projects is None:
            raise LookupError("Project index is unavailable")
        return self.projects.analysis_by_id(self.project_id, analysis_id, revision_id)

    def analysis(self, key):
        """Prefer the frozen per-file project index over the entry-only store."""
        try:
            return self._project_analysis(key)
        except (KeyError, LookupError):
            return super().analysis(key)

    def analysis_source(self, key):
        if self.projects is not None:
            try:
                source = self.projects.source_by_analysis_id(self.project_id, key)
            except (KeyError, LookupError):
                source = None
            if source is not None:
                return {
                    "path": source["path"],
                    "digest": source["digest"],
                    "code": source["code"],
                    "file_id": source["file_id"],
                    "revision_id": source["revision_id"],
                    "project_id": source["project_id"],
                }
        return super().analysis_source(key)

    def presenters(self, snapshot_id, analysis_id=None):
        snapshot = self.research.store.snapshot(snapshot_id)
        source = snapshot.source
        analysis = None
        if analysis_id:
            try:
                analysis = self.analysis(analysis_id)
            except (KeyError, LookupError):
                analysis = None
        elif source and source.file_id:
            # The exact per-file frozen document; a mismatched revision/file is a
            # clear failure, never a silently empty default analysis.
            if self.projects is None:
                raise ValueError("Snapshot evidence has no project index to resolve against")
            try:
                analysis = self.projects.analysis(
                    self.project_id, source.file_id, source.project_revision_id
                )
            except (KeyError, LookupError) as error:
                raise ValueError(
                    "Snapshot evidence does not belong to this indexed revision: "
                    + str(error)
                ) from error
        if analysis is None:
            return super().presenters(snapshot_id, analysis_id)
        from ..workbench.bindings import effective_presenters

        return effective_presenters(
            self.configurations.load(), self.catalog.definitions(), snapshot, analysis
        )

    # -- planning -----------------------------------------------------
    def plan_project(
        self,
        configuration_id: str,
        *,
        revision_id: str,
        entry_relative: str,
        entry_analysis_id: str,
        manifest: dict,
        entry_public: dict,
        scope: str = "compute",
        run_id=None,
        snapshot_ids=(),
        instance_ids=None,
        target_scope=None,
        frozen_config=None,
    ) -> ExecutionPlan:
        if scope not in ("compute", "probes", "replot"):
            raise ValueError("Unknown project plan scope: " + str(scope))
        if frozen_config is not None:
            # Evidence-only reuse: keep the config exactly as it was reviewed
            # when the run was prepared; never silently recompile.
            config = (
                frozen_config
                if isinstance(frozen_config, WorkbenchConfig)
                else WorkbenchConfig.model_validate(frozen_config)
            )
            run_config = None
        else:
            config, run_config = self.entry(configuration_id)
        entry_path = (self.project_root / entry_relative).resolve()
        entry_info = manifest.get(str(entry_path))
        if entry_info is None:
            raise ValueError("Entry script does not exist in the frozen revision")
        if scope == "compute":
            source = read_source(entry_path)
            if source.digest != entry_info["digest"]:
                raise ValueError("Entry source changed; index the project again")
        # Interpreter stays private: the public plan only carries symbolic refs.
        resolved_interpreter = config.interpreter or sys.executable
        selector = ScopeSelector.model_validate(target_scope or {"mode": "project"})
        resolved: list = []
        if selector.mode in ("selection", "block"):
            resolved = self._resolve_plan_targets(revision_id, selector)
        if run_config is not None:
            arguments = list(run_config.arguments)
            capture = run_config.options.get("capture") or config.capture
        else:
            arguments = list(config.arguments)
            capture = config.capture
        script_config = config.model_copy(
            deep=True,
            update={
                "script": str(entry_path),
                "interpreter": config.interpreter,
                "arguments": arguments,
                "capture": capture,
            },
        )
        if instance_ids is not None:
            wanted = set(instance_ids)
            if wanted - {probe.id for probe in script_config.probes}:
                raise ValueError("Requested probe instance is not configured")
            script_config = script_config.model_copy(
                deep=True,
                update={"probes": [p for p in script_config.probes if p.id in wanted]},
            )
        if scope != "compute":
            self._check_evidence_run(run_id, revision_id)
        definitions = self.catalog.definitions()
        environment = self.tools.scan(resolved_interpreter)
        manifest_id = runtime.save_manifest(self.project_root, manifest)
        plan = ExecutionPlan(
            analysis_id=entry_analysis_id,
            source_digest=entry_info["digest"],
            config_digest=fingerprint(script_config),
            environment_digest=fingerprint(environment),
            config=script_config,
            definitions=definitions,
            scope=scope,
            run_id=run_id if scope != "compute" else None,
            snapshot_ids=list(snapshot_ids) if scope != "compute" else [],
            target_scope=selector.model_copy(deep=True),
            resolved_targets=resolved,
            invocations=[],
        )
        plan = plan.model_copy(
            update={
                "preferences": self.preferences.load()["values"],
                "project_id": self.project_id,
                "project_revision_id": revision_id,
                "manifest_id": manifest_id,
                "entry": entry_public,
                "environment": local_runtime.environment_summary(
                    entry_public.get("interpreter_ref"), entry_public.get("environment")
                ),
                "diagnostics": [
                    f"Project revision {revision_id}: {len(manifest)} frozen sources",
                    "Compact plan: targets and probes are resolved from captured evidence",
                ],
            }
        )
        self.store.put("plans", plan.id, plan)
        return plan

    @staticmethod
    def _run_key(run_id: str) -> str:
        return "project-run:" + str(run_id)

    def _run_context(self, run_id):
        if not run_id:
            raise ValueError("Saved evidence requires a completed project run")
        try:
            return self.store.get("contexts", self._run_key(run_id))
        except KeyError:
            raise ValueError("Saved run is not a project computation of this project")

    def _check_evidence_run(self, run_id, revision_id):
        context = self._run_context(run_id)
        if context.get("project_id") != self.project_id:
            raise ValueError("Saved run belongs to another project")
        if context.get("project_revision_id") != revision_id:
            raise ValueError("Saved run belongs to another project revision")
        return context

    # -- historical evidence replot -----------------------------------
    def _evidence_plan(
        self, run_id, *, scope, snapshot_ids=(), instance_ids=None, target_scope=None
    ):
        """Rebuild an evidence-only plan from the saved frozen project run."""
        context = self._run_context(run_id)
        revision_id = context.get("project_revision_id")
        entry_relative = context.get("entry_relative")
        configuration_id = context.get("configuration_id")
        if not revision_id or not entry_relative:
            raise ValueError("Saved run has no frozen project entry")
        units = self._revision_units(revision_id)
        entry_unit = next(
            (u for u in units if u.relative_path == entry_relative), None
        )
        if entry_unit is None:
            raise ValueError("Saved entry is not part of the indexed revision")
        manifest = runtime.build_manifest(
            self.project_root, self.project_id, revision_id, units
        )
        entry_public = dict(context.get("entry") or {})
        entry_public.update(
            {
                "relative": entry_relative,
                "file_id": entry_unit.id,
                "analysis_id": entry_unit.analysis_id,
                "configuration_id": configuration_id,
            }
        )
        return self.plan_project(
            configuration_id,
            revision_id=revision_id,
            entry_relative=entry_relative,
            entry_analysis_id=entry_unit.analysis_id,
            manifest=manifest,
            entry_public=entry_public,
            scope=scope,
            run_id=run_id,
            snapshot_ids=snapshot_ids,
            instance_ids=instance_ids,
            target_scope=target_scope,
            frozen_config=context.get("configuration"),
        )

    def execute_probes(
        self, run_id, *, snapshot_ids=(), instance_ids=None, target_scope=None
    ):
        plan = self._evidence_plan(
            run_id,
            scope="probes",
            snapshot_ids=snapshot_ids,
            instance_ids=instance_ids,
            target_scope=target_scope,
        )
        return self.execute_plan(plan.id)

    def replot(
        self, run_id, *, snapshot_ids=(), instance_ids=None, target_scope=None
    ):
        plan = self._evidence_plan(
            run_id,
            scope="replot",
            snapshot_ids=snapshot_ids,
            instance_ids=instance_ids,
            target_scope=target_scope,
        )
        return self.execute_plan(plan.id)


    def _resolve_plan_targets(self, revision_id: str, selector: ScopeSelector) -> list:
        """Validate frozen canonical keys against the per-file revision indexes.

        Structural (folder/project) selections are validated against the frozen
        revision manifest prefix, never by loading every file analysis document.
        """
        wanted = selector.targets
        # A foreign owner/revision is rejected up front; another project's folder
        # key is never silently reinterpreted as a local one.
        for ref in wanted:
            if ref.project_id and ref.project_id != self.project_id:
                raise ValueError(
                    "Selected target belongs to another project: " + str(ref.logical_key)
                )
            if ref.project_revision_id and ref.project_revision_id != revision_id:
                raise ValueError(
                    "Selected target belongs to another project revision: "
                    + str(ref.logical_key)
                )
        units = None
        if any(ref.kind == "folder" for ref in wanted):
            units = self._revision_units(revision_id)
        resolved: list = []
        file_refs: list = []
        for ref in wanted:
            if ref.kind in ("folder", "project"):
                parts = ref.logical_key.split("::")
                owner = parts[0] if parts else ""
                if owner and owner != self.project_id:
                    raise ValueError(
                        "Selected target belongs to another project: "
                        + str(ref.logical_key)
                    )
                if ref.kind == "project":
                    block_id = _id("project", self.project_id)
                else:
                    path = "::".join(parts[2:]) if len(parts) >= 3 else ""
                    if not path or not any(
                        unit.relative_path.startswith(path + "/") for unit in units
                    ):
                        raise ValueError(
                            "Selected folder is unavailable in this project revision: "
                            + str(ref.logical_key)
                        )
                    block_id = _id("folder", self.project_id, path)
                # Compact structural identity: no member is expanded into an
                # invocation here; the hierarchy is rebuilt from captured evidence.
                resolved.append(
                    ref.model_copy(
                        deep=True,
                        update={
                            "project_id": self.project_id,
                            "project_revision_id": revision_id,
                            "block_id": block_id,
                        },
                    )
                )
                continue
            file_refs.append(ref)
        file_ids = [ref.file_id for ref in file_refs if ref.file_id]
        if file_refs and not file_ids:
            if units is None:
                units = self._revision_units(revision_id)
            file_ids = [unit.id for unit in units]
        index: dict = {}
        for file_id in dict.fromkeys(file_ids):
            document = self.projects.analysis(self.project_id, file_id, revision_id)
            for target in source_targets(document):
                index.setdefault((target.kind, target.logical_key), target)
        for ref in file_refs:
            hit = index.get((ref.kind, ref.logical_key))
            if hit is None:
                if selector.mode == "block" and ref.kind in (
                    "function",
                    "control",
                    "file",
                    "folder",
                    "project",
                    "stream",
                ):
                    # Block scope resolves against the runtime hierarchy; a stale
                    # block identity is reported instead of silently ignored.
                    continue
                raise ValueError(
                    "Selected target is unavailable in this project revision: "
                    + str(ref.logical_key)
                )
            update = {
                "project_id": self.project_id,
                "project_revision_id": revision_id,
            }
            # Preserve the exact requested per-file identity; a per-file hit
            # carries no file owner of its own.
            if ref.file_id:
                update["file_id"] = ref.file_id
            resolved.append(hit.model_copy(deep=True, update=update))
        return resolved

    def _revision_units(self, revision_id: str):
        units = []
        offset = 0
        while True:
            page = self.projects.files(self.project_id, revision_id, offset=offset, limit=1000)
            units.extend(page.items)
            offset += len(page.items)
            if offset >= page.total or not page.items:
                break
        return units

    # -- execution ----------------------------------------------------
    def execute_plan(self, plan_id: str):
        plan = ExecutionPlan.model_validate(self.store.get("plans", plan_id))
        if plan.project_id != self.project_id:
            raise ValueError("Plan belongs to another project")
        if plan.protocol_version != 3:
            raise ValueError("Legacy plan must be prepared again with the current protocol")
        if plan.scope == "compute":
            # The current authored configuration may only drive a NEW computation.
            current = self.configurations.load()
            if current.revision != plan.config.revision:
                raise ValueError(
                    "Configuration revision changed after planning (frozen revision "
                    f"{plan.config.revision}, current {current.revision}); prepare a new plan"
                )
        else:
            # Evidence-only scopes reuse the original project revision frozen on
            # the run; a mismatched run/revision is rejected explicitly.
            self._check_evidence_run(plan.run_id, plan.project_revision_id)
            run = self.research.store.run(plan.run_id)
            if run["status"] not in (
                "completed",
                "failed",
                "cancelled",
                "timeout",
                "interrupted",
            ):
                raise ValueError("Wait for computation before evaluating saved evidence")
            return self.jobs.submit(
                "project",
                lambda task, cancel: self._execute_evidence(plan, task, cancel),
                plan_id=plan.id,
                receipt={
                    "project_id": plan.project_id,
                    "project_revision_id": plan.project_revision_id,
                },
            )
        # Frozen digests are validated synchronously so a changed dependency
        # fails the call itself, not only the background task. The job
        # rechecks before the actual launch as well.
        manifest = runtime.load_manifest(self.project_root, plan.manifest_id)
        runtime.verify_manifest(self.project_root, manifest)
        return self.jobs.submit(
            "project",
            lambda task, cancel: self._execute_project(plan, task, cancel),
            plan_id=plan.id,
            receipt={
                "project_id": plan.project_id,
                "project_revision_id": plan.project_revision_id,
            },
        )

    def _execute_evidence(self, plan: ExecutionPlan, task, cancel):
        self.jobs.update(
            task.id,
            run_id=plan.run_id,
            project_id=self.project_id,
            project_revision_id=plan.project_revision_id,
            calculation_status="completed",
        )
        self._contexts[plan.id] = self._build_context(plan, plan.run_id)
        try:
            result = super()._postprocess(plan, plan.run_id, task, cancel)
        finally:
            self._contexts.pop(plan.id, None)
        return {"run_id": plan.run_id, "calculation_status": "completed", **result}

    def _evidence_calls(self, plan, analysis, run_id):
        if plan.scope == "compute":
            return super()._evidence_calls(plan, analysis, run_id)
        # Frozen configuration/definitions evaluated over the recorded evidence.
        return self._target_calls(plan, analysis, run_id)

    def _capture_specs(self, plan: ExecutionPlan):
        """Runtime gate specs and full-capture keys from the frozen config.

        Full capture is derived from the exact enabled probe inputs/selectors
        (intersected with an explicit plan selection) instead of from an
        implicit whole-project default.
        """
        definitions = {definition.id: definition for definition in plan.definitions}
        bounded = plan.target_scope.mode in ("selection", "block") and bool(
            plan.resolved_targets
        )
        plan_keys = {
            target.logical_key
            for target in plan.resolved_targets
            if target.kind == "data" and target.logical_key
        }

        def instance_keys(instance) -> set:
            keys: set = set()
            for ref in (instance.inputs or {}).values():
                if ref.logical_key:
                    keys.add(ref.logical_key)
            selector = instance.selector
            if selector is not None:
                for ref in selector.targets:
                    if ref.logical_key:
                        keys.add(ref.logical_key)
            return keys

        grouped: dict = {}
        full: list = []
        for instance in plan.config.probes:
            if not instance.enabled:
                continue
            definition = definitions.get(instance.definition_id)
            if definition is None:
                continue
            probe_keys = instance_keys(instance)
            gate_keys = sorted(plan_keys) if bounded else sorted(probe_keys)
            if (
                definition.capability == "check"
                and definition.execution == "program"
                and not definition.entrypoint
            ):
                signature = (instance.id, fingerprint(instance.parameters))
                grouped.setdefault(
                    signature,
                    ProbeSpec(
                        id=instance.id,
                        kind=definition.id.removeprefix("check."),
                        binding=instance.binding,
                        parameters=instance.parameters,
                        policy=instance.policy,
                        target_keys=gate_keys or None,
                        budget_ms=min(instance.budget_ms, 30000),
                    ),
                )
            if definition.evidence in ("full", "full_coordinates"):
                selected = probe_keys & plan_keys if bounded else probe_keys
                full.extend(sorted(selected))
        return [spec.model_dump(mode="json") for spec in grouped.values()], list(
            dict.fromkeys(full)
        )

    def _execute_project(self, plan: ExecutionPlan, task, cancel):
        manifest = runtime.load_manifest(self.project_root, plan.manifest_id)
        runtime.verify_manifest(self.project_root, manifest)
        entry = plan.entry or {}
        entry_relative = entry.get("relative") or entry.get("target", "")
        entry_path = (self.project_root / entry_relative).resolve()
        entry_info = manifest.get(str(entry_path))
        if entry_info is None:
            raise ValueError("Entry script is not part of the frozen manifest")
        config = plan.config
        reference = entry.get("interpreter_ref") or ""
        interpreter = (
            local_runtime.resolve_interpreter(self.host_root, reference)
            if reference
            else (config.interpreter or sys.executable)
        )
        private_env = local_runtime.resolve_environment(
            self.host_root, entry.get("environment", [])
        )
        working = runtime.resolve_cwd(self.project_root, entry.get("cwd"))
        if cancel.is_set():
            raise InterruptedError()
        checks, full_targets = self._capture_specs(plan)
        capture = {
            **{
                key: value
                for key, value in (plan.preferences.get("capture", {}) or {}).items()
                if key != "level"
            },
            "full_targets": full_targets,
        }
        handle = self.research.start_analysis(
            entry_path,
            interpreter=interpreter,
            arguments=config.arguments,
            mode=config.capture,
            probes=checks,
            adapters=config.adapters,
            capture=capture,
            expected_digest=entry_info["digest"],
            cwd=working,
            env=private_env,
            run_environment={
                "project_id": self.project_id,
                "project_revision_id": plan.project_revision_id,
            },
            project_job={
                "mode": "project",
                "root": str(self.project_root),
                "entry": {"kind": entry.get("kind", "script"), "target": entry.get("target", "")},
                "manifest_path": str(runtime.manifest_file(self.project_root, plan.manifest_id)),
                "instrument": "auto",
            },
        )
        run_id = handle.run_id
        self.store.put(
            "contexts",
            self._run_key(run_id),
            {
                "project_id": self.project_id,
                "project_revision_id": plan.project_revision_id,
                "entry_relative": entry_relative,
                "manifest_id": plan.manifest_id,
                "configuration_id": entry.get("configuration_id"),
                "entry": dict(entry),
                "configuration": config.model_dump(mode="json"),
            },
        )
        self.jobs.update(
            task.id,
            run_id=run_id,
            project_id=self.project_id,
            project_revision_id=plan.project_revision_id,
            calculation_status="running",
        )
        while True:
            if cancel.is_set():
                self.research.cancel(run_id)
                self.jobs.update(task.id, calculation_status="cancelled")
                raise InterruptedError()
            try:
                run = self.research.wait(run_id, timeout=0.1)
                break
            except TimeoutError:
                status = self.research.calculation_status(run_id)
                if status != self.jobs.get(task.id).calculation_status:
                    self.jobs.update(
                        task.id,
                        calculation_status=status,
                        message=(
                            "Probe gate paused; inspect its result before continuing"
                            if status == "paused"
                            else ""
                        ),
                    )
        self.jobs.update(task.id, calculation_status=run["status"], progress=0.6)
        if run["status"] != "completed":
            return {
                "status": "failed",
                "run_id": run_id,
                "calculation_status": run["status"],
                "message": self._failure_reason(run, run_id),
            }
        # Frozen definitions/config + exact captured evidence; no recompilation
        # against the current authored configuration.
        self._contexts[plan.id] = self._build_context(plan, run_id)
        try:
            result = super()._postprocess(plan, run_id, task, cancel)
        finally:
            self._contexts.pop(plan.id, None)
        return {"run_id": run_id, "calculation_status": run["status"], **result}

    def analysis_context(self, plan: ExecutionPlan):
        cached = self._contexts.get(plan.id)
        if cached is not None:
            return cached
        return super().analysis_context(plan)

    def _build_context(self, plan: ExecutionPlan, run_id: str) -> AnalysisDocument:
        """Bounded multi-file projection of the exact captured evidence.

        Per-file block identities are retained exactly as target resolution was
        frozen against them; a canonical project/folder ancestor chain is wrapped
        around the actual captured file roots so a structural selection can match
        by canonical logical key without loading unrequested files.
        """
        revision_id = plan.project_revision_id
        file_ids: list = []
        if plan.entry and plan.entry.get("file_id"):
            file_ids.append(plan.entry["file_id"])
        for target in plan.target_scope.targets:
            if target.file_id:
                file_ids.append(target.file_id)
        snapshots = self.research.store.snapshots(
            run_id, latest=True, limit=10000, metadata_only=True
        )
        for snapshot in snapshots:
            source = snapshot.source
            if (
                source
                and source.file_id
                and source.project_revision_id == revision_id
            ):
                file_ids.append(source.file_id)
        ordered_ids = list(dict.fromkeys(file_ids))
        if len(ordered_ids) > MAX_CONTEXT_FILES:
            # Never silently drop evidence: report the budget breach explicitly.
            raise ValueError(
                f"Evidence context exceeds the {MAX_CONTEXT_FILES}-file budget "
                f"({len(ordered_ids)} referenced files)"
            )
        unit_paths = {
            unit.id: unit.relative_path for unit in self._revision_units(revision_id)
        }
        objects, relations, nodes, edges = [], [], [], []
        roots: list = []
        block_map: dict = {}
        file_roots: dict = {}
        seen_nodes: set = set()
        seen_edges: set = set()
        for file_id in ordered_ids:
            try:
                document = self.projects.analysis(self.project_id, file_id, revision_id)
            except (KeyError, LookupError) as error:
                raise ValueError(
                    "Evidence references a file outside the frozen revision: "
                    + str(file_id)
                ) from error
            objects.extend(document.objects)
            relations.extend(document.relations)
            for block in document.graph.blocks:
                block_map.setdefault(block.id, block)
            if document.graph.roots:
                file_roots[file_id] = document.graph.roots[0]
            for node in document.graph.nodes:
                if node.id not in seen_nodes:
                    seen_nodes.add(node.id)
                    nodes.append(node)
            for edge in document.graph.edges:
                if edge.id not in seen_edges:
                    seen_edges.add(edge.id)
                    edges.append(edge)
            roots.extend(document.graph.roots)

        # Canonical project/folder ancestors wrapping the actual captured roots.
        project_block_id = _id("project", self.project_id)
        folder_blocks: dict = {}
        child_folders: dict = {}
        file_children: dict = {}

        def ensure_folder(path: str) -> str:
            fid = _id("folder", self.project_id, path)
            if fid in folder_blocks:
                return fid
            parent_path = path.rsplit("/", 1)[0] if "/" in path else ""
            parent = ensure_folder(parent_path) if parent_path else project_block_id
            folder_blocks[fid] = GraphBlock(
                id=fid,
                logical_key=f"{self.project_id}::folder::{path}",
                kind="folder",
                label=path,
                parent_id=parent,
                source=SourceRef(
                    path=path,
                    project_id=self.project_id,
                    project_revision_id=revision_id,
                ),
                members=[],
                runtime_coverage="supported",
            )
            child_folders.setdefault(parent, []).append(fid)
            return fid

        for file_id in ordered_ids:
            root_id = file_roots.get(file_id)
            if not root_id or root_id not in block_map:
                continue
            relative = unit_paths.get(file_id, "")
            parent = project_block_id
            for path in _folders_for(relative) if relative else ():
                parent = ensure_folder(path)
            block_map[root_id] = block_map[root_id].model_copy(
                update={"parent_id": parent}
            )
            file_children.setdefault(parent, []).append(root_id)

        def members_of(block_id: str) -> list:
            return list(child_folders.get(block_id, [])) + list(
                file_children.get(block_id, [])
            )

        project_members = members_of(project_block_id)
        project_block = GraphBlock(
            id=project_block_id,
            logical_key=f"{self.project_id}::project::{self.project_root.name}",
            kind="project",
            label=self.project_root.name,
            members=project_members,
            source=SourceRef(
                project_id=self.project_id, project_revision_id=revision_id
            ),
            runtime_coverage="supported",
        )
        blocks = [project_block]
        for fid, block in folder_blocks.items():
            blocks.append(
                block.model_copy(update={"members": members_of(fid)})
            )
        for block in block_map.values():
            blocks.append(block)
        for parent, children in (
            (project_block_id, project_members),
            *(
                (fid, members_of(fid)) for fid in folder_blocks
            ),
        ):
            for child in children:
                edges.append(
                    GraphEdge(
                        id=_id("e", parent, child, "contains"),
                        source=parent,
                        target=child,
                        kind="contains",
                        provenance="inferred",
                    )
                )
        graph = SemanticGraph(
            source_digest=plan.source_digest,
            roots=list(dict.fromkeys(roots)),
            blocks=blocks,
            nodes=nodes,
            edges=edges,
        )
        return AnalysisDocument(
            path=str(self.project_root),
            source_digest=plan.source_digest,
            objects=objects,
            relations=relations,
            graph=graph,
        )

    def _failure_reason(self, run, run_id=None) -> str:
        summary = run.get("summary") or {}
        message = None
        if run_id:
            try:
                events = self.research.events(run_id, 0, 1000)
            except Exception:
                events = []
            for event in reversed(events):
                if event.get("kind") == "analysis.error":
                    payload = event.get("payload") or {}
                    message = payload.get("message") or payload.get("error_type")
                    break
        status = run.get("status") or "failed"
        reason = message or summary.get("observer_error") or summary.get("execution_status")
        text = "Project run " + str(status)
        if reason and str(reason) != str(status):
            text += ": " + str(reason)
        exit_code = summary.get("exit_code")
        if exit_code is not None:
            text += f" (exit {exit_code})"
        return clean_text(text, 512)
