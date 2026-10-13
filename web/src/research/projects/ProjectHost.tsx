/** Standalone project chooser + host shell for the P3 project gateway.
 *
 * The host owns exactly one thing: the id of the project the user explicitly
 * opened. There is no mutable ambient "active project" module state; the loaded
 * record, revision and in-flight index task all live in component state, and the
 * only persisted value is the project id.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { ResearchProject } from "./generated";
import type { TaskRecord } from "../workspace/generated";
import {
  commandError,
  createProjectCommands,
  type ProjectCommands,
} from "./projectCommands";
import "./project-host.css";

/** Task poll cadence while an index job is queued or running. */
export const INDEX_POLL_MS = 350;
/** The single persisted key; only the project id is ever stored. */
export const ACTIVE_PROJECT_KEY = "cdaf.project.id";

export interface ProjectSession {
  project: ResearchProject;
  revisionId: string;
  onRevision: (id: string) => void;
  onProject: (project: ResearchProject) => void;
}

export interface ProjectHostProps {
  children: (session: ProjectSession) => ReactNode;
  onLegacy?: () => void;
  client?: ProjectCommands;
}

/** True while an index task is owned but not finished. */
export function isIndexing(task: TaskRecord | null | undefined): boolean {
  return task?.status === "queued" || task?.status === "running";
}

/** Human label for one index task; progress is reported, never fabricated. */
export function indexStatus(task: TaskRecord | null | undefined): {
  label: string;
  progress: number;
} {
  if (!task) return { label: "", progress: 0 };
  const progress = Number.isFinite(task.progress) ? task.progress : 0;
  return {
    label: task.message || task.status,
    progress: Math.min(1, Math.max(0, progress)),
  };
}

function readStoredProject(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(ACTIVE_PROJECT_KEY) ?? "";
  } catch {
    return "";
  }
}

function storeProject(id: string): void {
  if (typeof window === "undefined") return;
  try {
    if (id) window.localStorage.setItem(ACTIVE_PROJECT_KEY, id);
    else window.localStorage.removeItem(ACTIVE_PROJECT_KEY);
  } catch {
    /* storage unavailable: identity simply does not survive a reload */
  }
}

export function ProjectHost({ children, onLegacy, client }: ProjectHostProps) {
  const commands = useMemo(() => client ?? createProjectCommands(), [client]);
  const [project, setProject] = useState<ResearchProject | null>(null);
  const [revisionId, setRevisionId] = useState("");
  const [recent, setRecent] = useState<ResearchProject[]>([]);
  const [recentError, setRecentError] = useState("");
  const [chooser, setChooser] = useState(false);
  const [folder, setFolder] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [task, setTask] = useState<TaskRecord | null>(null);
  const [restoring, setRestoring] = useState(
    () => typeof window !== "undefined" && !!readStoredProject(),
  );

  const mounted = useRef(true);
  const activeId = useRef("");
  const sequence = useRef(0);
  const pending = useRef<AbortController | null>(null);
  const controllers = useRef(new Set<AbortController>());
  const pollTimer = useRef<number | null>(null);
  const retry = useRef<(() => void) | null>(null);

  const stopPolling = useCallback(() => {
    if (pollTimer.current !== null && typeof window !== "undefined") {
      window.clearTimeout(pollTimer.current);
    }
    pollTimer.current = null;
  }, []);

  const fail = useCallback((cause: unknown, again?: () => void) => {
    const { message } = commandError(cause);
    setError(message);
    retry.current = again ?? null;
  }, []);

  const poll = useCallback(
    async (projectId: string, taskId: string) => {
      stopPolling();
      const tick = async () => {
        if (!mounted.current || activeId.current !== projectId) return;
        const controller = new AbortController();
        controllers.current.add(controller);
        try {
          const next = await commands
            .forProject(projectId)
            .task(taskId, controller.signal);
          if (!mounted.current || activeId.current !== projectId) return;
          setTask(next);
          if (isIndexing(next)) {
            pollTimer.current = window.setTimeout(
              () => void tick(),
              INDEX_POLL_MS,
            );
            return;
          }
          retry.current = null;
          if (next.status === "completed") {
            const record = await commands
              .forProject(projectId)
              .info(controller.signal);
            if (!mounted.current || activeId.current !== projectId) return;
            setProject(record);
            setRevisionId(record.latest_revision_id ?? "");
          }
        } catch (cause) {
          if (!mounted.current || activeId.current !== projectId) return;
          if (controller.signal.aborted) return;
          fail(cause, () => void tick());
        } finally {
          controllers.current.delete(controller);
        }
      };
      await tick();
    },
    [commands, fail, stopPolling],
  );

  const beginIndex = useCallback(
    async (record: ResearchProject) => {
      stopPolling();
      setBusy(true);
      const controller = new AbortController();
      controllers.current.add(controller);
      try {
        const started = await commands
          .forProject(record.id)
          .index(record.latest_revision_id, controller.signal);
        if (
          !mounted.current ||
          controller.signal.aborted ||
          activeId.current !== record.id
        )
          return;
        setError("");
        retry.current = null;
        setTask(started);
        void poll(record.id, started.id);
      } catch (cause) {
        if (
          !mounted.current ||
          controller.signal.aborted ||
          activeId.current !== record.id
        )
          return;
        fail(cause, () => void beginIndex(record));
      } finally {
        controllers.current.delete(controller);
        if (mounted.current && activeId.current === record.id) setBusy(false);
      }
    },
    [commands, fail, poll, stopPolling],
  );

  const load = useCallback(
    async (id: string, options: { persist: boolean; autoIndex: boolean; restore?: boolean }) => {
      const controller = new AbortController();
      pending.current?.abort();
      pending.current = controller;
      const ticket = ++sequence.current;
      setBusy(true);
      try {
        const record = await commands.forProject(id).info(controller.signal);
        if (
          !mounted.current ||
          controller.signal.aborted ||
          ticket !== sequence.current
        )
          return;
        activeId.current = record.id;
        setProject(record);
        setRevisionId(record.latest_revision_id ?? "");
        setTask(null);
        setError("");
        retry.current = null;
        setChooser(false);
        if (options.persist) storeProject(record.id);
        if (options.autoIndex && !record.latest_revision_id)
          await beginIndex(record);
      } catch (cause) {
        if (
          !mounted.current ||
          controller.signal.aborted ||
          ticket !== sequence.current
        )
          return;
        if (options.persist) storeProject("");
        if (options.restore && commandError(cause).status === 404) {
          setError("");
          retry.current = null;
        } else fail(cause, () => void load(id, options));
        setChooser(true);
      } finally {
        if (mounted.current && ticket === sequence.current) {
          setBusy(false);
          setRestoring(false);
        }
      }
    },
    [beginIndex, commands, fail],
  );

  const openFolder = useCallback(async () => {
    const value = folder.trim();
    if (!value) return;
    const controller = new AbortController();
    pending.current?.abort();
    pending.current = controller;
    const ticket = ++sequence.current;
    setBusy(true);
    try {
      const record = await commands.open(value, controller.signal);
      if (
        !mounted.current ||
        controller.signal.aborted ||
        ticket !== sequence.current
      )
        return;
      activeId.current = record.id;
      setProject(record);
      setRevisionId(record.latest_revision_id ?? "");
      setTask(null);
      setError("");
      setRecent((list) => [
        record,
        ...list.filter((item) => item.id !== record.id),
      ]);
      storeProject(record.id);
      setFolder("");
      setChooser(false);
      if (!record.latest_revision_id) await beginIndex(record);
    } catch (cause) {
      if (
        !mounted.current ||
        controller.signal.aborted ||
        ticket !== sequence.current
      )
        return;
      fail(cause, () => void openFolder());
    } finally {
      if (mounted.current && ticket === sequence.current) setBusy(false);
    }
  }, [beginIndex, commands, fail, folder]);

  const cancelIndex = useCallback(async () => {
    const current = project;
    if (!current || !task || !isIndexing(task)) return;
    const controller = new AbortController();
    controllers.current.add(controller);
    try {
      const next = await commands
        .forProject(current.id)
        .cancelTask(task.id, controller.signal);
      if (
        !mounted.current ||
        controller.signal.aborted ||
        activeId.current !== current.id
      )
        return;
      setTask(next);
    } catch (cause) {
      if (
        !mounted.current ||
        controller.signal.aborted ||
        activeId.current !== current.id
      )
        return;
      fail(cause, () => void cancelIndex());
    } finally {
      controllers.current.delete(controller);
    }
  }, [commands, fail, project, task]);

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    controllers.current.add(controller);
    commands
      .recent(controller.signal)
      .then((list) => {
        if (controller.signal.aborted) return;
        setRecent(list);
        setRecentError("");
      })
      .catch((cause) => {
        if (controller.signal.aborted) return;
        setRecentError(commandError(cause).message);
      });
    const stored = readStoredProject();
    if (stored) void load(stored, { persist: true, autoIndex: false, restore: true });
    else {
      setRestoring(false);
      setChooser(true);
    }
    const aborters = controllers.current;
    return () => {
      mounted.current = false;
      pending.current?.abort();
      aborters.forEach((item) => item.abort());
      aborters.clear();
      stopPolling();
    };
  }, [commands, load, stopPolling]);

  const session: ProjectSession | null =
    project && revisionId
      ? {
          project,
          revisionId,
          onRevision: (id: string) => {
            setRevisionId(id);
            setProject((current) =>
              current ? { ...current, latest_revision_id: id } : current,
            );
          },
          onProject: (next: ResearchProject) => setProject(next),
        }
      : null;
  const indexing = isIndexing(task);
  const status = indexStatus(task);

  return (
    <div className="project-host">
      <div className="project-host-bar">
        {!project && <h1>Scientific Dataflow Inspector</h1>}
        <button
          type="button"
          className="project-host-button"
          aria-expanded={chooser}
          onClick={() => setChooser((value) => !value)}
        >
          {project ? "Switch project" : "Choose project"}
        </button>
        {project ? (
          <span className="project-host-current">
            <strong>{project.name || project.id}</strong>
            <code className="project-host-root">{project.root}</code>
          </span>
        ) : (
          <span className="project-host-current project-host-muted">
            No project open
          </span>
        )}
        {project ? (
          <button
            type="button"
            className="project-host-button"
            disabled={busy || indexing}
            onClick={() => void beginIndex(project)}
          >
            Refresh index
          </button>
        ) : null}
        {indexing ? (
          <button
            type="button"
            className="project-host-button"
            onClick={() => void cancelIndex()}
          >
            Cancel index
          </button>
        ) : null}
        {onLegacy ? (
          <button
            type="button"
            className="project-host-button project-host-legacy"
            onClick={onLegacy}
          >
            Back to legacy
          </button>
        ) : null}
      </div>

      {chooser ? (
        <div className="project-host-chooser">
          <label className="project-host-field">
            <span>Folder path</span>
            <input
              value={folder}
              placeholder="C:\\path\\to\\project"
              onChange={(event) => setFolder(event.target.value)}
            />
          </label>
          <button
            type="button"
            className="project-host-button project-host-open"
            disabled={busy || !folder.trim()}
            onClick={() => void openFolder()}
          >
            Open folder
          </button>
          <div className="project-host-recent">
            <span className="project-host-label">Recent projects</span>
            {recentError ? (
              <p className="project-host-error-text">{recentError}</p>
            ) : recent.length === 0 ? (
              <p className="project-host-muted">No indexed projects yet.</p>
            ) : (
              <ul>
                {recent.map((item) => (
                  <li key={item.id}>
                    <button
                      type="button"
                      className={item.id === project?.id ? "is-active" : ""}
                      onClick={() =>
                        void load(item.id, { persist: true, autoIndex: true })
                      }
                    >
                      <strong>{item.name || item.id}</strong>
                      <code>{item.root}</code>
                      {item.latest_revision_id ? null : <em>not indexed</em>}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      ) : null}

      {error ? (
        <div className="project-host-error" role="alert">
          <span>{error}</span>
          <button
            type="button"
            disabled={!retry.current}
            onClick={() => {
              const again = retry.current;
              setError("");
              retry.current = null;
              again?.();
            }}
          >
            Retry
          </button>
        </div>
      ) : null}

      {restoring && !project ? (
        <p className="project-host-muted">Restoring last project…</p>
      ) : null}

      {indexing ? (
        <div className="project-host-progress" role="status">
          <span className="project-host-progress-track" aria-hidden="true">
            <span style={{ width: `${Math.round(status.progress * 100)}%` }} />
          </span>
          <span className="project-host-progress-label">{status.label}</span>
          {status.progress > 0 ? (
            <span className="project-host-progress-value">
              {Math.round(status.progress * 100)}%
            </span>
          ) : null}
        </div>
      ) : task && task.status !== "completed" && task.message ? (
        <p className="project-host-muted">{task.message}</p>
      ) : null}

      {session ? (
        <div className="project-session" key={session.project.id}>
          {children(session)}
        </div>
      ) : project ? (
        <div className="project-host-unindexed">
          <p>This project has no published revision yet.</p>
          <button
            type="button"
            className="project-host-button project-host-open"
            disabled={busy || indexing}
            onClick={() => void beginIndex(project)}
          >
            Index project
          </button>
        </div>
      ) : null}
    </div>
  );
}

export default ProjectHost;
