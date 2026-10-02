"""Logical, persistent bindings independent of snapshot IDs and view tabs."""
from __future__ import annotations

from fnmatch import fnmatchcase
from .models import ResolvedProbeCall, TargetOverride
from .semantic_models import TargetRef
from .scopes import resolve_scope


def snapshot_target(snapshot, analysis):
    source = snapshot.source
    scope = '<module>' if snapshot.scope_id in ('main', '<module>') else snapshot.scope_id.rsplit(':', 1)[0]
    path = source.path if source and source.path else analysis.path
    logical_key = snapshot.logical_key or f'{path}::{scope}::{snapshot.name}'
    matches = [obj for obj in analysis.objects if (obj.logical_key or f'{obj.path}::{obj.scope}::{obj.name}') == logical_key]
    exact = [obj for obj in matches if source and obj.line <= source.line <= obj.end_line and (not source.column or obj.column == source.column)]
    obj = exact[-1] if exact else matches[-1] if matches else None
    return TargetRef(kind='data', logical_key=logical_key, object_id=obj.id if obj else None,
        block_id=obj.block_id if obj else (analysis.graph.roots[0] if analysis.graph.roots else None),
        analysis_id=analysis.id, run_id=snapshot.run_id, snapshot_id=snapshot.id)


def matches_instance(instance, target, analysis, *, snapshot=None):
    if not instance.enabled:
        return False
    override = instance.overrides.get(target.logical_key)
    if override and override.enabled is False:
        return False
    if instance.selector is not None:
        return bool(resolve_scope(analysis.graph, instance.selector, [target])) if instance.selector.mode != 'selection' else any(
            focus.logical_key == target.logical_key and (not focus.snapshot_id or focus.snapshot_id == target.snapshot_id)
            or focus.block_id and focus.kind != 'data' and target in resolve_scope(analysis.graph, instance.selector.model_copy(update={'mode': 'block', 'block_id': focus.block_id}), [target])
            for focus in instance.selector.targets) and target.logical_key not in instance.selector.excluded_keys
    name = snapshot.name if snapshot else target.logical_key.rsplit('::', 1)[-1]
    return instance.binding in ('*', target.logical_key, target.object_id, target.block_id, target.snapshot_id) or fnmatchcase(name, instance.binding) or snapshot is not None and fnmatchcase(snapshot.binding_id, instance.binding)


def effective_instance(instance, target):
    result = instance.model_copy(deep=True)
    override = instance.overrides.get(target.logical_key)
    if override is not None:
        if override.enabled is not None:
            result.enabled = result.enabled and override.enabled
        result.parameters.update(override.parameters)
    return result


def effective_presenters(config, definitions, snapshot, analysis):
    known = {definition.id: definition for definition in definitions}
    target = snapshot_target(snapshot, analysis)
    return [effective_instance(instance, target) for instance in config.probes if instance.definition_id in known
        and known[instance.definition_id].capability == 'view' and target.kind in known[instance.definition_id].supported_targets
        and matches_instance(instance, target, analysis, snapshot=snapshot)]


def set_local_override(config, instance_id, logical_key, *, enabled=None, parameters=None, restore=False):
    result = config.model_copy(deep=True)
    instance = next((probe for probe in result.probes if probe.id == instance_id), None)
    if instance is None:
        raise ValueError('Probe instance is not configured')
    if restore:
        instance.overrides.pop(logical_key, None)
    else:
        existing = instance.overrides.get(logical_key, TargetOverride())
        instance.overrides[logical_key] = TargetOverride(enabled=enabled if enabled is not None else existing.enabled,
            parameters={**existing.parameters, **(parameters or {})})
    return result


def resolve_calls(analysis, config, definitions, targets, snapshots=(), resource_versions=None, *, scope='probes'):
    from .planning import fingerprint
    from jsonschema import Draft202012Validator
    known = {definition.id: definition for definition in definitions}
    saved = {snapshot.id: snapshot for snapshot in snapshots}
    calls = []
    for instance in config.probes:
        if not instance.enabled:
            continue
        definition = known[instance.definition_id]
        if scope == 'replot' and definition.capability != 'view':
            continue
        eligible = [target for target in targets if target.kind in definition.supported_targets and matches_instance(instance, target, analysis, snapshot=saved.get(target.snapshot_id))]
        if definition.input_mode == 'joint':
            inputs = {role: ref.model_copy(deep=True) for role, ref in instance.inputs.items()}
            if not inputs:
                roles = [role.name for role in definition.input_roles]
                if len(eligible) != len(roles):
                    raise ValueError(f'{definition.label} requires roles: {", ".join(roles)}')
                inputs = dict(zip(roles, eligible))
            resolved_inputs = {}
            for role, ref in inputs.items():
                matches = [target for target in targets if (target.snapshot_id == ref.snapshot_id if ref.snapshot_id else target.logical_key == ref.logical_key)]
                if not matches:
                    raise ValueError('Joint input is not in the frozen scope')
                if len(matches) > 1:
                    if scope == 'compute' and all(not target.snapshot_id for target in matches):
                        # Source assignments are candidates for one future logical
                        # value; runtime evidence versions remain distinct.
                        matches = [next((t for t in matches if ref.object_id == t.object_id), matches[-1])]
                    else:
                        raise ValueError('Joint input has multiple evidence versions; select one explicitly')
                resolved_inputs[role] = matches[0].model_copy(deep=True)
            inputs = resolved_inputs
            if set(inputs) - {role.name for role in definition.input_roles}:
                raise ValueError('Unknown joint input role')
            if any(role.required and role.name not in inputs for role in definition.input_roles):
                raise ValueError('Joint input roles are incomplete')
            groups = [(list(inputs.values()), inputs)]
        else:
            groups = [([target], {}) for target in eligible]
        for group, inputs in groups:
            resolved = effective_instance(instance, group[0]) if len(group) == 1 else instance.model_copy(deep=True)
            errors = sorted(Draft202012Validator(definition.parameter_schema).iter_errors(resolved.parameters), key=lambda error: str(error.path))
            if errors:
                error = errors[0]
                raise ValueError(f'Probe {instance.id} parameters {".".join(str(part) for part in error.path) or "root"}: {error.message}')
            calls.append(ResolvedProbeCall(definition=definition.model_copy(deep=True), instance=resolved,
                targets=[target.model_copy(deep=True) for target in group], inputs=inputs,
                resource_versions={**(resource_versions or {}), **({definition.resource_id: definition.resource_version or definition.version} if definition.resource_id else {})},
                input_digest=fingerprint([target.model_dump(mode='json') for target in group])))
    return calls
