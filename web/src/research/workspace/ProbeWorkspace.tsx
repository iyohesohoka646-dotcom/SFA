import { memo, useEffect, useState } from "react";
import { MatrixView } from "../MatrixView";
import { TableView } from "../TableView";
import { displayCell } from "../matrix-renderer";
import { renderers } from "../renderer-registry";
import { client } from "../client";
import type { SnapshotRef } from "../generated";
import type {
  ProbeOutput,
  ProbeDefinition,
  ProbeInstance,
  WorkbenchConfig,
  DataSemantics,
} from "./generated";
import type { WorkspaceDocument } from "./layout";
import { useSnapshot } from "./evidence";
import { wb } from "./WorkbenchClient";
import { ArtifactView } from "./ArtifactView";
import { OperationView } from "../OperationView";
import type { ResearchState } from "../state";
import { ParameterForm } from "./ParameterForm";
export const ProbeWorkspace = memo(function ProbeWorkspace({
  document,
  state,
  outputVersion,
  onSelectVersion,
  onEvaluate,
  config,
  definitions,
  onConfig,
  onSave,
  onOpenPresenter,
}: {
  document: WorkspaceDocument;
  state: ResearchState;
  outputVersion: string;
  onSelectVersion: (s: SnapshotRef, pinned?: boolean) => void;
  onEvaluate: (s: SnapshotRef) => void;
  config?: WorkbenchConfig;
  definitions: ProbeDefinition[];
  onConfig: (c: WorkbenchConfig) => void;
  onSave: () => Promise<unknown>;
  onOpenPresenter: (s: SnapshotRef, id: string) => void;
}) {
  const { snapshot, error } = useSnapshot(document.reference.snapshot_id);
  const [history, setHistory] = useState<SnapshotRef[]>([]),
    [outputs, setOutputs] = useState<ProbeOutput[]>([]),
    [presenters, setPresenters] = useState<ProbeInstance[]>([]),
    [historyOpen, setHistoryOpen] = useState(false),
    [mode, setMode] = useState(document.reference.instance_id ?? ""),
    [settings, setSettings] = useState(false),
    [semantics, setSemantics] = useState<DataSemantics | null>(null),
    [semanticEdit, setSemanticEdit] = useState<DataSemantics>(),
    [notice, setNotice] = useState("");
  useEffect(() => {
    const abort = new AbortController();
    if (snapshot) {
      void Promise.all([
        client.history(
          snapshot.run_id,
          snapshot.binding_id,
          undefined,
          abort.signal,
        ),
        wb.outputs({ snapshot_id: snapshot.id }, abort.signal),
        wb.presenters(snapshot.id, abort.signal),
        wb.semantics(snapshot.id, abort.signal),
      ])
        .then(([h, o, p, s]) => {
          if (!abort.signal.aborted) {
            setHistory(h);
            setOutputs(o);
            setPresenters(p);
            setSemantics(s);
          }
        })
        .catch((e) => {
          if (!abort.signal.aborted) setNotice(e.message);
        });
    }
    return () => abort.abort();
  }, [snapshot?.id, outputVersion, config?.revision]);
  if (error)
    return (
      <div className="wb-empty" role="alert">
        {error}
      </div>
    );
  if (!snapshot) return <div className="wb-empty">读取此版本数据…</div>;
  const effective = presenters
    .filter((p) => {
      const live = config?.probes.find((i) => i.id === p.id);
      return (
        live &&
        live.enabled !== false &&
        live.overrides[snapshot.logical_key ?? ""]?.enabled !== false
      );
    })
    .map((p) => {
      const live = config!.probes.find((i) => i.id === p.id)!;
      return {
        ...p,
        parameters: {
          ...live.parameters,
          ...live.overrides[snapshot.logical_key ?? ""]?.parameters,
        },
      };
    });
  const instance =
      effective.find((p) => p.id === mode) ??
      (!document.reference.instance_id ? effective[0] : undefined),
    definition = definitions.find((d) => d.id === instance?.definition_id);
  const plugin = renderers.resolve(snapshot.descriptor),
    renderer =
      definition?.renderer === "auto"
        ? plugin
          ? "plugin"
          : snapshot.sample.columns
            ? "table"
            : snapshot.descriptor.shape
              ? "matrix"
              : "raw"
        : definition?.renderer;
  const artifacts = outputs.filter(
    (o) =>
      o.instance_id === instance?.id &&
      o.artifact_id &&
      o.status === "ready" &&
      JSON.stringify(o.data.parameters ?? {}) ===
        JSON.stringify(instance?.parameters ?? {}),
  );
  const updateParameters = (parameters: Record<string, unknown>) => {
    if (!config || !instance) return;
    const key = snapshot.logical_key ?? snapshot.binding_id;
    onConfig({
      ...config,
      probes: config.probes.map((p) =>
        p.id === instance.id
          ? {
              ...p,
              overrides: {
                ...p.overrides,
                [key]: {
                  enabled: p.overrides[key]?.enabled ?? null,
                  parameters,
                },
              },
            }
          : p,
      ),
    });
  };
  const localDisable = () => {
    if (!config || !instance) return;
    const key = snapshot.logical_key ?? snapshot.binding_id;
    onConfig({
      ...config,
      probes: config.probes.map((p) =>
        p.id === instance.id
          ? {
              ...p,
              overrides: {
                ...p.overrides,
                [key]: { enabled: false, parameters: {} },
              },
            }
          : p,
      ),
    });
  };
  const restoreLocal = () => {
    if (!config) return;
    const key = snapshot.logical_key ?? snapshot.binding_id;
    onConfig({
      ...config,
      probes: config.probes.map((p) => {
        const overrides = { ...p.overrides };
        delete overrides[key];
        return { ...p, overrides };
      }),
    });
  };
  const selectedSemantic = semantics?.accepted ? semantics : null;
  return (
    <div className="wb-data-pane">
      <div className="wb-view-toolbar">
        <strong data-testid="matrix-definition">
          <span data-testid="current-variable">{snapshot.name}</span>
          <small>
            {" "}
            v{snapshot.version} ·{" "}
            {snapshot.descriptor.dtype ?? snapshot.descriptor.kind} ·{" "}
            {snapshot.descriptor.shape?.join(" × ")}
          </small>
        </strong>
        <select
          aria-label="数据呈现探针"
          value={instance?.id ?? ""}
          onChange={(e) => setMode(e.target.value)}
        >
          <option value="">选择呈现探针</option>
          {effective.map((p) => (
            <option value={p.id} key={p.id}>
              {definitions.find((d) => d.id === p.definition_id)?.label ??
                p.definition_id}
            </option>
          ))}
        </select>
        <button
          aria-label="查看变量历史"
          aria-expanded={historyOpen}
          onClick={() => setHistoryOpen(!historyOpen)}
        >
          版本
        </button>
        <button onClick={() => setSettings(!settings)}>呈现设置</button>
        <button onClick={() => onEvaluate(snapshot)}>执行探针</button>
      </div>
      <div className="data-metadata">
        <span title={snapshot.source?.path}>
          {snapshot.source?.path.split(/[\\/]/).at(-1) ?? "派生数据"}
          {snapshot.source?.line ? " · L" + snapshot.source.line : ""}
        </span>
        <span>
          {instance?.origin === "project_default"
            ? "继承项目默认"
            : instance
              ? "局部绑定"
              : "无呈现绑定"}
        </span>
        {instance && (
          <button onClick={() => onOpenPresenter(snapshot, instance.id)}>
            固定此探针视图
          </button>
        )}
      </div>
      {historyOpen && (
        <div className="wb-version-strip">
          {history.map((v) => (
            <button
              key={v.id}
              aria-label={"版本 " + v.version}
              aria-pressed={v.id === snapshot.id}
              onClick={() => onSelectVersion(v)}
            >
              v{v.version}
            </button>
          ))}
          <button onClick={() => onSelectVersion(snapshot, true)}>
            并排固定此版本
          </button>
        </div>
      )}
      {settings && (
        <div className="data-presentation-settings">
          {instance && definition && (
            <>
              <ParameterForm
                schema={definition.parameter_schema}
                value={instance.parameters}
                onChange={updateParameters}
              />
              <button onClick={localDisable}>对此对象停用</button>
            </>
          )}
          <button onClick={restoreLocal}>恢复项目继承</button>
          <button
            onClick={() => void onSave().catch((e) => setNotice(e.message))}
          >
            保存呈现配置
          </button>
          <details
            onToggle={(e) => {
              if (e.currentTarget.open && !semanticEdit)
                setSemanticEdit(
                  semantics ?? {
                    protocol_version: 3,
                    logical_key: snapshot.logical_key ?? snapshot.binding_id,
                    kind: snapshot.sample.columns ? "table" : "matrix",
                    axes: (snapshot.descriptor.shape ?? []).map(() => ({
                      label: "",
                      meaning: "",
                      unit: "",
                      coordinates: [],
                      labels: [],
                      origin: "user",
                    })),
                    columns: ((snapshot.sample.columns ?? []) as unknown[]).map(
                      (c) => ({
                        key: String(c),
                        label: "",
                        meaning: "",
                        unit: "",
                        format: "",
                        missing: "—",
                        origin: "user" as const,
                      }),
                    ),
                    element_meaning: "",
                    unit: "",
                    mappings: {},
                    origin: "user",
                    revision: 0,
                    accepted: true,
                  },
                );
            }}
          >
            <summary>坐标与数据语义</summary>
            {semanticEdit && (
              <div className="wb-form compact">
                {semanticEdit.axes.map((axis, i) => (
                  <fieldset key={i}>
                    <legend>轴 {i}</legend>
                    <label>
                      名称
                      <input
                        value={axis.label}
                        onChange={(e) =>
                          setSemanticEdit({
                            ...semanticEdit,
                            axes: semanticEdit.axes.map((a, j) =>
                              j === i ? { ...a, label: e.target.value } : a,
                            ),
                          })
                        }
                      />
                    </label>
                    <label>
                      坐标
                      <input
                        aria-label={"轴 " + i + " 坐标"}
                        value={axis.coordinates.join(",")}
                        onChange={(e) =>
                          setSemanticEdit({
                            ...semanticEdit,
                            axes: semanticEdit.axes.map((a, j) =>
                              j === i
                                ? {
                                    ...a,
                                    coordinates: e.target.value
                                      ? e.target.value
                                          .split(",")
                                          .map((v) => v.trim())
                                      : [],
                                  }
                                : a,
                            ),
                          })
                        }
                      />
                    </label>
                    <label>
                      单位
                      <input
                        value={axis.unit}
                        onChange={(e) =>
                          setSemanticEdit({
                            ...semanticEdit,
                            axes: semanticEdit.axes.map((a, j) =>
                              j === i ? { ...a, unit: e.target.value } : a,
                            ),
                          })
                        }
                      />
                    </label>
                    <label>
                      元素含义
                      <input
                        value={axis.meaning}
                        onChange={(e) =>
                          setSemanticEdit({
                            ...semanticEdit,
                            axes: semanticEdit.axes.map((a, j) =>
                              j === i ? { ...a, meaning: e.target.value } : a,
                            ),
                          })
                        }
                      />
                    </label>
                  </fieldset>
                ))}
                {semanticEdit.columns.map((col, i) => (
                  <fieldset key={i}>
                    <legend>{col.key}</legend>
                    <label>
                      列名称
                      <input
                        value={col.label}
                        onChange={(e) =>
                          setSemanticEdit({
                            ...semanticEdit,
                            columns: semanticEdit.columns.map((c, j) =>
                              j === i ? { ...c, label: e.target.value } : c,
                            ),
                          })
                        }
                      />
                    </label>
                    <label>
                      列含义
                      <input
                        value={col.meaning}
                        onChange={(e) =>
                          setSemanticEdit({
                            ...semanticEdit,
                            columns: semanticEdit.columns.map((c, j) =>
                              j === i ? { ...c, meaning: e.target.value } : c,
                            ),
                          })
                        }
                      />
                    </label>
                    <label>
                      单位
                      <input
                        value={col.unit}
                        onChange={(e) =>
                          setSemanticEdit({
                            ...semanticEdit,
                            columns: semanticEdit.columns.map((c, j) =>
                              j === i ? { ...c, unit: e.target.value } : c,
                            ),
                          })
                        }
                      />
                    </label>
                  </fieldset>
                ))}
                <label>
                  元素定义
                  <input
                    value={semanticEdit.element_meaning}
                    onChange={(e) =>
                      setSemanticEdit({
                        ...semanticEdit,
                        element_meaning: e.target.value,
                      })
                    }
                  />
                </label>
                <button
                  onClick={() =>
                    void wb
                      .saveSemantics(snapshot.id, semanticEdit)
                      .then((s) => {
                        setSemantics(s);
                        setSemanticEdit(s);
                        setNotice("数据语义已保存");
                      })
                      .catch((e) => setNotice(e.message))
                  }
                >
                  保存数据语义
                </button>
              </div>
            )}
          </details>
        </div>
      )}
      <div className="wb-data-content">
        {!instance ? (
          <div className="wb-empty">没有有效呈现探针</div>
        ) : definition?.entrypoint ? (
          <pre className="wb-json">
            {JSON.stringify(
              outputs.find((o) => o.instance_id === instance.id)?.data ?? {
                status: "尚未执行此程序探针",
              },
              null,
              2,
            )}
          </pre>
        ) : definition?.tool_id ? (
          artifacts.length ? (
            <ArtifactView id={artifacts[0].artifact_id!} />
          ) : (
            <div className="wb-empty">尚未执行此绘图探针</div>
          )
        ) : renderer === "plugin" && plugin ? (
          <plugin.Component snapshot={snapshot} />
        ) : renderer === "matrix" && snapshot.descriptor.shape ? (
          <MatrixView
            snapshot={snapshot}
            parameters={instance.parameters}
            semantics={selectedSemantic}
          />
        ) : renderer === "table" ? (
          <TableView
            snapshot={snapshot}
            semantics={selectedSemantic}
            parameters={instance.parameters}
          />
        ) : renderer === "compare" ? (
          <div className="wb-empty">联合比较结果在任务与结果中打开</div>
        ) : renderer === "relationships" ? (
          <div className="wb-empty">在计算关系图查看关联</div>
        ) : (
          <pre className="wb-json" data-testid="raw-data">
            {snapshot.descriptor.kind === "scalar" &&
            Array.isArray(snapshot.sample.values)
              ? displayCell((snapshot.sample.values as unknown[][])[0]?.[0])
              : JSON.stringify(snapshot.sample, null, 2)}
          </pre>
        )}
      </div>
      {snapshot.run_id === state.runId &&
        snapshot.operation_id &&
        state.operations.has(snapshot.operation_id) && (
          <details className="wb-operation-details">
            <summary>计算定义与解释</summary>
            <OperationView
              operation={state.operations.get(snapshot.operation_id)}
              snapshots={state.snapshots}
              model={false}
            />
          </details>
        )}
      {instance && renderer !== "matrix" && (
        <details className="wb-operation-details">
          <summary>统计与采集</summary>
          <div className="wb-form compact">
            <small>
              {snapshot.fidelity} · {snapshot.truncation.join(" · ")}
            </small>
            <dl>
              {Object.entries(snapshot.statistics)
                .filter(
                  ([, v]) => typeof v === "number" || typeof v === "string",
                )
                .map(([k, v]) => (
                  <div key={k}>
                    <dt>{k}</dt>
                    <dd>{String(v)}</dd>
                  </div>
                ))}
            </dl>
            <details>
              <summary>采集详情</summary>
              <pre className="wb-json">
                {JSON.stringify(snapshot.coverage, null, 2)}
              </pre>
            </details>
          </div>
        </details>
      )}
      {notice && <span role="status">{notice}</span>}
      <div className="wb-evidence-bar">
        <span>
          {snapshot.fidelity} · {snapshot.descriptor.backend}
        </span>
        <span>
          {snapshot.redacted.length ? "已脱敏" : "已保存证据"} ·{" "}
          {snapshot.run_id.slice(0, 8)}
        </span>
      </div>
    </div>
  );
});
