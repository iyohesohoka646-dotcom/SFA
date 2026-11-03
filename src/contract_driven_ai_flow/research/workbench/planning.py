"""Freeze a user's configured computation and independent probe operations."""

import hashlib
import json

from .models import AnalysisDocument, ExecutionPlan, ProbeDefinition, WorkbenchConfig


def fingerprint(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def compile_plan(
    analysis: AnalysisDocument,
    config: WorkbenchConfig,
    definitions: list[ProbeDefinition],
    *,
    scope="compute",
    run_id=None,
    snapshot_ids=(),
    environment=None,
    snapshots=(),
    target_scope=None,
) -> ExecutionPlan:
    if analysis.diagnostics:
        raise ValueError("Resolve source diagnostics before execution")
    known = {definition.id: definition for definition in definitions}
    ids = set()
    for probe in config.probes:
        if probe.id in ids:
            raise ValueError("Probe IDs must be unique")
        ids.add(probe.id)
        if probe.enabled and probe.definition_id not in known:
            raise ValueError(f"Probe {probe.definition_id} is not registered")
    if scope != "compute" and not run_id:
        raise ValueError("Saved evidence is required for probes or replot")
    from .semantic_models import ScopeSelector
    from .scopes import source_targets, resolve_scope
    from .bindings import snapshot_target, resolve_calls

    target_scope = target_scope or ScopeSelector()
    available = (
        (
            [snapshot_target(snapshot, analysis) for snapshot in snapshots]
            + [target for target in source_targets(analysis) if target.kind != "data"]
        )
        if snapshots
        else source_targets(analysis)
    )
    resolved = resolve_scope(analysis.graph, target_scope, available)
    versions = {
        tool["id"]: tool.get("version") or "unavailable"
        for tool in (environment or {}).get("tools", [])
    }
    invocations = resolve_calls(
        analysis, config, definitions, resolved, snapshots, versions, scope=scope
    )
    return ExecutionPlan(
        analysis_id=analysis.id,
        source_digest=analysis.source_digest,
        config_digest=fingerprint(config),
        environment_digest=fingerprint(
            environment or {"interpreter": config.interpreter}
        ),
        config=config.model_copy(deep=True),
        definitions=[d.model_copy(deep=True) for d in definitions],
        scope=scope,
        run_id=run_id,
        snapshot_ids=list(snapshot_ids),
        target_scope=target_scope.model_copy(deep=True),
        resolved_targets=resolved,
        invocations=invocations,
    )
