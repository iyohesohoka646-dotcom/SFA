import type { ProbeInstance, ProbeOutput } from "./generated";
import type { SnapshotRef } from "../generated";
const canonical = (value: unknown): unknown => Array.isArray(value) ? value.map(canonical) : value && typeof value === "object"
  ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => [key, canonical(item)])) : value;
export const sameParameters = (a: unknown, b: unknown) => JSON.stringify(canonical(a ?? {})) === JSON.stringify(canonical(b ?? {}));

/** Results belong to exact evidence, not to a variable's display name. */
export function latestProbeOutputs(outputs: ProbeOutput[], snapshot: SnapshotRef, instances: ProbeInstance[]): Map<string, ProbeOutput> {
  const enabled = new Set(instances.filter(p => p.enabled).map(p => p.id)), latest = new Map<string, ProbeOutput>();
  for (const result of outputs) {
    if (!enabled.has(result.instance_id) || result.run_id && result.run_id !== snapshot.run_id) continue;
    if (result.snapshot_id !== snapshot.id && !result.targets.some(t => t.snapshot_id === snapshot.id)) continue;
    const previous = latest.get(result.instance_id);
    if (!previous || (Date.parse(result.created_at) || 0) > (Date.parse(previous.created_at) || 0)) latest.set(result.instance_id, result);
  }
  return latest;
}
