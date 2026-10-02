import { useEffect, useState } from "react";
import { models } from "../../settings/client";
import type { PublicProviderProfile } from "../../settings/generated";
import type {
  AnalysisDocument,
  HarnessPolicy,
  SourceObject,
  TaskRecord,
  WorkbenchConfig,
} from "./generated";
import type { SnapshotRef } from "../generated";
import { wb, type ContextRecord, type SkillRecord } from "./WorkbenchClient";

export function IntelligencePanel({
  analysis,
  object,
  snapshot,
  config,
  onChange,
  onSave,
  onTask,
  onContext,
  onModels,
  onError,
}: {
  analysis?: AnalysisDocument;
  object?: SourceObject;
  snapshot?: SnapshotRef;
  config: WorkbenchConfig;
  onChange: (config: WorkbenchConfig) => void;
  onSave: () => Promise<unknown>;
  onTask: (task: TaskRecord) => void;
  onContext: (id: string) => void;
  onModels: () => void;
  onError: (message: string) => void;
}) {
  const [role, setRole] = useState<HarnessPolicy["role"]>("explain"),
    [question, setQuestion] = useState(""),
    [settings, setSettings] = useState(false);
  const [profiles, setProfiles] = useState<PublicProviderProfile[]>([]),
    [skills, setSkills] = useState<SkillRecord[]>([]),
    [skill, setSkill] = useState(""),
    [skillPath, setSkillPath] = useState("");
  const [contexts, setContexts] = useState<
    Omit<ContextRecord, "calls" | "tools">[]
  >([]);
  const policy = config.harness.find((p) => p.role === role)!;
  const update = (patch: Partial<HarnessPolicy>) =>
    onChange({
      ...config,
      harness: config.harness.map((p) =>
        p.role === role ? { ...p, ...patch } : p,
      ),
    });
  useEffect(() => {
    const abort = new AbortController();
    void models
      .list(abort.signal)
      .then(setProfiles)
      .catch(() => {});
    void wb
      .skills(abort.signal)
      .then(setSkills)
      .catch(() => {});
    void wb
      .contexts(abort.signal)
      .then(setContexts)
      .catch(() => {});
    return () => abort.abort();
  }, [settings]);
  const ask = () => {
    if (!analysis) return;
    const matched = snapshot?.source?.digest === analysis.source_digest;
    void onSave()
      .then(() =>
        wb.ask({
          source_object_ids: null,
          question,
          analysis_id: analysis.id,
          object_id: object?.id ?? null,
          run_id: matched ? snapshot!.run_id : null,
          snapshot_id: matched ? snapshot!.id : null,
          skill_id: skill || null,
          policy,
        }),
      )
      .then(onTask)
      .catch((error) => onError(error.message));
  };
  return (
    <div className="wb-full-pane">
      <div className="wb-view-toolbar">
        <strong>智能助手</strong>
        <select
          aria-label="智能任务角色"
          value={role}
          onChange={(e) => setRole(e.target.value as HarnessPolicy["role"])}
        >
          <option value="explain">解读</option>
          <option value="parse">解析</option>
          <option value="probe">探针</option>
          <option value="code">代码修改</option>
        </select>
        <button onClick={() => setSettings(!settings)} aria-expanded={settings}>
          任务设置
        </button>
        <button onClick={onModels}>模型设置</button>
      </div>
      <div className="wb-scroll wb-ai-content">
        {settings && (
          <div className="wb-form wb-role-settings">
            <label>
              模型服务
              <select
                aria-label="任务模型服务"
                value={policy.provider_id}
                onChange={(e) =>
                  update({
                    provider_id: e.target.value,
                    model:
                      profiles.find((p) => p.id === e.target.value)
                        ?.default_model ?? null,
                  })
                }
              >
                {profiles.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.id} · {p.protocol}
                  </option>
                ))}
              </select>
            </label>
            <label>
              模型
              <input
                aria-label="任务模型"
                value={policy.model ?? ""}
                onChange={(e) => update({ model: e.target.value || null })}
                list="harness-model-list"
              />
            </label>
            <datalist id="harness-model-list">
              {profiles
                .find((p) => p.id === policy.provider_id)
                ?.models.map((id) => (
                  <option value={id} key={id} />
                ))}
            </datalist>
            <label>
              输入预算
              <input
                type="number"
                min="512"
                max="128000"
                value={policy.input_tokens}
                onChange={(e) =>
                  update({ input_tokens: Number(e.target.value) })
                }
              />
            </label>
            <label>
              输出预算
              <input
                type="number"
                min="128"
                max="16384"
                value={policy.output_tokens}
                onChange={(e) =>
                  update({ output_tokens: Number(e.target.value) })
                }
              />
            </label>
            <label>
              最大步骤
              <input
                type="number"
                min="1"
                max="16"
                value={policy.max_steps}
                onChange={(e) => update({ max_steps: Number(e.target.value) })}
              />
            </label>
            <label>
              调用预算
              <input
                type="number"
                min="1"
                max="16"
                value={policy.max_calls}
                onChange={(e) => update({ max_calls: Number(e.target.value) })}
              />
            </label>
            <label>
              <input
                type="checkbox"
                checked={policy.include_samples}
                onChange={(e) => update({ include_samples: e.target.checked })}
              />
              允许读取脱敏样例
            </label>
            <label>
              <input
                type="checkbox"
                checked={policy.allow_execute}
                onChange={(e) => update({ allow_execute: e.target.checked })}
              />
              允许运行已验证计划
            </label>
            <button
              onClick={() => void onSave().catch((e) => onError(e.message))}
            >
              保存任务设置
            </button>
          </div>
        )}
        <div className="wb-ai-focus">
          <span>{object?.qualname ?? "当前源码"}</span>
          <span>
            {snapshot ? snapshot.name + " · v" + snapshot.version : ""}
          </span>
          <small>
            {policy.provider_id} / {policy.model ?? "默认模型"}
          </small>
        </div>
        <textarea
          className="wb-task-input"
          aria-label="任务指令"
          placeholder="描述要理解、检查或修改的计算…"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
        />
        <div className="wb-ai-actions">
          <select
            aria-label="使用 Skill"
            value={skill}
            onChange={(e) => setSkill(e.target.value)}
          >
            <option value="">不使用 Skill</option>
            {skills.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title}
              </option>
            ))}
          </select>
          <button
            className="wb-primary"
            disabled={!analysis || !question.trim()}
            onClick={ask}
          >
            执行智能任务
          </button>
        </div>
        <details className="wb-skill-import">
          <summary>导入 Skill</summary>
          <input
            aria-label="Skill 路径"
            value={skillPath}
            onChange={(e) => setSkillPath(e.target.value)}
            placeholder="SKILL.md 路径"
          />
          <button
            disabled={!skillPath}
            onClick={() =>
              void wb
                .registerSkill(skillPath)
                .then((value) => {
                  setSkills((s) => [
                    ...s.filter((v) => v.id !== value.id),
                    value,
                  ]);
                  setSkill(value.id);
                })
                .catch((error) => onError(error.message))
            }
          >
            导入
          </button>
        </details>
        <div className="wb-section-label">
          调用记录{" "}
          <button
            onClick={() =>
              void wb
                .contexts()
                .then(setContexts)
                .catch((e) => onError(e.message))
            }
          >
            刷新
          </button>
        </div>
        {contexts.map((context) => (
          <button
            className="wb-context-row"
            key={context.id}
            onClick={() => onContext(context.id)}
          >
            <strong>
              {context.policy.role} · {context.status}
            </strong>
            <small>
              {context.answer || context.message || context.id.slice(0, 8)}
            </small>
          </button>
        ))}
      </div>
    </div>
  );
}

export function ContextView({
  id,
  onError,
}: {
  id: string;
  onError: (message: string) => void;
}) {
  const [record, setRecord] = useState<ContextRecord>();
  useEffect(() => {
    const abort = new AbortController();
    void wb
      .context(id, abort.signal)
      .then(setRecord)
      .catch((error) => {
        if (!abort.signal.aborted) onError(error.message);
      });
    return () => abort.abort();
  }, [id]);
  if (!record) return <div className="wb-empty">读取调用记录…</div>;
  return (
    <div className="wb-full-pane">
      <div className="wb-view-toolbar">
        <strong>实际上下文</strong>
        <span>
          {record.status} · {record.provenance}
        </span>
      </div>
      <div className="wb-scroll wb-context-view">
        <div className="wb-ai-answer">{record.answer || record.message}</div>
        {record.citations.map((c) => (
          <code key={c}>{c}</code>
        ))}
        {record.calls.map((call, i) => (
          <details key={i}>
            <summary>
              调用 {i + 1} · {call.status} · 输入上界 {call.input_token_bound} ·{" "}
              {call.duration_ms?.toFixed(0)} ms
            </summary>
            {call.messages.map((message, j) => (
              <div key={j}>
                <strong>{message.role}</strong>
                <pre className="wb-json">{message.content}</pre>
              </div>
            ))}
            <pre className="wb-json">{call.response}</pre>
            <small>{JSON.stringify(call.usage)}</small>
          </details>
        ))}
        {record.tools.map((tool, i) => (
          <details key={i}>
            <summary>{tool.name}</summary>
            <pre className="wb-json">
              {JSON.stringify(
                { arguments: tool.arguments, output: tool.output },
                null,
                2,
              )}
            </pre>
          </details>
        ))}
      </div>
    </div>
  );
}
