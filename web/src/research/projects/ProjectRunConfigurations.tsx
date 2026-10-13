/** Authored run-entry editor for one indexed project revision.
 *
 * Editing an entry authors a definition (id, interpreter reference, environment
 * reference, arguments). It never reads or writes source files, never launches a
 * process and never guesses an execution: saving is one optimistic PUT against
 * the configuration revision, and a 409 is surfaced instead of overwritten.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { RunConfiguration, RuntimeReferenceState } from "./generated";
import {
  commandError,
  createProjectCommands,
  type ProjectCommands,
  type EntriesPage,
} from "./projectCommands";
import "./project-host.css";

export interface EntryDraft {
  id: string;
  name: string;
  kind: RunConfiguration["kind"];
  target: string;
  cwd: string;
  argumentsText: string;
  interpreterRef: string;
  environmentRef: string;
  index: number | null;
}

export interface ProjectRunConfigurationsProps {
  projectId: string;
  revisionId: string;
  onSelect: (id: string) => void;
  onSaved?: () => void;
  onError: (message: string) => void;
  client?: ProjectCommands;
}

/** One argument per line; blank lines are ignored, never split on spaces. */
export function parseArgumentLines(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

/** ``KEY=value`` per line; the value may be empty but the key must be a name. */
export function parseEnvironmentLines(text: string): {
  values: Record<string, string>;
  invalid: string[];
} {
  const values: Record<string, string> = {};
  const invalid: string[] = [];
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    const at = line.indexOf("=");
    const name = at < 0 ? "" : line.slice(0, at).trim();
    if (at < 0 || !/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) {
      invalid.push(line);
      continue;
    }
    values[name] = line.slice(at + 1);
  }
  return { values, invalid };
}

/** Module targets are dotted and extension-free; script targets stay relative. */
export function normalizeTarget(
  kind: RunConfiguration["kind"],
  target: string,
): string {
  const value = target.trim();
  if (kind !== "module") return value;
  return value.replace(/\\/g, "/").replace(/\//g, ".").replace(/\.py$/, "");
}

let generated = 0;
export function newEntryId(): string {
  generated += 1;
  const cryptoRef = (globalThis as { crypto?: { randomUUID?: () => string } })
    .crypto;
  if (cryptoRef?.randomUUID) return cryptoRef.randomUUID().replace(/-/g, "");
  return `entry${Date.now().toString(36)}${generated.toString(36)}`;
}

export function newEntryDraft(): EntryDraft {
  return {
    id: newEntryId(),
    name: "",
    kind: "script",
    target: "",
    cwd: ".",
    argumentsText: "",
    interpreterRef: "",
    environmentRef: "",
    index: null,
  };
}

export function draftFromEntry(
  entry: RunConfiguration,
  index: number | null = 0,
): EntryDraft {
  return {
    id: entry.id,
    name: entry.name,
    kind: entry.kind,
    target: entry.target,
    cwd: entry.cwd || ".",
    argumentsText: entry.arguments.join("\n"),
    interpreterRef: entry.interpreter_ref || "",
    environmentRef: entry.environment[0] ?? "",
    index,
  };
}

export function entryFromDraft(draft: EntryDraft): RunConfiguration {
  const target = normalizeTarget(draft.kind, draft.target);
  const environment = draft.environmentRef.trim();
  return {
    id: draft.id.trim(),
    name: draft.name.trim() || target,
    kind: draft.kind,
    target,
    cwd: draft.cwd.trim() || ".",
    interpreter_ref: draft.interpreterRef.trim(),
    arguments: parseArgumentLines(draft.argumentsText),
    environment: environment ? [environment] : [],
    options: {},
  };
}

function ProjectRunConfigurationsView({
  projectId,
  revisionId,
  onSelect,
  onSaved,
  onError,
  client,
}: ProjectRunConfigurationsProps) {
  const commands = useMemo(() => client ?? createProjectCommands(), [client]);
  const [entries, setEntries] = useState<RunConfiguration[]>([]);
  const [candidates, setCandidates] = useState<EntriesPage["candidates"]>([]);
  const [configRevision, setConfigRevision] = useState(0);
  const [runtime, setRuntime] = useState<RuntimeReferenceState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [draft, setDraft] = useState<EntryDraft | null>(null);
  const [saving, setSaving] = useState(false);
  const [interpreterRef, setInterpreterRef] = useState("");
  const [interpreterPath, setInterpreterPath] = useState("");
  const [environmentRef, setEnvironmentRef] = useState("");
  const [environmentText, setEnvironmentText] = useState("");
  const [referenceError, setReferenceError] = useState("");
  const [referenceBusy, setReferenceBusy] = useState(false);

  const mounted = useRef(true);
  const retry = useRef<(() => void) | null>(null);
  const ticket = useRef(0);
  const pending = useRef<AbortController | null>(null);
  const controllers = useRef(new Set<AbortController>());
  const notify = useRef(onError);
  const saved = useRef(onSaved);
  const select = useRef(onSelect);
  notify.current = onError;
  saved.current = onSaved;
  select.current = onSelect;

  const issue = useCallback(
    <T,>(run: (signal: AbortSignal) => Promise<T>): Promise<T> => {
      const controller = new AbortController();
      controllers.current.add(controller);
      return run(controller.signal).finally(() =>
        controllers.current.delete(controller),
      );
    },
    [],
  );

  const reload = useCallback(async () => {
    const controller = new AbortController();
    pending.current?.abort();
    pending.current = controller;
    const mine = ++ticket.current;
    setLoading(true);
    try {
      const binding = commands.forProject(projectId);
      const [page, state] = await Promise.all([
        binding.entries(revisionId || null, controller.signal),
        binding.runtime(controller.signal),
      ]);
      if (
        !mounted.current ||
        controller.signal.aborted ||
        mine !== ticket.current
      )
        return;
      setEntries(page.entries);
      setCandidates(page.candidates);
      setConfigRevision(page.config_revision);
      setRuntime(state);
      setError("");
      setConflict("");
    } catch (cause) {
      if (
        !mounted.current ||
        controller.signal.aborted ||
        mine !== ticket.current
      )
        return;
      const { message } = commandError(cause);
      setError(message);
      notify.current(message);
    } finally {
      if (mounted.current && mine === ticket.current) setLoading(false);
    }
  }, [commands, projectId, revisionId]);

  useEffect(() => {
    mounted.current = true;
    // A new project or revision resets every authored draft and pending view.
    setEntries([]);
    setCandidates([]);
    setConfigRevision(0);
    setRuntime(null);
    setSelectedId("");
    setDraft(null);
    setError("");
    setConflict("");
    setReferenceError("");
    setLoading(true);
    void reload();
    const aborters = controllers.current;
    return () => {
      mounted.current = false;
      pending.current?.abort();
      aborters.forEach((item) => item.abort());
      aborters.clear();
    };
  }, [reload]);

  const patch = (changes: Partial<EntryDraft>) =>
    setDraft((current) => (current ? { ...current, ...changes } : current));

  const choose = (entry: RunConfiguration, index: number) => {
    setSelectedId(entry.id);
    setDraft(draftFromEntry(entry, index));
    select.current(entry.id);
  };

  const applySave = useCallback(
    async (next: RunConfiguration[], selected: string, again: () => void) => {
      setSaving(true);
      setConflict("");
      try {
        const config = await issue((signal) =>
          commands
            .forProject(projectId)
            .saveEntries(next, configRevision, signal),
        );
        if (!mounted.current) return;
        setEntries(config.run_configurations ?? next);
        setConfigRevision(config.revision);
        setDraft(null);
        setError("");
        if (selected) {
          setSelectedId(selected);
          select.current(selected);
        }
        saved.current?.();
      } catch (cause) {
        if (!mounted.current) return;
        const { message, status } = commandError(cause);
        if (status === 409) {
          // Never overwrite: reload the authoritative revision for the author.
          setConflict(
            message || "Configuration revision conflict; reload before saving",
          );
          await reload();
        } else {
          setError(message);
        }
        notify.current(message);
        retry.current = again;
      } finally {
        if (mounted.current) setSaving(false);
      }
    },
    [commands, configRevision, issue, projectId, reload],
  );

  const save = () => {
    if (!draft) return;
    const entry = entryFromDraft(draft);
    if (!entry.id) return setError("Entry id is required");
    if (!entry.target) return setError("Entry target is required");
    const next =
      draft.index === null
        ? [...entries, entry]
        : entries.map((item, index) => (index === draft.index ? entry : item));
    void applySave(next, entry.id, save);
  };

  const remove = (entry: RunConfiguration) => {
    const next = entries.filter((item) => item.id !== entry.id);
    if (next.length === entries.length) return;
    setDraft(null);
    void applySave(next, "", () => void reload());
  };

  const registerInterpreter = async () => {
    const reference = interpreterRef.trim();
    const path = interpreterPath.trim();
    if (!reference || !path || !runtime) return;
    setReferenceBusy(true);
    setReferenceError("");
    try {
      const state = await issue((signal) =>
        commands.registerInterpreter(reference, path, runtime.revision, signal),
      );
      if (!mounted.current) return;
      setRuntime(state);
      setInterpreterRef("");
      setInterpreterPath("");
    } catch (cause) {
      if (!mounted.current) return;
      setReferenceError(commandError(cause).message);
    } finally {
      if (mounted.current) setReferenceBusy(false);
    }
  };

  const registerEnvironment = async () => {
    const reference = environmentRef.trim();
    if (!reference || !runtime) return;
    const { values, invalid } = parseEnvironmentLines(environmentText);
    if (invalid.length) {
      setReferenceError(`Invalid variable name on: ${invalid.join(", ")}`);
      return;
    }
    if (Object.keys(values).length === 0) {
      setReferenceError("Enter at least one KEY=value line");
      return;
    }
    setReferenceBusy(true);
    setReferenceError("");
    try {
      const state = await issue((signal) =>
        commands.registerEnvironment(
          reference,
          values,
          runtime.revision,
          signal,
        ),
      );
      if (!mounted.current) return;
      setRuntime(state);
      // Values are host-private: the field is cleared and never echoed back.
      setEnvironmentRef("");
      setEnvironmentText("");
    } catch (cause) {
      if (!mounted.current) return;
      setReferenceError(commandError(cause).message);
    } finally {
      if (mounted.current) setReferenceBusy(false);
    }
  };

  const interpreterOptions = runtime?.interpreters ?? [];
  const environmentOptions = runtime?.environments ?? [];

  return (
    <div className="project-entries">
      <div className="project-entries-head">
        <span className="project-entries-label">Run entries</span>
        <span className="project-entries-revision">
          config r{configRevision}
        </span>
        <button type="button" onClick={() => void reload()} disabled={loading}>
          Reload
        </button>
        <button
          type="button"
          className="primary"
          disabled={saving}
          onClick={() => setDraft(newEntryDraft())}
        >
          Add
        </button>
      </div>

      {error ? (
        <p className="project-entries-error" role="alert">
          <span>{error}</span>
          {retry.current ? (
            <button
              type="button"
              onClick={() => {
                const again = retry.current;
                setError("");
                retry.current = null;
                again?.();
              }}
            >
              Retry
            </button>
          ) : null}
        </p>
      ) : null}
      {conflict ? (
        <p className="project-entries-conflict" role="alert">
          {conflict}
        </p>
      ) : null}

      <ul className="project-entries-list">
        {entries.map((entry, index) => (
          <li key={entry.id}>
            <button
              type="button"
              className={entry.id === selectedId ? "is-active" : ""}
              onClick={() => choose(entry, index)}
            >
              <strong>{entry.name || entry.target}</strong>
              <span>
                {entry.kind} · {entry.target}
              </span>
              <em>
                {entry.interpreter_ref || "machine interpreter"}
                {entry.environment.length
                  ? ` · env ${entry.environment[0]}`
                  : ""}
              </em>
            </button>
            <button
              type="button"
              className="project-entries-remove"
              disabled={saving}
              onClick={() => remove(entry)}
            >
              Delete
            </button>
          </li>
        ))}
        {entries.length === 0 && !loading ? (
          <li className="project-entries-empty">No authored entries yet.</li>
        ) : null}
      </ul>

      {candidates.length ? (
        <div className="project-entries-candidates">
          <span className="project-entries-label">Candidates</span>
          {candidates.map((candidate) => (
            <button
              type="button"
              key={candidate.id}
              onClick={() => setDraft(draftFromEntry(candidate, null))}
            >
              {candidate.target}
            </button>
          ))}
        </div>
      ) : null}

      {draft ? (
        <form
          className="project-entries-form"
          onSubmit={(event) => {
            event.preventDefault();
            save();
          }}
        >
          <div className="project-entries-grid">
            <label className="project-entries-field">
              <span>Name</span>
              <input
                value={draft.name}
                onChange={(e) => patch({ name: e.target.value })}
              />
            </label>
            <label className="project-entries-field">
              <span>Id</span>
              <input
                value={draft.id}
                onChange={(e) => patch({ id: e.target.value })}
              />
            </label>
            <label className="project-entries-field">
              <span>Kind</span>
              <select
                value={draft.kind}
                onChange={(e) =>
                  patch({ kind: e.target.value as EntryDraft["kind"] })
                }
              >
                <option value="script">script</option>
                <option value="module">module</option>
              </select>
            </label>
            <label className="project-entries-field">
              <span>Target</span>
              <input
                value={draft.target}
                onChange={(e) => patch({ target: e.target.value })}
              />
            </label>
            <label className="project-entries-field">
              <span>Working dir</span>
              <input
                value={draft.cwd}
                onChange={(e) => patch({ cwd: e.target.value })}
              />
            </label>
            <label className="project-entries-field">
              <span>Interpreter</span>
              <select
                value={draft.interpreterRef}
                onChange={(e) => patch({ interpreterRef: e.target.value })}
              >
                <option value="">Machine default</option>
                {interpreterOptions.map((item) => (
                  <option value={item.id} key={item.id}>
                    {item.id}
                  </option>
                ))}
              </select>
            </label>
            <label className="project-entries-field">
              <span>Environment</span>
              <select
                value={draft.environmentRef}
                onChange={(e) => patch({ environmentRef: e.target.value })}
              >
                <option value="">None</option>
                {environmentOptions.map((item) => (
                  <option value={item.id} key={item.id}>
                    {item.id} ({item.keys.length} keys)
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="project-entries-field project-entries-wide">
            <span>Arguments (one per line)</span>
            <textarea
              rows={4}
              value={draft.argumentsText}
              onChange={(e) => patch({ argumentsText: e.target.value })}
            />
          </label>
          <div className="project-entries-actions">
            <button type="submit" className="primary" disabled={saving}>
              Save entry
            </button>
            <button
              type="button"
              onClick={() => setDraft(null)}
              disabled={saving}
            >
              Discard
            </button>
          </div>
          <p className="project-entries-help">
            Saving authors this definition only; machine interpreter references
            stay on the host.
          </p>
        </form>
      ) : null}

      <details className="project-entries-advanced">
        <summary>Advanced: machine references</summary>
        <p className="project-entries-help">
          Interpreter paths and environment values live on this machine only;
          the project stores reference ids.
        </p>
        {referenceError ? (
          <p className="project-entries-error" role="alert">
            {referenceError}
          </p>
        ) : null}
        <div className="project-entries-grid">
          <label className="project-entries-field">
            <span>Interpreter reference</span>
            <input
              value={interpreterRef}
              onChange={(e) => setInterpreterRef(e.target.value)}
              placeholder="py311"
            />
          </label>
          <label className="project-entries-field">
            <span>Interpreter path</span>
            <input
              value={interpreterPath}
              onChange={(e) => setInterpreterPath(e.target.value)}
              placeholder="C:\\Python311\\python.exe"
            />
          </label>
        </div>
        <button
          type="button"
          disabled={
            referenceBusy || !interpreterRef.trim() || !interpreterPath.trim()
          }
          onClick={() => void registerInterpreter()}
        >
          Register interpreter
        </button>
        <div className="project-entries-grid">
          <label className="project-entries-field">
            <span>Environment reference</span>
            <input
              value={environmentRef}
              onChange={(e) => setEnvironmentRef(e.target.value)}
              placeholder="lab-env"
            />
          </label>
        </div>
        <label className="project-entries-field project-entries-wide">
          <span>Environment values (KEY=value per line)</span>
          <textarea
            rows={3}
            value={environmentText}
            onChange={(e) => setEnvironmentText(e.target.value)}
            placeholder="TOKEN=..."
          />
        </label>
        <button
          type="button"
          disabled={referenceBusy || !environmentRef.trim()}
          onClick={() => void registerEnvironment()}
        >
          Register environment
        </button>
        <ul className="project-entries-profiles">
          {runtime?.environments.map((item) => (
            <li key={item.id}>
              <code>{item.id}</code>
              <span>{item.keys.length} keys</span>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

export default ProjectRunConfigurations;

export function ProjectRunConfigurations(props: ProjectRunConfigurationsProps) {
  return (
    <ProjectRunConfigurationsView
      key={`${props.projectId}@${props.revisionId}`}
      {...props}
    />
  );
}
