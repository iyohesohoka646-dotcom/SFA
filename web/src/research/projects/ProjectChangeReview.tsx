/** P4 reviewed project-change panel.
 *
 * Loads the project's reviewed proposals plus its recovery state, shows the
 * sanitized (possibly redacted/empty) diff, validation and affected references,
 * and exposes explicit accept / reject / rollback actions. A queued accept task
 * is never treated as an accepted change: acceptance only counts after the
 * owned task finishes and the reloaded change carries a non-empty
 * ``accepted_revision``. Recovery never auto-accepts; rollback only creates a
 * new review proposal.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type { TaskRecord } from "../workspace/generated";
import {
  createProjectIntelligenceClient,
  type ProjectIntelligenceClient,
} from "./intelligenceClient";
import type {
  ChangeValidation,
  ProjectChangePage,
  ProjectChangeSet,
  ProjectRecoveryState,
} from "./generated";
import "./project-intelligence.css";

const messageOf = (error: unknown) =>
  error instanceof Error ? error.message : String(error);

const isAbort = (error: unknown) =>
  !!error &&
  typeof error === "object" &&
  (error as { name?: string }).name === "AbortError";

const sleep = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer);
      const error = new Error("aborted");
      error.name = "AbortError";
      reject(error);
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", abort);
      resolve();
    }, ms);
    signal.addEventListener("abort", abort, { once: true });
  });

const baseName = (path: string) => path.split(/[\\/]/).at(-1) || path;

const validationTone = (validation: ChangeValidation) =>
  validation.status === "fail"
    ? "pi-chip bad"
    : validation.status === "pass"
      ? "pi-chip"
      : "pi-chip warn";

export interface ProjectChangeReviewProps {
  projectId: string;
  revisionId: string;
  changeId?: string;
  onRevision: (revisionId: string) => void;
  onError: (message: string) => void;
  client?: ProjectIntelligenceClient;
}

export function ProjectChangeReview({
  projectId,
  revisionId,
  changeId,
  onRevision,
  onError,
  client,
}: ProjectChangeReviewProps) {
  const projectClient = useMemo(
    () => client ?? createProjectIntelligenceClient(projectId),
    [client, projectId],
  );
  const [page, setPage] = useState<ProjectChangePage>();
  const [recovery, setRecovery] = useState<ProjectRecoveryState>();
  const [selectedId, setSelectedId] = useState(changeId ?? "");
  const [change, setChange] = useState<ProjectChangeSet>();
  const [activeFile, setActiveFile] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [task, setTask] = useState<TaskRecord>();
  const [refreshKey, setRefreshKey] = useState(0);
  const actionRef = useRef<AbortController | null>(null);

  const reload = () => setRefreshKey((current) => current + 1);

  useEffect(() => {
    return () => actionRef.current?.abort();
  }, [projectId]);

  useEffect(() => {
    if (changeId) setSelectedId(changeId);
  }, [changeId]);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      projectClient.changes(controller.signal),
      projectClient.recovery(controller.signal),
    ])
      .then(([nextPage, nextRecovery]) => {
        if (controller.signal.aborted) return;
        setPage(nextPage);
        setRecovery(nextRecovery);
      })
      .catch((reason) => {
        if (controller.signal.aborted || isAbort(reason)) return;
        const message = messageOf(reason);
        setError(message);
        onError(message);
      });
    return () => controller.abort();
  }, [projectClient, changeId, refreshKey]);

  useEffect(() => {
    if (selectedId) return;
    const first = changeId || page?.items[0]?.id;
    if (first) setSelectedId(first);
  }, [page, changeId, selectedId]);

  useEffect(() => {
    if (!selectedId) {
      setChange(undefined);
      return;
    }
    setChange(undefined);
    const controller = new AbortController();
    projectClient
      .change(selectedId, controller.signal)
      .then((next) => {
        if (controller.signal.aborted) return;
        setChange(next);
        setActiveFile(0);
      })
      .catch((reason) => {
        if (controller.signal.aborted || isAbort(reason)) return;
        const message = messageOf(reason);
        setError(message);
        onError(message);
      });
    return () => controller.abort();
  }, [projectClient, selectedId, refreshKey]);

  const fail = (reason: unknown) => {
    if (isAbort(reason)) return;
    const message = messageOf(reason);
    setError(message);
    onError(message);
  };

  const begin = () => {
    setError("");
    const controller = new AbortController();
    actionRef.current?.abort();
    actionRef.current = controller;
    return controller.signal;
  };

  const pollTask = async (
    id: string,
    signal: AbortSignal,
  ): Promise<TaskRecord | undefined> => {
    for (;;) {
      if (signal.aborted) return undefined;
      const current = await projectClient.task(id, signal);
      if (signal.aborted) return undefined;
      setTask(current);
      if (
        current.status === "completed" ||
        ["failed", "cancelled", "interrupted"].includes(current.status)
      )
        return current;
      await sleep(350, signal);
    }
  };

  const accept = async () => {
    if (!change || change.id !== selectedId) return;
    setStatus("");
    const signal = begin();
    setBusy("accept");
    try {
      const queued = await projectClient.accept(change.id, revisionId, signal);
      if (signal.aborted) return;
      setTask(queued);
      const done = await pollTask(queued.id, signal);
      if (!done) return;
      if (done.status !== "completed") {
        fail(done.message || `任务${done.status}`);
        reload();
        return;
      }
      const fresh = await projectClient.change(change.id, signal);
      if (signal.aborted) return;
      setChange(fresh);
      reload();
      if (fresh.accepted_revision) onRevision(fresh.accepted_revision);
      else setStatus("接受任务已完成，但尚未发布新修订；请重新索引后再检查。");
    } catch (reason) {
      fail(reason);
    } finally {
      if (!signal.aborted) setBusy(null);
    }
  };

  const reject = async () => {
    if (!change || change.id !== selectedId) return;
    setStatus("");
    const signal = begin();
    setBusy("reject");
    try {
      const updated = await projectClient.reject(change.id, revisionId, signal);
      if (signal.aborted) return;
      setChange(updated);
      reload();
      setStatus(`已退回 · ${updated.status}`);
    } catch (reason) {
      fail(reason);
    } finally {
      if (!signal.aborted) setBusy(null);
    }
  };

  const rollback = async () => {
    if (!change || change.id !== selectedId) return;
    setStatus("");
    const signal = begin();
    setBusy("rollback");
    try {
      const created = await projectClient.rollback(
        change.id,
        revisionId,
        signal,
      );
      if (signal.aborted) return;
      setChange(created);
      setSelectedId(created.id);
      reload();
      setStatus(`已创建回滚提案 · ${created.status}（需人工接受）`);
    } catch (reason) {
      fail(reason);
    } finally {
      if (!signal.aborted) setBusy(null);
    }
  };

  const recover = async () => {
    setStatus("");
    const signal = begin();
    setBusy("recover");
    try {
      const restored = await projectClient.recover(revisionId, signal);
      if (signal.aborted) return;
      setChange(restored);
      setSelectedId(restored.id);
      reload();
      setStatus(`已恢复中断的写入 · ${restored.status}`);
    } catch (reason) {
      fail(reason);
    } finally {
      if (!signal.aborted) setBusy(null);
    }
  };

  const baseStale =
    !!change &&
    !!page &&
    !!change.base_revision &&
    change.base_revision !== page.revision_id;
  const recoveryRequired =
    recovery?.required === true ||
    page?.recovery_required === true ||
    change?.status === "recovery_required";
  const acceptDisabled =
    busy !== null ||
    !change ||
    change.id !== selectedId ||
    change.status !== "ready" ||
    baseStale ||
    recoveryRequired;
  const gate = recoveryRequired
    ? "需先恢复中断的写入"
    : baseStale
      ? "基线已变化，请刷新"
      : change && change.status !== "ready"
        ? `状态 ${change.status}`
        : "";

  const file = change?.files[activeFile];
  const diff = file?.diff ?? "";

  return (
    <section className="pi-review" aria-label="项目变更审查">
      <div className="pi-toolbar">
        <strong>变更审查</strong>
        <span className="pi-muted">修订 {revisionId.slice(0, 8)}</span>
        <button type="button" onClick={reload} disabled={busy !== null}>
          刷新
        </button>
      </div>
      {recoveryRequired && (
        <div className="pi-error" role="alert">
          <span>存在中断的写入，接受已停用。</span>
          <button
            type="button"
            onClick={() => void recover()}
            disabled={busy !== null}
          >
            {busy === "recover" ? "恢复中…" : "恢复"}
          </button>
        </div>
      )}
      {error && (
        <div className="pi-error" role="alert">
          <span>{error}</span>
        </div>
      )}
      {status && (
        <span className="pi-status" role="status">
          {status}
        </span>
      )}
      {task && (
        <span className="pi-status" role="status">
          任务 {task.id.slice(0, 8)} · {task.status}
          {task.message ? ` · ${task.message}` : ""}
        </span>
      )}
      <div className="pi-scroll">
        <div className="pi-list" role="listbox" aria-label="变更提案">
          {(page?.items ?? []).map((item) => (
            <button
              type="button"
              key={item.id}
              role="option"
              aria-selected={item.id === selectedId}
              onClick={() => setSelectedId(item.id)}
            >
              {item.id.slice(0, 8)} · {item.status} · {item.files.length} 个文件
            </button>
          ))}
          {page && !page.items.length && (
            <span className="pi-status">暂无审查中的提案。</span>
          )}
        </div>
        {change ? (
          <>
            <div className="pi-row">
              <strong>{change.status}</strong>
              {!!change.base_revision && (
                <span className="pi-muted">
                  基线 {change.base_revision.slice(0, 8)}
                </span>
              )}
              {change.rollback_of && (
                <span className="pi-chip">
                  回滚 {change.rollback_of.slice(0, 8)}
                </span>
              )}
            </div>
            {!!change.validation.length && (
              <div className="pi-chips">
                {change.validation.map((validation, index) => (
                  <span
                    className={validationTone(validation)}
                    key={`${validation.kind}-${index}`}
                    title={validation.detail}
                  >
                    {validation.kind} · {validation.status}
                  </span>
                ))}
              </div>
            )}
            {!!change.affected_references.length && (
              <details className="pi-details">
                <summary>
                  受影响引用 · {change.affected_references.length}
                </summary>
                <div className="pi-chips">
                  {change.affected_references.map((reference) => (
                    <code className="pi-chip" key={reference}>
                      {reference}
                    </code>
                  ))}
                </div>
              </details>
            )}
            <div className="pi-files">
              {change.files.map((item, index) => (
                <button
                  type="button"
                  key={item.path}
                  aria-pressed={index === activeFile}
                  onClick={() => setActiveFile(index)}
                >
                  {baseName(item.path)} · {item.operation}
                </button>
              ))}
            </div>
            {file ? (
              <>
                <span className="pi-muted">{file.path}</span>
                {!!file.diagnostics.length && (
                  <div className="pi-error" role="alert">
                    {file.diagnostics.map((detail, index) => (
                      <span key={index}>{detail}</span>
                    ))}
                  </div>
                )}
                {diff ? (
                  <pre className="pi-diff" data-testid="change-diff">
                    {diff.split("\n").map((line, index) => (
                      <span
                        key={index}
                        className={
                          line.startsWith("+")
                            ? "pi-add"
                            : line.startsWith("-")
                              ? "pi-del"
                              : ""
                        }
                      >
                        {line + "\n"}
                      </span>
                    ))}
                  </pre>
                ) : (
                  <span className="pi-status" role="status">
                    后端未返回差异（可能已脱敏）。
                  </span>
                )}
              </>
            ) : (
              <span className="pi-status">该提案没有文件。</span>
            )}
            {gate && (
              <span className="pi-status" role="status">
                {gate}
              </span>
            )}
            <div className="pi-row">
              <button
                type="button"
                className="pi-primary"
                disabled={acceptDisabled}
                onClick={() => void accept()}
              >
                {busy === "accept" ? "接受中…" : "接受并发布"}
              </button>
              <button
                type="button"
                disabled={
                  busy !== null || recoveryRequired || change.status !== "ready"
                }
                onClick={() => void reject()}
              >
                {busy === "reject" ? "退回中…" : "退回提案"}
              </button>
              <button
                type="button"
                disabled={
                  busy !== null ||
                  recoveryRequired ||
                  change.status !== "accepted"
                }
                onClick={() => void rollback()}
              >
                {busy === "rollback" ? "生成中…" : "生成回滚提案"}
              </button>
            </div>
          </>
        ) : (
          <span className="pi-status">选择提案查看差异。</span>
        )}
      </div>
    </section>
  );
}

export default ProjectChangeReview;
