/** Pure lexical-scope and selection identity for the project browser/canvas.
 *
 * The backend publishes object targets as `project::file::scope::name`, where
 * `scope` is the full lexical scope (`<module>` for globals) and
 * `source.qualname` is only the qualified *variable* name. Grouping therefore
 * never reads `qualname` while a canonical key is available, and never guesses
 * a scope from `scope_id` (that field may hold a runtime id elsewhere).
 */
import type { ObjectItem, SourceRef, TargetRef } from "./generated";

export const MODULE_SCOPE = "<module>";

const text = (value: string | null | undefined): string | null =>
  typeof value === "string" && value.length > 0 ? value : null;

/** Full lexical scope encoded in a canonical `project::file::scope::name` key.
 *
 * The exact `project::file::` prefix is removed first, then the trailing
 * `::name` segment. Inner `::` separators are kept, so `A.fn`/`B.fn` stay apart.
 */
function keyScope(
  logicalKey: string | null | undefined,
  projectId: string,
  fileId: string,
  name: string,
): string | null {
  const key = text(logicalKey);
  if (!key || !projectId || !fileId) return null;
  const prefix = `${projectId}::${fileId}::`;
  if (!key.startsWith(prefix)) return null;
  let rest = key.slice(prefix.length);
  if (rest === name) return MODULE_SCOPE;
  const cut = rest.lastIndexOf("::");
  if (cut < 0) return null;
  if (name && rest.slice(cut + 2) !== name) return null;
  rest = rest.slice(0, cut);
  return rest || MODULE_SCOPE;
}

/** Parent scope of a legacy qualified variable name, only when it ends with the
 * known item name; otherwise the legacy record has no usable lexical scope. */
function qualnameScope(qualname: string | null | undefined, name: string): string | null {
  const value = text(qualname);
  if (!value) return null;
  if (!name || value === name) return MODULE_SCOPE;
  if (!value.endsWith(name)) return MODULE_SCOPE;
  const parent = value.slice(0, value.length - name.length).replace(/(::|\.)+$/, "");
  return parent || MODULE_SCOPE;
}

function resolveScope(item: ObjectItem): { key: string; scope: string } {
  const target = (item.target ?? {}) as TargetRef;
  const source = item.source as SourceRef | undefined;
  const projectId = text(target.project_id) ?? text(source?.project_id) ?? "";
  const fileId = text(target.file_id) ?? text(source?.file_id) ?? "";
  const name = text(item.name) ?? "";
  const scope =
    keyScope(target.logical_key, projectId, fileId, name) ??
    qualnameScope(source?.qualname, name) ??
    MODULE_SCOPE;
  return { key: `${projectId}::${fileId}::${scope}`, scope };
}

/** Canonical grouping identity `project::file::lexicalScope` for one object. */
export function objectScope(item: ObjectItem): string {
  return resolveScope(item).key;
}

/** Lexical scope alone, for labels and titles (never for identity). */
export function objectLexicalScope(item: ObjectItem): string {
  return resolveScope(item).scope;
}

/** Display-only shortening of a scope; never used as the grouping identity. */
export function scopeLabel(scope: string): string {
  const parts = text(scope)?.split(/::|\./).filter(Boolean) ?? [];
  return parts.at(-1) ?? MODULE_SCOPE;
}

/** Pure selection identity shared by browser and canvas.
 *
 * Data targets ignore the assignment `object_id` unless the target carries exact
 * evidence (snapshot/run ids), so the same project/file/logical_key stays one
 * key across assignments while distinct files or snapshots stay distinct.
 * Other kinds keep their source object id.
 */
export function targetSelectionKey(target: TargetRef): string {
  const identity = [
    target.kind ?? "",
    target.project_id ?? "",
    target.file_id ?? "",
    target.logical_key ?? "",
  ];
  if (target.exact_evidence) {
    identity.push(target.snapshot_id ?? "", target.run_id ?? "", target.object_id ?? "");
  } else if (target.kind !== "data") {
    identity.push(target.object_id ?? "");
  }
  return identity.join("::");
}
