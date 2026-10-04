import { memo, useEffect, useState } from "react";
import { client } from "../client";
import type { SnapshotRef } from "../generated";
import type {
  ProbeOutput,
  ProbeDefinition,
  WorkbenchConfig,
  DataSemantics,
  AnalysisDocument,
} from "./generated";
import type { WorkspaceDocument } from "./layout";
import { useSnapshot } from "./evidence";
import { wb } from "./WorkbenchClient";
import { OperationView } from "../OperationView";
import type { ResearchState } from "../state";
import { ParameterForm } from "./ParameterForm";
import { snapshotProbeTarget, targetOverrideError, targetOverrideKey, targetProbeEntries } from "./probe-configuration";
import { latestProbeOutputs } from "./probe-results";
import { ProbePresentation } from "./ProbePresentation";
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
  runAnalysis,
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
  runAnalysis?: { runId: string; analysis: AnalysisDocument };
}) {
  const { snapshot, error } = useSnapshot(document.reference.snapshot_id);
  const [scope, setScope] = useState<{ runId: string; analysis: AnalysisDocument }>();
  const providedScope = snapshot && runAnalysis?.runId === snapshot.run_id ? runAnalysis : undefined;
  const [history, setHistory] = useState<SnapshotRef[]>([]),
    [outputs, setOutputs] = useState<ProbeOutput[]>([]),
    [historyOpen, setHistoryOpen] = useState(false),
    [mode, setMode] = useState(document.reference.instance_id ?? "all"),
    [closedViews, setClosedViews] = useState(new Set<string>()),
    [settings, setSettings] = useState(false),
    [semantics, setSemantics] = useState<DataSemantics | null>(null),
    [semanticEdit, setSemanticEdit] = useState<DataSemantics>(),
    [notice, setNotice] = useState("");
  useEffect(() => {
    if (!snapshot || providedScope || scope?.runId === snapshot.run_id) return;
    const abort = new AbortController();
    void wb.runAnalysis(snapshot.run_id, abort.signal)
      .then(analysis => { if (!abort.signal.aborted) setScope({ runId: snapshot.run_id, analysis }); })
      .catch(error => { if (!abort.signal.aborted) setNotice(error.message); });
    return () => abort.abort();
  }, [snapshot?.run_id, providedScope?.analysis.id]);
  useEffect(() => {
    const abort = new AbortController();
    setSemantics(null);
    if (snapshot) {
      setNotice("");
      void Promise.all([
        wb.outputs({ snapshot_id: snapshot.id }, abort.signal),
        wb.semantics(snapshot.id, abort.signal),
      ]).then(([o, semantics]) => {
        if (!abort.signal.aborted) { setOutputs(o); setSemantics(semantics); }
      }).catch(e => { if (!abort.signal.aborted) setNotice(e.message); });
    }
    return () => abort.abort();
  }, [snapshot?.id, outputVersion, config?.revision]);
  useEffect(() => {
    if (!snapshot || !historyOpen) return;
    const abort = new AbortController();
    void client.history(snapshot.run_id, snapshot.binding_id, undefined, abort.signal)
      .then(h => { if (!abort.signal.aborted) setHistory(h); })
      .catch(e => { if (!abort.signal.aborted) setNotice(e.message); });
    return () => abort.abort();
  }, [snapshot?.id, historyOpen]);
  if (error)
    return (
      <div className="wb-empty" role="alert">
        {error}
      </div>
    );
  if (!snapshot) return <div className="wb-empty">读取此版本数据…</div>;
  const analysis = providedScope?.analysis ?? (scope?.runId === snapshot.run_id ? scope.analysis : undefined);
  if (!analysis) return <div className="wb-empty" role={notice ? "alert" : undefined}>{notice || "读取此版本的作用域…"}</div>;
  const target = snapshotProbeTarget(snapshot, analysis);
  const overrideKey = targetOverrideKey(target, analysis);
  const overrideNotice = config?.probes.filter((probe) => probe.enabled)
    .map((probe) => targetOverrideError(probe, target, analysis)).find(Boolean);
  const entries = targetProbeEntries(config?.probes ?? [], definitions, target, analysis).filter(entry => entry.enabled);
  const enabled = entries.map(entry => ({ ...entry.probe, parameters: entry.parameters }));
  const effective = enabled.filter(p => definitions.some(d => d.id === p.definition_id && d.capability === "view"));
  const instance = effective.find(p => p.id === mode) ?? effective[0];
  const activeMode = mode === "all" || effective.some(p => p.id === mode) ? mode : "all";
  const definition = definitions.find(d => d.id === instance?.definition_id);
  const shown = activeMode === "all" ? effective : effective.filter(p => p.id === activeMode);
  const currentOutputs = latestProbeOutputs(outputs, snapshot, enabled);
  const checks = enabled.filter(p => definitions.find(d => d.id === p.definition_id)?.capability !== "view");
  const updateParameters = (parameters: Record<string, unknown>) => {
    if (!config || !instance || !overrideKey) return;
    const key = overrideKey;
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
    if (!config || !instance || !overrideKey) return;
    const key = overrideKey;
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
    if (!config || !overrideKey) return;
    const key = overrideKey;
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
          value={activeMode}
          onChange={(e) => setMode(e.target.value)}
        >
          <option value="all">全部呈现探针 ({effective.length})</option>
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
        <button disabled={!instance} onClick={() => setSettings(!settings)}>呈现设置</button>
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
        {!shown.length && <div className="wb-empty">没有有效呈现探针</div>}
        {shown.map(p => {
          const d = definitions.find(item => item.id === p.definition_id), result = currentOutputs.get(p.id), open = !closedViews.has(p.id);
          return <details className="probe-presentation" data-testid="probe-view" data-instance-id={p.id} key={p.id} open={open} onToggle={e => {
            const isOpen = e.currentTarget.open;
            setClosedViews(old => { if (old.has(p.id) === !isOpen) return old; const next = new Set(old); isOpen ? next.delete(p.id) : next.add(p.id); return next; });
          }}>
            <summary><strong>{d?.label ?? p.definition_id}</strong><small>{p.origin === "project_default" ? "默认" : "局部"}</small>
              {result && <span className={"wb-kind " + result.status}>{result.status}</span>}
            </summary>
            {open && <ProbePresentation snapshot={snapshot} instance={p} definition={d} output={result} semantics={selectedSemantic} />}
          </details>;
        })}
        {checks.length > 0 && <div className="data-probe-results">{checks.map(p => {
          const d = definitions.find(item => item.id === p.definition_id), result = currentOutputs.get(p.id);
          return <details className={"data-probe-result " + (result?.status ?? "pending")} data-testid="data-probe-result" key={p.id}>
            <summary><strong>{d?.label ?? p.definition_id}</strong><span className={"wb-kind " + (result?.status ?? "pending")}>{result?.status ?? "待执行"}</span></summary>
            {result ? <><p>{result.message}</p><pre className="wb-json">{JSON.stringify(result.data, null, 2)}</pre></> : <p>执行探针后显示结果</p>}
          </details>;
        })}</div>}
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
      {instance && (
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
      {(overrideNotice || notice) && <span role={overrideNotice ? "alert" : "status"}>{overrideNotice || notice}</span>}
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
