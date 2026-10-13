import type {
  AnalysisDocument,
  ProbeDefinition,
  ProbeInstance,
  ScopeSelector,
  TargetRef,
} from "./generated";
import type { SnapshotRef, SourceRef } from "../generated";
import type { PublicProviderProfile } from "../../settings/client";
import { scopeSelector, selectionKey } from "./selection";

export interface ParameterField {
  type?: string | string[];
  title?: string;
  description?: string;
  enum?: (string | number | boolean | null)[];
  default?: unknown;
  minimum?: number;
  maximum?: number;
  items?: ParameterField;
  properties?: Record<string, ParameterField>;
}

export function schemaDefaults(schema: Record<string, unknown>): Record<string, unknown> {
  const properties = (schema.properties ?? {}) as Record<string, ParameterField>;
  return Object.fromEntries(
    Object.entries(properties).flatMap(([key, field]) => {
      if ("default" in field) return [[key, structuredClone(field.default)]];
      if (field.type === "object") {
        const nested = schemaDefaults(field as Record<string, unknown>);
        if (Object.keys(nested).length) return [[key, nested]];
      }
      return [];
    }),
  );
}

export function initialProbeParameters(
  definition: ProbeDefinition,
  saved: Record<string, unknown> = {},
  snapshot?: SnapshotRef,
) {
  const result = { ...schemaDefaults(definition.parameter_schema), ...structuredClone(saved) };
  if (!("expected" in saved) && snapshot) {
    if (definition.id === "check.shape" && snapshot.descriptor.shape)
      result.expected = [...snapshot.descriptor.shape];
    if (definition.id === "check.dtype" && snapshot.descriptor.dtype)
      result.expected = snapshot.descriptor.dtype;
  }
  return result;
}

export function availableModels(profile?: PublicProviderProfile) {
  return [...new Set([profile?.default_model, ...(profile?.models ?? [])].filter((id): id is string => Boolean(id)))];
}

export function currentProbeBlock(analysis?: AnalysisDocument, explicit?: string | null) {
  if (!analysis) return undefined;
  const blocks = analysis.graph.blocks;
  return blocks.find((block) => block.id === explicit)
    ?? blocks.find((block) => analysis.graph.roots.includes(block.id))
    ?? blocks.find((block) => block.kind === "file");
}

function inside(analysis: AnalysisDocument | undefined, block: string | null, ancestor: string | null) {
  if (!block || !ancestor) return false;
  const parents = new Map(analysis?.graph.blocks.map((item) => [item.id, item.parent_id]) ?? []);
  const seen = new Set<string>();
  while (block && !seen.has(block)) {
    if (block === ancestor) return true;
    seen.add(block);
    block = parents.get(block) ?? null;
  }
  return false;
}

export function sameLogicalTarget(focus: TargetRef, target: TargetRef, analysis?: AnalysisDocument) {
  if (focus.logical_key !== target.logical_key || focus.snapshot_id && focus.snapshot_id !== target.snapshot_id) return false;
  if (focus.kind === "function" && target.kind === "function" && focus.object_id) {
    if (analysis?.graph.blocks.some((block) => block.source_object_id === focus.object_id))
      return focus.object_id === target.object_id;
    return analysis?.graph.blocks.filter((block) => block.logical_key === focus.logical_key).length === 1;
  }
  if (focus.object_id && target.object_id) {
    const left = lexicalOwner(focus, analysis, true), right = lexicalOwner(target, analysis, true);
    if (left && right) return left === right;
    if (analysis && focus.kind === "data" && !left) {
      const owners = targetOwners(target, analysis);
      return owners.size === 1 && Boolean(right && owners.has(right));
    }
  }
  return true;
}

const containsChildren = (target: TargetRef) =>
  ["function", "control", "file", "folder", "project", "stream"].includes(target.kind);

function lexicalOwner(item: { block_id: string | null; kind: string }, analysis?: AnalysisDocument, functionParent = false) {
  const blocks = new Map(analysis?.graph.blocks.map((block) => [block.id, block]) ?? []);
  let block = functionParent && item.kind === "function" && item.block_id ? blocks.get(item.block_id)?.parent_id : item.block_id;
  const seen = new Set<string>();
  while (block && !seen.has(block)) {
    seen.add(block);
    const current = blocks.get(block);
    if (!current) return undefined;
    if (["function", "class", "file"].includes(current.kind)) return block;
    block = current.parent_id;
  }
  return undefined;
}

function targetOwners(target: TargetRef, analysis?: AnalysisDocument) {
  if (containsChildren(target)) return new Set(analysis?.graph.blocks.filter((block) => block.logical_key === target.logical_key).map((block) => block.id));
  return new Set(analysis?.graph.nodes.filter((node) => node.logical_key === target.logical_key
    && ["data", "parameter"].includes(node.kind) === (target.kind === "data"))
    .map((node) => lexicalOwner(node, analysis)).filter((owner): owner is string => Boolean(owner)));
}

const scopeMarker = "::scope:";
export function targetOverrideKey(target: TargetRef, analysis?: AnalysisDocument) {
  const owners = targetOwners(target, analysis);
  if (owners.size <= 1) return target.logical_key;
  const owner = containsChildren(target) ? target.block_id : lexicalOwner(target, analysis);
  return owner && owners.has(owner) ? target.logical_key + scopeMarker + owner : undefined;
}

export function targetOverrideError(probe: ProbeInstance, target: TargetRef, analysis?: AnalysisDocument) {
  const owners = targetOwners(target, analysis), prefix = target.logical_key + scopeMarker;
  const valid = new Set([...owners].map((owner) => prefix + owner));
  if (Object.keys(probe.overrides).some((key) => key.startsWith(prefix) && !valid.has(key))
    || owners.size > 1 && target.logical_key in probe.overrides || !targetOverrideKey(target, analysis))
    return "局部覆盖的作用域已失效或有歧义，请重新绑定。";
  return undefined;
}

export function targetOverride(probe: ProbeInstance, target: TargetRef, analysis?: AnalysisDocument) {
  if (targetOverrideError(probe, target, analysis)) return undefined;
  const key = targetOverrideKey(target, analysis)!;
  if (key === target.logical_key) {
    const scoped = Object.keys(probe.overrides).find((candidate) => candidate.startsWith(key + scopeMarker));
    if (scoped) return probe.overrides[scoped];
  }
  return probe.overrides[key];
}

export function snapshotProbeTarget(snapshot: SnapshotRef, analysis: AnalysisDocument): TargetRef {
  const source = snapshot.source;
  const scope = ["main", "<module>"].includes(snapshot.scope_id) ? "<module>" : snapshot.scope_id.split(":").slice(0, -1).join(":");
  const logical_key = snapshot.logical_key || `${source?.path || analysis.path}::${scope}::${snapshot.name}`;
  const matches = analysis.objects.filter((object) => object.logical_key === logical_key);
  const exact = matches.filter((object) => source && object.line <= source.line && source.line <= object.end_line
    && (!source.column || object.column === source.column));
  const object = exact.at(-1) ?? matches.at(-1);
  return { kind: "data", logical_key, object_id: object?.id ?? null, block_id: object?.block_id ?? analysis.graph.roots[0] ?? null,
    analysis_id: analysis.id, run_id: snapshot.run_id, snapshot_id: snapshot.id,
    project_id: source?.project_id || null, file_id: source?.file_id || null, project_revision_id: source?.project_revision_id || null,
    exact_evidence: false };
}

export function probeScopeSelector(
  analysis: AnalysisDocument | undefined,
  blockId: string | null,
  targets: TargetRef[],
  mode: ScopeSelector["mode"],
): ScopeSelector {
  const selector = scopeSelector(blockId, targets, mode);
  const block = mode === "block" ? analysis?.graph.blocks.find((item) => item.id === blockId) : undefined;
  if (block && analysis) selector.targets = [{
    kind: block.kind === "file" ? "file" : ["function", "class"].includes(block.kind) ? "function" : block.kind === "project" ? "project" : block.kind === "folder" ? "folder" : "control",
    logical_key: block.logical_key, block_id: block.id, object_id: block.source_object_id,
    analysis_id: analysis.id, run_id: null, snapshot_id: null,
    project_id: block.source?.project_id || null, file_id: block.source?.file_id || null, project_revision_id: block.source?.project_revision_id || null,
    exact_evidence: false,
  }];
  return selector;
}

export function resolveProbeBlock(analysis: AnalysisDocument | undefined, selector: ScopeSelector) {
  const blocks = analysis?.graph.blocks ?? [];
  const current = blocks.find((block) => block.id === selector.block_id);
  if (current) return current;
  const keys = new Set(selector.targets.filter(containsChildren).map((target) => target.logical_key));
  const choices = blocks.filter((block) => keys.has(block.logical_key));
  return choices.length === 1 ? choices[0] : undefined;
}

export function selectionMatches(focus: TargetRef, target: TargetRef, analysis?: AnalysisDocument) {
  if (sameLogicalTarget(focus, target, analysis)) return true;
  if (!containsChildren(focus)) return false;
  const blocks = analysis?.graph.blocks ?? [];
  let ancestor = focus.block_id;
  if (!blocks.some((block) => block.id === ancestor)) {
    const choices = blocks.filter((block) => block.logical_key === focus.logical_key);
    if (choices.length !== 1) return false;
    ancestor = choices[0].id;
  }
  return inside(analysis, target.block_id, ancestor);
}

export function removeLogicalProbeTarget(selector: ScopeSelector, target: TargetRef, analysis?: AnalysisDocument): ScopeSelector {
  return { ...selector, targets: selector.targets.filter((focus) => !sameLogicalTarget(focus, target, analysis)) };
}

function sourceTargets(analysis?: AnalysisDocument): TargetRef[] {
  if (!analysis) return [];
  const ref = (kind: TargetRef["kind"], key: string, object: string | null, block: string | null, source?: SourceRef | null): TargetRef => ({
    kind, logical_key: key, object_id: object, block_id: block,
    analysis_id: analysis.id, run_id: null, snapshot_id: null,
    project_id: source?.project_id || null, file_id: source?.file_id || null, project_revision_id: source?.project_revision_id || null,
    exact_evidence: false,
  });
  const blockSources = new Map(analysis.graph.blocks.map((block) => [block.id, block.source] as const));
  return [
    ...analysis.objects.map((object) => ref(
      ["function", "class"].includes(object.kind) ? "function" : "data",
      object.logical_key, object.id, object.block_id, blockSources.get(object.block_id),
    )),
    ...analysis.graph.blocks.filter((block) => ["condition", "loop", "try", "with", "file"].includes(block.kind))
      .map((block) => ref(block.kind === "file" ? "file" : "control", block.logical_key, null, block.id, block.source)),
    ...analysis.graph.nodes.filter((node) => !["data", "parameter"].includes(node.kind) && node.source)
      .map((node) => ref("operation", node.logical_key, node.source_object_id, node.block_id, node.source)),
  ];
}

export function scopeProbeTargets(analysis: AnalysisDocument | undefined, selector: ScopeSelector) {
  const scopeBlock = selector.mode === "block" ? resolveProbeBlock(analysis, selector) : undefined;
  const supplied = selector.targets.filter((target) => {
    if (!analysis || !containsChildren(target)) return true;
    const block = analysis.graph.blocks.find((item) => item.id === target.block_id);
    return Boolean(block && (target.kind !== "function" || !target.object_id || block.source_object_id === target.object_id));
  });
  const needsRecovery = analysis && selector.targets.some((target) => target.kind === "data" && !target.snapshot_id
    && !analysis.graph.blocks.some((block) => block.id === target.block_id));
  const candidates = selector.mode === "selection" && !selector.targets.some(containsChildren) && !needsRecovery
    ? supplied : [...sourceTargets(analysis), ...supplied];
  const selected = candidates.filter((target) => {
    if (selector.excluded_keys.includes(target.logical_key)) return false;
    if (selector.mode === "project") return true;
    if (selector.mode === "block") return inside(analysis, target.block_id, scopeBlock?.id ?? null);
    return selector.targets.some((focus) => selectionMatches(focus, target, analysis));
  });
  return [...new Map(selected.map((target) => [selectionKey(target), target])).values()];
}

export function compatibleProbes(
  definitions: ProbeDefinition[],
  purpose: string,
  query: string,
  targets: TargetRef[],
) {
  const search = query.trim().toLowerCase();
  return definitions.filter((definition) =>
    (purpose === "all" || definition.capability === purpose)
    && (definition.label + " " + definition.id).toLowerCase().includes(search)
    && (!targets.length || targets.some((target) => definition.supported_targets.includes(target.kind))),
  );
}

export function probeAppliesToTarget(probe: ProbeInstance, target: TargetRef, analysis?: AnalysisDocument) {
  const selector = probe.selector;
  if (!selector) {
    if (["*", target.logical_key, target.object_id, target.block_id, target.snapshot_id].includes(probe.binding)) return true;
    const name = target.logical_key.split("::").at(-1) ?? "";
    const escaped = probe.binding.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".");
    return new RegExp("^" + escaped + "$", "u").test(name);
  }
  if (selector.excluded_keys.includes(target.logical_key)) return false;
  if (selector.mode === "project") return true;
  if (selector.mode === "block") return inside(analysis, target.block_id, resolveProbeBlock(analysis, selector)?.id ?? null);
  return selector.targets.some((focus) => selectionMatches(focus, target, analysis));
}

export function targetProbeEntries(
  probes: ProbeInstance[],
  definitions: ProbeDefinition[],
  target: TargetRef,
  analysis?: AnalysisDocument,
) {
  const candidates = containsChildren(target) ? scopeProbeTargets(analysis, {
    mode: "selection", block_id: null, targets: [target], excluded_keys: [],
  }) : [target];
  return probes.flatMap((probe) => {
    const definition = definitions.find((item) => item.id === probe.definition_id);
    const targets = candidates.filter((candidate) =>
      (!definition || definition.supported_targets.includes(candidate.kind))
      && probeAppliesToTarget(probe, candidate, analysis),
    );
    if (!targets.length) return [];
    const overrideError = targets.map((candidate) => targetOverrideError(probe, candidate, analysis)).find(Boolean);
    const enabledCount = targets.filter((candidate) => probe.enabled && !overrideError && targetOverride(probe, candidate, analysis)?.enabled !== false).length;
    const parameters = { ...probe.parameters, ...targetOverride(probe, targets[0], analysis)?.parameters };
    return [{
    probe,
    targets,
    inherited: probe.origin === "project_default"
      || probe.selector?.mode === "project"
      || probe.selector?.mode === "block"
      || (!probe.selector && probe.binding === "*")
      || probe.selector?.mode === "selection" && !probe.selector.targets.some((focus) => sameLogicalTarget(focus, target, analysis)),
    enabled: enabledCount > 0,
    enabledCount,
    overrideError,
    mixedParameters: targets.some((candidate) => JSON.stringify({ ...probe.parameters, ...targetOverride(probe, candidate, analysis)?.parameters }) !== JSON.stringify(parameters)),
    parameters,
    }];
  });
}

export function probeTargetLabel(target: TargetRef, analysis?: AnalysisDocument) {
  const block = containsChildren(target)
    ? analysis?.graph.blocks.find((item) => item.id === target.block_id) : undefined;
  return block?.label || analysis?.objects.find((object) => object.id === target.object_id)?.name
    || target.logical_key.split("::").at(-1) || target.logical_key;
}
