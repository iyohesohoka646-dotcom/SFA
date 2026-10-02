import { useEffect, useState } from "react";
import type {
  AnalysisDocument,
  ProbeDefinition,
  ProbeInstance,
  ProbeOutput,
  WorkbenchConfig,
  TargetRef,
} from "./generated";
import type { SnapshotRef } from "../generated";
import { Icon } from "./icons";
import { wb } from "./WorkbenchClient";
import { ParameterForm } from "./ParameterForm";
import {
  purposeNames,
  targetNames,
  implementationNames,
} from "./probe-taxonomy";
import { scopeSelector, selectionKey, type Selection } from "./selection";
export function ProbeInspector({
  config,
  definitions,
  selected,
  analysis,
  outputs,
  onChange,
  onSave,
  onError,
  onRecorded,
  selection,
  blockScope,
  requested,
}: {
  config: WorkbenchConfig;
  definitions: ProbeDefinition[];
  selected?: SnapshotRef;
  analysis?: AnalysisDocument;
  outputs: ProbeOutput[];
  onChange: (c: WorkbenchConfig) => void;
  onSave: () => Promise<unknown>;
  onError: (s: string) => void;
  onRecorded: (o: ProbeOutput) => void;
  selection?: Selection;
  blockScope?: string | null;
  requested?: string;
}) {
  const [adding, setAdding] = useState(false),
    [type, setType] = useState("view.matrix"),
    [range, setRange] = useState<"selection" | "block" | "project">(
      "selection",
    ),
    [purpose, setPurpose] = useState("all"),
    [query, setQuery] = useState(""),
    [editing, setEditing] = useState<string>(),
    [params, setParams] = useState<Record<string, unknown>>({}),
    [note, setNote] = useState(""),
    [verdict, setVerdict] = useState("unknown"),
    [roles, setRoles] = useState<Record<string, string>>({}),
    [templates, setTemplates] = useState<
      {
        id: string;
        label: string;
        definition_id: string;
        parameters: Record<string, unknown>;
      }[]
    >([]);
  useEffect(() => {
    void wb
      .templates()
      .then(setTemplates)
      .catch((e) => onError(e.message));
  }, []);
  const targets = selection?.targets ?? [];
  const definition = definitions.find((d) => d.id === type);
  useEffect(() => {
    if (requested) {
      setType(requested);
      setAdding(true);
      setParams({});
    }
  }, [requested]);
  const add = () => {
    if (!definition) return;
    const inputs: Record<string, TargetRef> = {};
    if (definition.input_mode === "joint") {
      for (const [i, role] of definition.input_roles.entries()) {
        const target =
          targets.find((t) => selectionKey(t) === roles[role.name]) ??
          targets[i];
        if (!target) {
          onError("请先选择联合输入对象");
          return;
        }
        inputs[role.name] = target;
      }
    }
    const instance: ProbeInstance = {
      id: crypto.randomUUID(),
      definition_id: type,
      binding: "*",
      enabled: true,
      parameters: params,
      policy: "continue",
      budget_ms: definition.tool_id ? 30000 : 5000,
      selector:
        definition.input_mode === "joint"
          ? scopeSelector(null, Object.values(inputs), "selection")
          : scopeSelector(blockScope ?? null, targets, range),
      inputs,
      origin: range === "project" ? "project_default" : "local",
      overrides: {},
    };
    onChange({ ...config, probes: [...config.probes, instance] });
    setAdding(false);
    setEditing(instance.id);
  };
  const update = (id: string, patch: Partial<ProbeInstance>) =>
    onChange({
      ...config,
      probes: config.probes.map((p) => (p.id === id ? { ...p, ...patch } : p)),
    });
  const compatible = definitions.filter(
    (d) =>
      (purpose === "all" || d.capability === purpose) &&
      (d.label + " " + d.id).includes(query) &&
      (range === "project" ||
        targets.length === 0 ||
        targets.some((t) => d.supported_targets.includes(t.kind))),
  );
  return (
    <div className="wb-inspector">
      <div className="wb-view-toolbar">
        <strong>探针台</strong>
        <button
          aria-label="添加探针"
          onClick={() => {
            setRange(
              targets.length ? "selection" : blockScope ? "block" : "project",
            );
            setAdding(!adding);
            setParams({});
          }}
        >
          <Icon name="add" />
        </button>
        <button onClick={() => void onSave().catch((e) => onError(e.message))}>
          保存
        </button>
      </div>
      {adding && (
        <div className="probe-binding-form">
          <div className="wb-form compact">
            <label>
              作用范围
              <select
                aria-label="探针绑定范围"
                value={range}
                onChange={(e) => setRange(e.target.value as typeof range)}
              >
                <option value="selection" disabled={!targets.length}>
                  当前选择 ({targets.length})
                </option>
                <option value="block" disabled={!blockScope}>
                  当前块
                </option>
                <option value="project">整个项目</option>
              </select>
            </label>
            <label>
              功能用途
              <select
                aria-label="新探针用途"
                value={purpose}
                onChange={(e) => setPurpose(e.target.value)}
              >
                <option value="all">全部用途</option>
                {Object.entries(purposeNames).map(([k, l]) => (
                  <option value={k} key={k}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            <input
              type="search"
              aria-label="搜索兼容探针"
              placeholder="搜索兼容探针"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <label>
              探针
              <select
                aria-label="探针类型"
                value={type}
                onChange={(e) => {
                  setType(e.target.value);
                  setParams({});
                }}
              >
                {Object.entries(purposeNames).map(([k, l]) => (
                  <optgroup label={l} key={k}>
                    {compatible
                      .filter((d) => d.capability === k)
                      .map((d) => (
                        <option key={d.id} value={d.id}>
                          {d.label}
                        </option>
                      ))}
                  </optgroup>
                ))}
              </select>
            </label>
            {definition?.input_mode === "joint" &&
              definition.input_roles.map((role, i) => (
                <label key={role.name}>
                  {role.name}
                  <select
                    aria-label={"输入角色 " + role.name}
                    value={
                      roles[role.name] ??
                      (targets[i] ? selectionKey(targets[i]) : "")
                    }
                    onChange={(e) =>
                      setRoles({ ...roles, [role.name]: e.target.value })
                    }
                  >
                    <option value="">选择输入</option>
                    {targets
                      .filter((t) => t.kind === "data")
                      .map((t) => (
                        <option key={selectionKey(t)} value={selectionKey(t)}>
                          {t.logical_key.split("::").at(-1)}
                          {t.snapshot_id ? " · 已保存" : " · 下次运行"}
                        </option>
                      ))}
                  </select>
                </label>
              ))}
          </div>
          {templates.some((t) => t.definition_id === type) && (
            <select
              aria-label="探针参数模板"
              onChange={(e) => {
                const t = templates.find((t) => t.id === e.target.value);
                if (t) setParams(t.parameters);
              }}
            >
              <option value="">选择参数模板</option>
              {templates
                .filter((t) => t.definition_id === type)
                .map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.label}
                  </option>
                ))}
            </select>
          )}
          {definition && (
            <ParameterForm
              schema={definition.parameter_schema}
              value={params}
              onChange={setParams}
            />
          )}
          <button
            className="wb-primary"
            aria-label="确认添加探针"
            disabled={!definition || (range === "selection" && !targets.length)}
            onClick={add}
          >
            保存绑定
          </button>
        </div>
      )}
      <div className="wb-probe-list">
        {config.probes.map((probe) => {
          const d = definitions.find((d) => d.id === probe.definition_id),
            count =
              probe.selector?.mode === "selection"
                ? probe.selector.targets.length
                : undefined;
          return (
            <div className="wb-probe-row" key={probe.id}>
              <div>
                <input
                  type="checkbox"
                  aria-label={"启用 " + probe.definition_id}
                  checked={probe.enabled}
                  onChange={(e) =>
                    update(probe.id, { enabled: e.target.checked })
                  }
                />
                <button
                  className="wb-probe-name"
                  onClick={() =>
                    setEditing(editing === probe.id ? undefined : probe.id)
                  }
                >
                  {d?.label ?? probe.definition_id}
                </button>
                <button
                  aria-label={"删除 " + probe.definition_id}
                  onClick={() =>
                    onChange({
                      ...config,
                      probes: config.probes.filter((p) => p.id !== probe.id),
                    })
                  }
                >
                  <Icon name="close" size={12} />
                </button>
              </div>
              <small>
                <span className={"wb-kind " + d?.capability}>
                  {d ? purposeNames[d.capability] : "不可用"}
                </span>{" "}
                {d ? implementationNames[d.execution] : ""} ·{" "}
                {probe.selector?.mode === "project"
                  ? "整个项目"
                  : probe.selector?.mode === "block"
                    ? "块范围"
                    : count !== undefined
                      ? count + " 个目标"
                      : probe.binding}
                {probe.origin === "project_default" ? " · 项目默认" : ""}
              </small>
              {editing === probe.id && (
                <>
                  <ParameterForm
                    schema={d?.parameter_schema ?? {}}
                    value={probe.parameters}
                    onChange={(parameters) => update(probe.id, { parameters })}
                  />
                  <div className="wb-form compact">
                    <label>
                      控制
                      <select
                        value={probe.policy}
                        onChange={(e) =>
                          update(probe.id, {
                            policy: e.target.value as ProbeInstance["policy"],
                          })
                        }
                      >
                        <option value="continue">继续</option>
                        <option value="pause">检查异常时暂停</option>
                        <option value="cancel">检查失败时取消</option>
                      </select>
                    </label>
                    <label>
                      预算 ms
                      <input
                        type="number"
                        value={probe.budget_ms}
                        min={1}
                        max={120000}
                        onChange={(e) =>
                          update(probe.id, {
                            budget_ms: Number(e.target.value),
                          })
                        }
                      />
                    </label>
                    <button
                      onClick={() =>
                        void wb
                          .saveTemplate(
                            crypto.randomUUID(),
                            d?.label ?? probe.id,
                            probe.definition_id,
                            probe.parameters,
                          )
                          .catch((e) => onError(e.message))
                      }
                    >
                      保存为模板
                    </button>
                  </div>
                </>
              )}
            </div>
          );
        })}
      </div>
      {!config.probes.some((p) => p.id === "auto-view") && (
        <button
          onClick={() =>
            onChange({
              ...config,
              probes: [
                ...config.probes,
                {
                  id: "auto-view",
                  definition_id: "view.auto",
                  binding: "*",
                  enabled: true,
                  parameters: {},
                  policy: "continue",
                  budget_ms: 5000,
                  selector: scopeSelector(null, [], "project"),
                  inputs: {},
                  origin: "project_default",
                  overrides: {},
                },
              ],
            })
          }
        >
          恢复项目默认
        </button>
      )}
      <details>
        <summary>人工判断</summary>
        <div className="wb-form compact">
          <textarea
            aria-label="人工判断记录"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <select
            aria-label="人工判断结果"
            value={verdict}
            onChange={(e) => setVerdict(e.target.value)}
          >
            <option value="unknown">待判断</option>
            <option value="pass">通过</option>
            <option value="fail">失败</option>
          </select>
          <button
            disabled={!analysis || !note}
            onClick={() =>
              void wb
                .manual({
                  instance_id: editing ?? "manual",
                  analysis_id: analysis!.id,
                  snapshot_id: selected?.id,
                  note,
                  verdict,
                })
                .then(onRecorded)
                .catch((e) => onError(e.message))
            }
          >
            记录判断
          </button>
        </div>
      </details>
      <div className="wb-section-label">
        此范围的结果{" "}
        <span>
          {
            outputs.filter(
              (o) =>
                !selected ||
                o.snapshot_id === selected.id ||
                o.parent_snapshot_ids.includes(selected.id),
            ).length
          }
        </span>
      </div>
      {outputs
        .filter(
          (o) =>
            !selected ||
            o.snapshot_id === selected.id ||
            o.parent_snapshot_ids.includes(selected.id),
        )
        .slice(0, 50)
        .map((o) => (
          <div
            className={"wb-probe-output " + o.status}
            data-testid="probe-output"
            key={o.id}
          >
            <strong>
              {definitions.find((d) => d.id === o.definition_id)?.label ??
                o.definition_id}
            </strong>
            <span>{o.status}</span>
            <p>{o.message}</p>
          </div>
        ))}
    </div>
  );
}
