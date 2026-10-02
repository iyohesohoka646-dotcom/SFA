import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { ModelSettings } from "../settings/ModelSettings";
import { client, downloadReport } from "./client";
import { ObjectBrowser } from "./workspace/ObjectBrowser";
import type { TargetRef } from "./workspace/generated";
import type { SnapshotRef, SourceRef } from "./generated";
import type { ProbeOutput } from "./workspace/generated";
import type { DocumentKind, WorkspaceDocument } from "./workspace/layout";
import { groups } from "./workspace/layout";
import { LayoutControls, WorkspaceShell } from "./workspace/WorkspaceShell";
import { useWorkbench } from "./workspace/controller";
import { Icon } from "./workspace/icons";
import { wb, type Preferences } from "./workspace/WorkbenchClient";
import { SourceDocument } from "./workspace/SourceDocument";
import { ProbeWorkspace } from "./workspace/ProbeWorkspace";
import { WorkbenchSettings } from "./workspace/WorkbenchSettings";
import { ComparisonView } from "./workspace/ComparisonView";
import { ProbeInspector } from "./workspace/ProbeInspector";
import { TaskPanel } from "./workspace/TaskPanel";
import { ResultView } from "./workspace/ResultView";
import "./research.css";
import "./workspace/workbench.css";
const RelationGraph = lazy(() =>
  import("./workspace/RelationGraph").then((m) => ({
    default: m.RelationGraph,
  })),
);
const ProbeLibrary = lazy(() =>
  import("./workspace/ProbeLibrary").then((m) => ({ default: m.ProbeLibrary })),
);
const IntelligencePanel = lazy(() =>
  import("./workspace/IntelligencePanel").then((m) => ({
    default: m.IntelligencePanel,
  })),
);
const ContextView = lazy(() =>
  import("./workspace/IntelligencePanel").then((m) => ({
    default: m.ContextView,
  })),
);
const ChangeReview = lazy(() =>
  import("./workspace/ChangeReview").then((m) => ({ default: m.ChangeReview })),
);
const CommandPane = lazy(() =>
  import("./workspace/CommandPane").then((m) => ({ default: m.CommandPane })),
);
const views: { kind: DocumentKind; label: string }[] = [
  { kind: "graph", label: "计算关系图" },
  { kind: "probes", label: "探针台" },
  { kind: "tools", label: "探针库" },
  { kind: "intelligence", label: "智能助手" },
  { kind: "changes", label: "代码审查" },
  { kind: "terminal", label: "终端" },
];

export default function ResearchWorkbench() {
  const c = useWorkbench(),
    [modelsVisible, setModelsVisible] = useState(false),
    [sourceOptions, setSourceOptions] = useState(false),
    [requestedProbe, setRequestedProbe] = useState(""),
    [runMode, setRunMode] = useState<"compute" | "probes" | "replot">(
      "compute",
    );
  useEffect(() => {
    const open = () => c.open("terminal", {}, "终端", true, "main");
    window.addEventListener("cdaf-open-terminal", open);
    return () => window.removeEventListener("cdaf-open-terminal", open);
  }, [c.open]);
  useEffect(() => {
    if (!c.runId) setRunMode("compute");
  }, [c.runId]);
  const [compactWindow, setCompactWindow] = useState(innerWidth < 650),
    autoFocus = useRef(false);
  useEffect(() => {
    const media = matchMedia("(max-width:650px)"),
      change = () => setCompactWindow(media.matches);
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);
  const [viewMenu, setViewMenu] = useState(false),
    [explorer, setExplorer] = useState(true);
  useEffect(() => {
    if (!c.ready) return;
    if (compactWindow) {
      setExplorer(false);
      autoFocus.current = true;
      if (c.layout.focused !== c.layout.activeGroup)
        c.dispatch({ type: "focus", group: c.layout.activeGroup });
    } else if (autoFocus.current) {
      autoFocus.current = false;
      c.dispatch({ type: "focus", group: null });
      setExplorer(true);
    }
  }, [compactWindow, c.ready, c.layout.activeGroup]);
  const width = c.layout.explorerWidth;
  const setWidth = (value: number) =>
    c.dispatch({ type: "explorer-width", width: value });
  const drag = useRef<{ x: number; width: number } | null>(null),
    [theme, setTheme] = useState(
      document.documentElement.dataset.theme ?? "light",
    );
  const error = c.setNotice;
  const preferencesTouched = useRef(new Set<string>());
  const applyPreferences = (p: Preferences, group: string, initial = false) => {
    if (!initial) preferencesTouched.current.add(group);
    if (group === "workspace") {
      const accept = (field: string) =>
        !initial || p.sources["workspace." + field] !== "default";
      if (accept("theme")) {
        const next = String(p.values.workspace.theme);
        setTheme(next);
        document.documentElement.dataset.theme = next;
        localStorage.setItem("cdaf-theme", next);
      }
      if (accept("explorer_width"))
        c.dispatch({
          type: "explorer-width",
          width: Number(p.values.workspace.explorer_width),
        });
      if (accept("compact"))
        document.documentElement.dataset.compact = String(
          p.values.workspace.compact,
        );
    }
    if (group === "graph") {
      localStorage.setItem(
        "cdaf-graph-settings",
        JSON.stringify(p.values.graph),
      );
      window.dispatchEvent(new Event("cdaf-preferences-changed"));
    }
    if (!initial && c.config && group === "capture")
      c.editConfig({
        ...c.config,
        capture: p.values.capture.level as typeof c.config.capture,
      });
    if (!initial && c.config && group === "intelligence")
      c.editConfig({
        ...c.config,
        harness: c.config.harness.map((h) => ({
          ...h,
          include_samples: Boolean(p.values.intelligence.include_samples),
          input_tokens: Number(p.values.intelligence.input_tokens),
        })),
      });
  };
  useEffect(() => {
    if (!c.info || !c.ready) return;
    let live = true;
    void wb
      .preferences()
      .then((p) => {
        if (!live) return;
        for (const group of ["workspace", "graph"])
          if (!preferencesTouched.current.has(group))
            applyPreferences(p, group, true);
      })
      .catch((e) => {
        if (live) error(e.message);
      });
    return () => {
      live = false;
    };
  }, [c.info?.root, c.ready]);
  const refreshKey = c.tasks
    .filter((t) => !["running", "queued"].includes(t.status))
    .map((t) => t.id)
    .join("|");
  const showView = (kind: DocumentKind) => {
    setViewMenu(false);
    if (kind === "graph")
      c.open(
        "graph",
        c.runId && c.values.length
          ? { run_id: c.runId }
          : { analysis_id: c.analysis?.id },
        "计算关系图",
      );
    else
      c.open(
        kind,
        kind === "source" ? { analysis_id: c.analysis?.id } : {},
        undefined,
        kind === "probes" || kind === "tasks",
        kind === "probes" ? "detail" : undefined,
      );
  };
  const selectVersion = useCallback(
    (value: SnapshotRef, pinned = false) => {
      if (!pinned) return c.selectSnapshot(value);
      const id = "data:" + value.id;
      const currentGroup = groups(c.layout.tree).find((g) =>
        g.tabs.includes(id),
      )?.id;
      const group =
        groups(c.layout.tree).find(
          (g) =>
            g.id !== currentGroup && g.id !== "bottom" && g.id !== "source",
        )?.id ?? "main";
      if (c.layout.documents[id]) {
        c.dispatch({ type: "pin", documentId: id, pinned: true });
        c.dispatch({ type: "move", documentId: id, group });
      } else
        c.open(
          "data",
          { snapshot_id: value.id, run_id: value.run_id },
          `${value.name} · v${value.version}`,
          true,
          group,
        );
      if (!c.layout.locked)
        c.dispatch({ type: "resize", id: "detail-width", ratio: 0.5 });
    },
    [c.selectSnapshot, c.open, c.layout],
  );
  const selectObject = (id: string) => {
    const obj = c.analysis?.objects.find((o) => o.id === id);
    if (obj)
      c.chooseTargets({
        targets: [
          {
            kind: obj.kind === "function" ? "function" : "data",
            logical_key: obj.logical_key,
            object_id: id,
            block_id: obj.block_id,
            analysis_id: c.analysis!.id,
          } as TargetRef,
        ],
        anchor: null,
      });
  };
  const openTarget = (t: TargetRef) => {
    if (t.snapshot_id)
      void client
        .snapshot(t.snapshot_id)
        .then(c.selectSnapshot)
        .catch((e) => error(e.message));
  };
  const sourceTarget = (t: TargetRef) => {
    c.setSelectedObject(t.object_id ?? "");
    if (t.analysis_id)
      c.open(
        "source",
        { analysis_id: t.analysis_id },
        undefined,
        false,
        "source",
      );
    else if (t.run_id)
      c.open("source", { run_id: t.run_id }, undefined, false, "source");
  };
  const selection: SourceRef | null = c.object
    ? {
        path: c.object.path,
        qualname: c.object.qualname,
        line: c.object.line,
        end_line: c.object.end_line,
        column: c.object.column,
        end_column: c.object.end_column,
        digest: c.object.source_digest,
        code: c.object.code,
      }
    : (c.focusSnapshot?.source ?? null);
  const evaluateSnapshot = (snapshot: SnapshotRef) => {
    if (!c.config) return;
    void c
      .saveConfig()
      .then(() => wb.evaluate(snapshot.run_id, [snapshot.id]))
      .then(c.track)
      .catch((e) => error(e.message));
  };
  const output = (value: ProbeOutput) => {
    if (value.definition_id === "view.compare") {
      c.open("comparison", { output_id: value.id }, "并排比较", true);
      return;
    }
    if (typeof value.data.context_id === "string")
      c.open("context", { context_id: value.data.context_id });
    else c.open("result", { output_id: value.id }, value.definition_id);
  };
  const accepted = (path: string) => {
    c.setScript(path);
    void c.imported(path).catch((e) => error(e.message));
  };
  const render = (doc: WorkspaceDocument) => {
    switch (doc.kind) {
      case "settings":
        return (
          <WorkbenchSettings
            onModels={() => setModelsVisible(true)}
            onTools={() => showView("tools")}
            onError={error}
            onApplied={applyPreferences}
          />
        );
      case "source":
        return (
          <SourceDocument
            key={doc.id}
            document={doc}
            analysis={c.analysis}
            selection={selection}
            onSelect={selectObject}
            onError={error}
          />
        );
      case "data":
        return (
          <ProbeWorkspace
            key={doc.id}
            document={doc}
            state={c.state}
            outputVersion={refreshKey}
            onSelectVersion={selectVersion}
            onEvaluate={evaluateSnapshot}
            config={c.config}
            definitions={c.definitions}
            onConfig={c.editConfig}
            onSave={c.saveConfig}
            onOpenPresenter={(s, id) =>
              c.open(
                "data",
                { snapshot_id: s.id, run_id: s.run_id, instance_id: id },
                s.name +
                  " · " +
                  (c.definitions.find(
                    (d) =>
                      d.id ===
                      c.config?.probes.find((p) => p.id === id)?.definition_id,
                  )?.label ?? id),
                true,
              )
            }
          />
        );
      case "graph":
        return (
          <RelationGraph
            key={doc.id}
            document={doc}
            state={c.state}
            analysis={c.analysis}
            selection={c.selection}
            onSelection={c.chooseTargets}
            scope={c.blockScope}
            onEnter={c.enterScope}
            onOpen={openTarget}
            onSource={sourceTarget}
            onBind={() => showView("probes")}
            onError={error}
          />
        );
      case "comparison":
        return (
          <ComparisonView id={doc.reference.output_id!} config={c.config} />
        );
      case "result":
        return (
          <ResultView
            id={doc.reference.output_id!}
            onData={(id) =>
              void client
                .snapshot(id)
                .then(c.selectSnapshot)
                .catch((e) => error(e.message))
            }
            onProposal={(p) => c.open("changes", { proposal_id: p.id })}
            onError={error}
          />
        );
      case "probes":
        return c.config ? (
          <ProbeInspector
            selection={c.selection}
            blockScope={c.blockScope}
            requested={requestedProbe}
            config={c.config}
            definitions={c.definitions}
            selected={c.focusSnapshot}
            analysis={c.viewAnalysis}
            outputs={c.outputs}
            onChange={c.editConfig}
            onSave={c.saveConfig}
            onError={error}
            onRecorded={c.recordOutput}
          />
        ) : null;
      case "tools":
        return (
          <ProbeLibrary
            definitions={c.definitions}
            interpreter={c.interpreter}
            tasks={c.tasks}
            onTask={c.track}
            onError={error}
            onRefresh={c.refreshDefinitions}
            onBind={(id) => {
              setRequestedProbe(id);
              showView("probes");
            }}
          />
        );
      case "intelligence":
        return c.config ? (
          <IntelligencePanel
            analysis={c.analysis}
            object={c.object}
            snapshot={c.focusSnapshot}
            config={c.config}
            onChange={c.editConfig}
            onSave={c.saveConfig}
            onTask={c.track}
            onContext={(id) => c.open("context", { context_id: id })}
            onModels={() => setModelsVisible(true)}
            onError={error}
          />
        ) : null;
      case "context":
        return <ContextView id={doc.reference.context_id!} onError={error} />;
      case "changes":
        return (
          <ChangeReview
            analysis={c.analysis}
            object={c.object}
            proposalId={doc.reference.proposal_id}
            tasks={c.tasks}
            outputs={c.outputs}
            onAccepted={accepted}
            onError={error}
          />
        );
      case "tasks":
        return (
          <TaskPanel
            scope={c.blockScope}
            analysis={c.viewAnalysis}
            tasks={c.tasks}
            outputs={c.outputs}
            state={c.state}
            onSnapshot={(id) =>
              void client
                .snapshot(id)
                .then(c.selectSnapshot)
                .catch((e) => error(e.message))
            }
            onContext={(id) => c.open("context", { context_id: id })}
            onChange={(id) => c.open("changes", { proposal_id: id })}
            onOutput={output}
            onError={error}
          />
        );
      case "terminal":
        return <CommandPane />;
    }
  };
  useEffect(() => {
    const shortcut = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        void c.run();
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setViewMenu((v) => !v);
      }
    };
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, [c.run]);
  const running = c.tasks.filter((t) =>
    ["running", "queued"].includes(t.status),
  );
  return (
    <main className="research-app scientific-workspace" data-theme={theme}>
      <header className="wb-menubar">
        <h1>Scientific Dataflow Inspector</h1>
        <span className="wb-project-name" title={c.info?.root}>
          {c.info?.root.split(/[\\/]/).at(-1)}
        </span>
        <div className="ri-header-actions">
          <button onClick={() => showView("settings")}>
            <Icon name="settings" />
            设置
          </button>
          <button onClick={() => setModelsVisible(true)}>模型设置</button>
          <button
            aria-label="切换主题"
            onClick={() => {
              preferencesTouched.current.add("workspace");
              const next = theme === "light" ? "dark" : "light";
              setTheme(next);
              document.documentElement.dataset.theme = next;
              localStorage.setItem("cdaf-theme", next);
            }}
          >
            ◐
          </button>
        </div>
      </header>
      <div className="wb-main-toolbar">
        <button
          aria-label="切换对象侧栏"
          aria-pressed={explorer}
          onClick={() => setExplorer(!explorer)}
        >
          <Icon name="source" />
        </button>
        <div className="wb-source-switch">
          <button
            aria-label="打开源码配置"
            onClick={() => setSourceOptions(!sourceOptions)}
            aria-expanded={sourceOptions}
          >
            <Icon name="source" />
            <span>{c.analysis?.path.split(/[\\/]/).at(-1) ?? "选择源码"}</span>
            <Icon name="chevron" size={12} />
          </button>
          {sourceOptions && (
            <div className="wb-source-popover wb-form">
              <label>
                源码路径
                <input
                  aria-label="分析脚本"
                  value={c.script}
                  onChange={(e) => c.setScript(e.target.value)}
                />
              </label>
              <label>
                示例
                <select
                  aria-label="示例选择"
                  value={
                    c.info?.examples.find((e) => e.script === c.script)?.id ??
                    ""
                  }
                  onChange={(e) =>
                    c.setScript(
                      c.info?.examples.find((v) => v.id === e.target.value)
                        ?.script ?? "",
                    )
                  }
                >
                  <option value="">自定义</option>
                  {c.info?.examples.map((e) => (
                    <option value={e.id} key={e.id}>
                      {e.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                解释器
                <input
                  aria-label="计算解释器"
                  value={c.interpreter}
                  onChange={(e) => c.setInterpreter(e.target.value)}
                />
              </label>
              {c.config && (
                <>
                  <label>
                    脚本参数 JSON
                    <input
                      aria-label="脚本参数 JSON"
                      defaultValue={JSON.stringify(c.config.arguments)}
                      onBlur={(e) => {
                        try {
                          const v = JSON.parse(e.target.value);
                          if (
                            !Array.isArray(v) ||
                            v.some((a) => typeof a !== "string")
                          )
                            throw new Error();
                          c.editConfig({ ...c.config!, arguments: v });
                        } catch {
                          error("脚本参数须为字符串数组");
                        }
                      }}
                    />
                  </label>
                  <label>
                    采集
                    <select
                      aria-label="采集模式"
                      value={c.config.capture}
                      onChange={(e) =>
                        c.editConfig({
                          ...c.config!,
                          capture: e.target.value as
                            | "metadata"
                            | "summary"
                            | "sample"
                            | "full",
                        })
                      }
                    >
                      <option value="metadata">元数据</option>
                      <option value="summary">摘要</option>
                      <option value="sample">有界样例</option>
                      <option value="full">完整数据</option>
                    </select>
                  </label>
                </>
              )}
            </div>
          )}
        </div>
        <button
          disabled={!c.script || c.loading.status === "running"}
          onClick={() => void c.parse()}
        >
          导入解析
        </button>
        <button
          className="wb-primary"
          disabled={!c.analysis || c.preparing.status === "running"}
          onClick={() => void c.run(runMode)}
        >
          <Icon name="run" />
          运行
        </button>
        <select
          aria-label="运行模式"
          value={runMode}
          onChange={(e) => setRunMode(e.target.value as typeof runMode)}
        >
          <option value="compute">计算与探针</option>
          <option value="probes" disabled={!c.runId}>
            仅执行探针
          </option>
          <option value="replot" disabled={!c.runId}>
            仅重绘
          </option>
        </select>
        <select
          aria-label="探针执行范围"
          value={c.probeRange}
          onChange={(e) =>
            c.setProbeRange(e.target.value as "project" | "block" | "selection")
          }
        >
          <option value="project">整个项目</option>
          <option value="block" disabled={!c.blockScope}>
            当前块
          </option>
          <option value="selection" disabled={!c.selection.targets.length}>
            当前选择 ({c.selection.targets.length})
          </option>
        </select>
        <select
          className="wb-run-select"
          aria-label="运行记录"
          value={c.runId}
          onChange={(e) => c.setRunId(e.target.value)}
        >
          <option value="">尚未运行</option>
          {c.runId && !c.runs.some((r) => r.id === c.runId) && (
            <option value={c.runId}>
              {c.runId.slice(0, 8)} · {c.state.status}
            </option>
          )}
          {c.runs.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name} · {r.status} · {r.started.slice(11, 19)}
            </option>
          ))}
        </select>
        <span className="wb-draft">
          {c.dirty ? "配置未保存" : c.analysis ? "已解析" : "待导入"}
        </span>
        <div className="wb-toolbar-right">
          <button
            disabled={!c.runId}
            onClick={() =>
              void downloadReport(c.runId).catch((e) => error(e.message))
            }
          >
            导出报告
          </button>
          <button
            onClick={() => setViewMenu(!viewMenu)}
            aria-expanded={viewMenu}
          >
            打开视图
          </button>
          {c.hasLayoutBackup && (
            <button
              onClick={() => {
                try {
                  c.recoverLayout();
                } catch (e) {
                  error((e as Error).message);
                }
              }}
            >
              恢复旧布局
            </button>
          )}
          <LayoutControls layout={c.layout} dispatch={c.dispatch} />
        </div>
        {viewMenu && (
          <div className="wb-view-menu workspace-menu">
            {views.map((v) => (
              <button key={v.kind} onClick={() => showView(v.kind)}>
                <Icon name={v.kind} />
                {v.label}
              </button>
            ))}
            <button onClick={() => showView("source")}>源码</button>
            <button
              onClick={() => {
                if (c.focusSnapshot) c.selectSnapshot(c.focusSnapshot);
                setViewMenu(false);
              }}
            >
              数据探针
            </button>
          </div>
        )}
      </div>
      <div className="wb-body">
        <nav className="wb-activity" aria-label="工作区">
          <button aria-label="源码" onClick={() => showView("source")}>
            <Icon name="source" />
            <span>源码</span>
          </button>
          {views.map((v) => (
            <button
              key={v.kind}
              aria-label={v.label}
              title={v.label}
              onClick={() => showView(v.kind)}
            >
              <Icon name={v.kind} />
              <span>
                {v.kind === "graph"
                  ? "关系"
                  : v.kind === "intelligence"
                    ? "智能"
                    : v.kind === "changes"
                      ? "审查"
                      : v.kind === "terminal"
                        ? "命令"
                        : v.label}
              </span>
            </button>
          ))}
        </nav>
        {explorer && (
          <>
            <aside className="wb-explorer" style={{ width }}>
              <ObjectBrowser
                outputs={c.outputs}
                analysis={c.viewAnalysis}
                values={c.values}
                selection={c.selection}
                onSelection={c.chooseTargets}
                scope={c.blockScope}
                onEnter={c.enterScope}
                onOpen={(row) =>
                  row.snapshot
                    ? c.selectSnapshot(row.snapshot)
                    : sourceTarget(row.target)
                }
                onSource={(row) => sourceTarget(row.target)}
                onBind={() => showView("probes")}
              />
            </aside>
            <div
              role="separator"
              aria-label="调整对象侧栏"
              aria-orientation="vertical"
              aria-disabled={c.layout.locked}
              tabIndex={c.layout.locked ? -1 : 0}
              className="workspace-separator horizontal"
              onPointerDown={(e) => {
                if (c.layout.locked) return;
                drag.current = { x: e.clientX, width };
                e.currentTarget.setPointerCapture(e.pointerId);
              }}
              onPointerMove={(e) => {
                if (drag.current && !c.layout.locked) {
                  const next = Math.min(
                    360,
                    Math.max(
                      170,
                      drag.current.width + e.clientX - drag.current.x,
                    ),
                  );
                  setWidth(next);
                  localStorage.setItem("cdaf-explorer-width", String(next));
                }
              }}
              onPointerUp={() => {
                drag.current = null;
              }}
              onLostPointerCapture={() => {
                drag.current = null;
              }}
              onKeyDown={(e) => {
                if (
                  !c.layout.locked &&
                  (e.key === "ArrowLeft" || e.key === "ArrowRight")
                ) {
                  e.preventDefault();
                  setWidth(
                    Math.max(
                      170,
                      Math.min(
                        360,
                        width + (e.key === "ArrowRight" ? 15 : -15),
                      ),
                    ),
                  );
                }
              }}
            />
          </>
        )}
        <Suspense fallback={<div className="wb-empty">打开视图…</div>}>
          {c.info && c.ready ? (
            <WorkspaceShell
              key={c.info.root}
              layout={c.layout}
              dispatch={c.dispatch}
              render={render}
              onOpen={() => setViewMenu(true)}
            />
          ) : (
            <div className="wb-empty">加载工作区…</div>
          )}
        </Suspense>
      </div>
      <div className="wb-statusbar" role="status">
        <span
          className={"wb-status-dot " + (running.length ? "running" : "")}
        />
        <span>
          {running.length ? running.length + " 个任务运行中" : "本地工作区"}
        </span>
        <span title={c.notice}>
          {c.loading.error || c.preparing.error || c.notice}
        </span>
        <span className="wb-status-right">
          <span data-testid="run-status">{c.state.status}</span> ·{" "}
          {c.values.length} 个数据对象
        </span>
      </div>
      <ModelSettings
        visible={modelsVisible}
        onClose={() => setModelsVisible(false)}
      />
    </main>
  );
}
