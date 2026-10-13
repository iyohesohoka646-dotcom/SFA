/** P4 project intelligence panel: explicit, revision-bound questions only.
 *
 * One input project, one frozen revision per request. Nothing here reads an
 * ambient current project or fires a preview/ask implicitly on render or on a
 * selection change; both actions are explicit buttons. The selected scope is
 * an explicit ``ScopeSelector``; file ids are only sent for an all-files
 * selection. The model policy is the existing harness policy for the role.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { ProbeModelFields } from "../workspace/ProbeModelFields";
import type {
  HarnessPolicy,
  TaskRecord,
  WorkbenchConfig,
} from "../workspace/generated";
import {
  createProjectIntelligenceClient,
  type ContextRecord,
  type ProjectIntelligenceClient,
} from "./intelligenceClient";
import type {
  ProjectAIRequest,
  ProjectContextPreview,
  Role,
  TargetRef,
} from "./generated";
import "./project-intelligence.css";

const ROLES: { value: Role; label: string }[] = [
  { value: "explain", label: "解读" },
  { value: "probe", label: "探针" },
  { value: "code", label: "生成" },
];

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

export interface ProjectIntelligencePanelProps {
  projectId: string;
  revisionId: string;
  entryId?: string;
  selection?: TargetRef[];
  config: WorkbenchConfig;
  onChange: (config: WorkbenchConfig) => void;
  onSave: () => Promise<unknown>;
  onTask: (task: TaskRecord) => void;
  onModels: () => void;
  onError: (message: string) => void;
  onOpenChange?: (id: string) => void;
  client?: ProjectIntelligenceClient;
}

export function ProjectIntelligencePanel({
  projectId,
  revisionId,
  entryId,
  selection,
  config,
  onChange,
  onSave,
  onTask,
  onModels,
  onError,
  onOpenChange,
  client,
}: ProjectIntelligencePanelProps) {
  const projectClient = useMemo(
    () => client ?? createProjectIntelligenceClient(projectId),
    [client, projectId],
  );
  const [role, setRole] = useState<Role>("explain");
  const [purpose, setPurpose] = useState<"general" | "format_source">(
    "general",
  );
  const [question, setQuestion] = useState("");
  const [scopeMode, setScopeMode] = useState<"project" | "selection">(
    "project",
  );
  const [settings, setSettings] = useState(false);
  const [busy, setBusy] = useState<"preview" | "ask" | null>(null);
  const [error, setError] = useState("");
  const [lastAction, setLastAction] = useState<"preview" | "ask" | null>(null);
  const [preview, setPreview] = useState<ProjectContextPreview>();
  const [sent, setSent] = useState<ProjectAIRequest>();
  const [task, setTask] = useState<TaskRecord>();
  const [contextId, setContextId] = useState("");
  const [context, setContext] = useState<ContextRecord>();
  const [status, setStatus] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  const effectiveRole: Role = purpose === "format_source" ? "code" : role;
  const policy = config.harness.find((item) => item.role === effectiveRole);
  const selected = (selection ?? []).filter((target) => !!target);
  const fileIds = useMemo(() => {
    if (scopeMode !== "selection" || !selected.length) return null;
    if (!selected.every((target) => !!target.file_id)) return null;
    return [
      ...new Set(
        selected
          .map((target) => target.file_id)
          .filter((id): id is string => Boolean(id)),
      ),
    ];
  }, [scopeMode, selected]);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, [projectId]);

  const updatePolicy = (patch: Partial<HarnessPolicy>) => {
    onChange({
      ...config,
      harness: config.harness.map((item) =>
        item.role === effectiveRole ? { ...item, ...patch } : item,
      ),
    });
  };

  const buildRequest = (): ProjectAIRequest | null => {
    if (!policy) return null;
    const narrow = scopeMode === "selection" && selected.length > 0;
    return {
      question: question.trim(),
      analysis_id: "",
      object_id: null,
      source_object_ids: null,
      run_id: null,
      snapshot_id: null,
      skill_id: null,
      policy: { ...policy, role: effectiveRole },
      purpose,
      project_id: projectId,
      project_revision_id: revisionId,
      entry_id: entryId ?? null,
      scope_id: null,
      file_ids: narrow ? fileIds : null,
      scope: narrow
        ? {
            mode: "selection",
            block_id: null,
            targets: selected,
            excluded_keys: [],
          }
        : { mode: "project", block_id: null, targets: [], excluded_keys: [] },
    };
  };

  const fail = (reason: unknown) => {
    if (isAbort(reason)) return;
    const message = messageOf(reason);
    setError(message);
    onError(message);
  };

  const runPreview = async () => {
    const request = buildRequest();
    if (!request) {
      setError("当前角色缺少任务策略，请先在任务设置中保存。");
      return;
    }
    setError("");
    setStatus("");
    setBusy("preview");
    setLastAction("preview");
    const controller = new AbortController();
    abortRef.current?.abort();
    abortRef.current = controller;
    try {
      const result = await projectClient.preview(request, controller.signal);
      if (controller.signal.aborted) return;
      setPreview(result);
      setSent(request);
    } catch (reason) {
      fail(reason);
    } finally {
      if (!controller.signal.aborted) setBusy(null);
    }
  };

  const loadContext = async (id: string, signal: AbortSignal) => {
    setContextId(id);
    const record = await projectClient.context(id, signal);
    if (!signal.aborted) setContext(record);
  };

  const pollTask = async (taskId: string, signal: AbortSignal) => {
    for (;;) {
      if (signal.aborted) return;
      const current = await projectClient.task(taskId, signal);
      if (signal.aborted) return;
      setTask(current);
      if (current.status === "completed") {
        const receiptId = current.receipt?.context_id;
        if (typeof receiptId !== "string" || !receiptId) {
          setStatus("任务完成，但没有可读取的上下文标识。");
          return;
        }
        await loadContext(receiptId, signal);
        return;
      }
      if (["failed", "cancelled", "interrupted"].includes(current.status)) {
        const message = current.message || `任务${current.status}`;
        setError(message);
        onError(message);
        return;
      }
      await sleep(350, signal);
    }
  };

  const runAsk = async () => {
    const request = buildRequest();
    if (!request) {
      setError("当前角色缺少任务策略，请先在任务设置中保存。");
      return;
    }
    setError("");
    setStatus("");
    setPreview(undefined);
    setContext(undefined);
    setContextId("");
    setTask(undefined);
    const frozen = request;
    setSent(frozen);
    setLastAction("ask");
    setBusy("ask");
    const controller = new AbortController();
    abortRef.current?.abort();
    abortRef.current = controller;
    try {
      await onSave();
      const created = await projectClient.ask(frozen, controller.signal);
      if (controller.signal.aborted) return;
      setTask(created);
      onTask(created);
      await pollTask(created.id, controller.signal);
    } catch (reason) {
      fail(reason);
    } finally {
      if (!controller.signal.aborted) setBusy(null);
    }
  };

  const retry = () => {
    if (lastAction === "preview") void runPreview();
    else if (lastAction === "ask") void runAsk();
  };

  const askDisabled =
    !policy ||
    busy !== null ||
    !question.trim() ||
    (scopeMode === "selection" && selected.length === 0);

  return (
    <section className="pi-panel" aria-label="项目智能助手">
      <div className="pi-toolbar">
        <strong>项目智能</strong>
        <span className="pi-muted">修订 {revisionId.slice(0, 8)}</span>
        <button
          type="button"
          aria-expanded={settings}
          onClick={() => setSettings(!settings)}
        >
          任务设置
        </button>
      </div>
      <div className="pi-row">
        <label className="pi-field">
          用途
          <select
            aria-label="智能任务角色"
            value={role}
            onChange={(event) => setRole(event.target.value as Role)}
          >
            {ROLES.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label className="pi-field">
          目的
          <select
            aria-label="智能任务目的"
            value={purpose}
            onChange={(event) =>
              setPurpose(event.target.value as "general" | "format_source")
            }
          >
            <option value="general">一般提问</option>
            <option value="format_source">整理源码</option>
          </select>
        </label>
        <label className="pi-field">
          范围
          <select
            aria-label="任务范围"
            value={scopeMode}
            onChange={(event) =>
              setScopeMode(event.target.value as "project" | "selection")
            }
          >
            <option value="project">整个项目</option>
            <option value="selection" disabled={!selected.length}>
              已选源码{selected.length ? ` (${selected.length})` : ""}
            </option>
          </select>
        </label>
      </div>
      {settings && (
        <div className="pi-details" aria-label="任务设置">
          {policy ? (
            <>
              <div className="pi-row">
                <label className="pi-field">
                  输入预算
                  <input
                    type="number"
                    aria-label="输入预算"
                    value={policy.input_tokens}
                    onChange={(event) =>
                      updatePolicy({ input_tokens: Number(event.target.value) })
                    }
                  />
                </label>
                <label className="pi-field">
                  输出预算
                  <input
                    type="number"
                    aria-label="输出预算"
                    value={policy.output_tokens}
                    onChange={(event) =>
                      updatePolicy({
                        output_tokens: Number(event.target.value),
                      })
                    }
                  />
                </label>
                <label className="pi-field">
                  最大步骤
                  <input
                    type="number"
                    aria-label="最大步骤"
                    value={policy.max_steps}
                    onChange={(event) =>
                      updatePolicy({ max_steps: Number(event.target.value) })
                    }
                  />
                </label>
                <label className="pi-field">
                  调用预算
                  <input
                    type="number"
                    aria-label="调用预算"
                    value={policy.max_calls}
                    onChange={(event) =>
                      updatePolicy({ max_calls: Number(event.target.value) })
                    }
                  />
                </label>
              </div>
              <ProbeModelFields
                labelPrefix="任务"
                value={{
                  provider_id: policy.provider_id,
                  model: policy.model ?? "",
                }}
                onChange={(value) =>
                  updatePolicy({
                    provider_id: String(value.provider_id ?? ""),
                    model: value.model ? String(value.model) : null,
                  })
                }
                onModelSettings={onModels}
              />
              <div className="pi-row">
                <button
                  type="button"
                  onClick={() => void onSave().catch((reason) => fail(reason))}
                >
                  保存任务设置
                </button>
              </div>
            </>
          ) : (
            <span className="pi-status" role="status">
              当前角色尚未配置任务策略。
            </span>
          )}
        </div>
      )}
      <textarea
        className="pi-textarea"
        aria-label="问题或整理要求"
        placeholder={
          purpose === "format_source"
            ? "可选：分行、缩进、段落等书写要求"
            : "描述要理解、检查或修改的计算…"
        }
        value={question}
        onChange={(event) => setQuestion(event.target.value)}
      />
      <div className="pi-row">
        <button
          type="button"
          disabled={askDisabled}
          onClick={() => void runPreview()}
        >
          {busy === "preview" ? "预览中…" : "上下文预览"}
        </button>
        <button
          type="button"
          className="pi-primary"
          disabled={askDisabled}
          onClick={() => void runAsk()}
        >
          {busy === "ask"
            ? "提问中…"
            : purpose === "format_source"
              ? "整理源码"
              : "提问"}
        </button>
        {sent && (
          <span className="pi-muted">
            {sent.scope?.mode === "selection" ? "已选源码" : "整个项目"} ·{" "}
            {sent.project_revision_id.slice(0, 8)}
          </span>
        )}
      </div>
      {error && (
        <div className="pi-error" role="alert">
          <span>{error}</span>
          {lastAction && (
            <button type="button" onClick={retry} disabled={busy !== null}>
              重试
            </button>
          )}
        </div>
      )}
      {status && (
        <span className="pi-status" role="status">
          {status}
        </span>
      )}
      <div className="pi-scroll">
        {preview && (
          <details className="pi-details">
            <summary>
              上下文预览 · 上界 {preview.token_bound} tokens ·{" "}
              {preview.tools.length} 个工具
            </summary>
            <div className="pi-field">
              <span className="pi-muted">
                {preview.messages.length} 条消息 · 工具仅名称/说明，不含源码正文
              </span>
              <div className="pi-chips">
                {preview.tools.map((tool, index) => (
                  <span className="pi-chip" key={index}>
                    {String(tool.name ?? index)}
                  </span>
                ))}
              </div>
            </div>
          </details>
        )}
        {task && (
          <span className="pi-status" role="status">
            任务 {task.id.slice(0, 8)} · {task.status}
            {task.message ? ` · ${task.message}` : ""}
          </span>
        )}
        {contextId && !context && (
          <span className="pi-status" role="status">
            读取上下文 {contextId.slice(0, 8)}…
          </span>
        )}
        {context && (
          <div className="pi-field">
            <div className="pi-row">
              <strong>回答</strong>
              <span className="pi-muted">
                {context.status} · {context.provenance}
              </span>
            </div>
            <div className="pi-answer">
              {context.answer || context.message || ""}
            </div>
            {!!context.citations.length && (
              <div className="pi-chips">
                {context.citations.map((citation) => {
                  const proposal = citation.startsWith("proposal:")
                    ? citation.slice("proposal:".length)
                    : "";
                  return proposal && onOpenChange ? (
                    <button
                      type="button"
                      className="pi-chip"
                      key={citation}
                      onClick={() => onOpenChange(proposal)}
                    >
                      查看变更 {proposal.slice(0, 8)}
                    </button>
                  ) : (
                    <code className="pi-chip" key={citation}>
                      {citation}
                    </code>
                  );
                })}
              </div>
            )}
            <div className="pi-chips">
              <span className="pi-chip">{context.calls.length} 次调用</span>
              <span className="pi-chip">{context.tools.length} 条工具回执</span>
            </div>
            <details className="pi-details">
              <summary>工具回执</summary>
              <pre className="pi-diff">
                {JSON.stringify(
                  context.tools.map((tool) => ({
                    name: tool.name,
                    output: tool.output,
                  })),
                  null,
                  2,
                )}
              </pre>
            </details>
          </div>
        )}
      </div>
    </section>
  );
}

export default ProjectIntelligencePanel;
