import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
} from "react";
import { ModelSettings } from "../../settings/ModelSettings";
import {
  createResearchServices,
  ResearchServicesProvider,
  useResearchServices,
} from "../workspace/ResearchServices";
import { WorkspaceShell, LayoutControls } from "../workspace/WorkspaceShell";
import {
  groups,
  type DocumentKind,
  type WorkspaceDocument,
} from "../workspace/layout";
import { useWorkspace } from "../workspace/useWorkspace";
import { ProbeInspector } from "../workspace/ProbeInspector";
import { ProbeLibrary } from "../workspace/ProbeLibrary";
import { TaskPanel } from "../workspace/TaskPanel";
import { CommandPane } from "../workspace/CommandPane";
import { WorkbenchSettings } from "../workspace/WorkbenchSettings";
import { ResultView } from "../workspace/ResultView";
import { ComparisonView } from "../workspace/ComparisonView";
import { ContextView } from "../workspace/IntelligencePanel";
import { snapshotProbeTarget } from "../workspace/probe-configuration";
import type {
  AnalysisDocument,
  ProbeOutput,
  TargetRef,
} from "../workspace/generated";
import type { SnapshotRef } from "../generated";
import { ProjectHost, type ProjectSession } from "./ProjectHost";
import ProjectBrowser from "./ProjectBrowser";
import ProjectCanvas, { type ProjectCanvasView } from "./ProjectCanvas";
import { ProjectRunConfigurations } from "./ProjectRunConfigurations";
import { ProjectIntelligencePanel } from "./ProjectIntelligencePanel";
import { ProjectChangeReview } from "./ProjectChangeReview";
import { ProjectSourceDocument, ProjectDataDocument } from "./ProjectDocuments";
import { useProjectWorkbench } from "./useProjectWorkbench";
import { targetSelectionKey } from "./identity";
import type { ProjectGraphSlice } from "./generated";
import "./project-shell.css";

const names: Partial<Record<DocumentKind, string>> = {
  graph: "计算关系图",
  probes: "探针台",
  tools: "探针库",
  source: "源码",
  data: "数据视图",
  tasks: "任务与结果",
  terminal: "终端",
  settings: "设置",
  intelligence: "智能助手",
  changes: "修改审查",
  comparison: "并排比较",
  result: "探针结果",
  context: "上下文记录",
};
const menu: DocumentKind[] = [
  "graph",
  "probes",
  "tools",
  "intelligence",
  "changes",
  "tasks",
  "terminal",
  "settings",
];
export default function ProjectWorkbench({
  onLegacy,
}: {
  onLegacy: () => void;
}) {
  return (
    <ProjectHost onLegacy={onLegacy}>
      {(session) => <BoundProject key={session.project.id} session={session} />}
    </ProjectHost>
  );
}
function BoundProject({ session }: { session: ProjectSession }) {
  const services = useMemo(
    () => createResearchServices(session.project.id),
    [session.project.id],
  );
  return (
    <ResearchServicesProvider services={services}>
      <ProjectWorkspace session={session} />
    </ResearchServicesProvider>
  );
}
function ProjectWorkspace({ session }: { session: ProjectSession }) {
  const c = useProjectWorkbench(session),
    { research, workbench: wb } = useResearchServices();
  const workspace = useWorkspace("cdaf-project-layout:" + session.project.id);
  const [targets, setTargets] = useState<TargetRef[]>([]),
    [scope, setScope] = useState<string | null>(null),
    [history, setHistory] = useState<Array<string | null>>([]);
  const [mode, setMode] = useState<"code" | "data">("code"),
    [slice, setSlice] = useState<ProjectGraphSlice>(),
    [graphError, setGraphError] = useState("");
  const [analysis, setAnalysis] = useState<AnalysisDocument>(),
    [modelsVisible, setModelsVisible] = useState(false),
    [requestedProbe, setRequestedProbe] = useState("");
  const [entriesVisible, setEntriesVisible] = useState(false),
    [range, setRange] = useState<"project" | "selection" | "block">("project");
  const [theme, setTheme] = useState(
    () => localStorage.getItem("cdaf-theme") || "light",
  );
  const [explorerWidth, setExplorerWidth] = useState(280),
    drag = useRef<{ x: number; width: number } | undefined>(undefined);
  const [viewEpoch, setViewEpoch] = useState(0);
  const viewKey = `cdaf-project-camera:${session.project.id}:${c.revisionId}:${scope ?? "root"}:${mode}`;
  const savedView = useMemo(() => {
    try {
      return JSON.parse(
        localStorage.getItem(viewKey) || "null",
      ) as ProjectCanvasView | null;
    } catch {
      return null;
    }
  }, [viewKey]);
  const open = useCallback(
    (
      kind: DocumentKind,
      reference: WorkspaceDocument["reference"] = {},
      title?: string,
    ) => {
      const identity = reference.snapshot_id
        ? reference.snapshot_id + ":" + (reference.instance_id ?? "")
        : reference.file_id
          ? reference.file_id + ":" + reference.project_revision_id
          : (reference.output_id ??
            reference.context_id ??
            reference.proposal_id ??
            "workspace");
      workspace.dispatch({
        type: "open",
        document: {
          id: kind + ":" + identity,
          kind,
          reference,
          title: title ?? names[kind] ?? kind,
          pinned: false,
        },
        group:
          kind === "tasks"
            ? "bottom"
            : kind === "source"
              ? "source"
              : kind === "probes"
                ? "detail"
                : "main",
      });
    },
    [workspace.dispatch],
  );
  useEffect(() => {
    if (
      workspace.ready &&
      !groups(workspace.layout.tree).some((g) => g.tabs.length)
    ) {
      open("graph");
      open("probes");
      workspace.dispatch({
        type: "minimize",
        group: "source",
        minimized: true,
      });
      workspace.dispatch({
        type: "minimize",
        group: "bottom",
        minimized: true,
      });
    }
  }, [workspace.ready]);
  useEffect(() => {
    setTargets([]);
    setScope(null);
    setHistory([]);
  }, [c.runId, c.revisionId]);
  useEffect(() => {
    const abort = new AbortController();
    setSlice(undefined);
    setGraphError("");
    if (!c.revisionId) return () => abort.abort();
    void c.queries
      .graph(
        c.revisionId,
        { view: mode, scope_id: scope || undefined, limit: 350 },
        abort.signal,
      )
      .then((graph) => {
        if (!abort.signal.aborted) setSlice(graph);
      })
      .catch((e) => {
        if (!abort.signal.aborted) setGraphError(e.message);
      });
    return () => abort.abort();
  }, [c.queries, c.revisionId, scope, mode, viewEpoch]);
  const fileId = targets.at(-1)?.file_id,
    selectedRevision = targets.at(-1)?.project_revision_id;
  useEffect(() => {
    const abort = new AbortController();
    setAnalysis(undefined);
    if (fileId && selectedRevision)
      void c.queries
        .analysis(selectedRevision, fileId, abort.signal)
        .then((a) => {
          if (!abort.signal.aborted) setAnalysis(a);
        })
        .catch((e) => {
          if (!abort.signal.aborted) c.setError(e.message);
        });
    return () => abort.abort();
  }, [fileId, selectedRevision, c.queries]);
  const select = (target: TargetRef, event: MouseEvent) => {
    setTargets((current) =>
      event.ctrlKey || event.metaKey
        ? current.some(
            (t) => targetSelectionKey(t) === targetSelectionKey(target),
          )
          ? current.filter(
              (t) => targetSelectionKey(t) !== targetSelectionKey(target),
            )
          : [...current, target]
        : [target],
    );
  };
  const enter = (id: string | null) => {
    setHistory((current) => [...current, scope]);
    setScope(id);
    setTargets([]);
  };
  const source = (target: TargetRef) => {
    if (!target.file_id || !target.project_revision_id) {
      c.setError("此结构没有对应的源码版本");
      return;
    }
    const path = slice?.graph.blocks.find(
      (b) => b.source?.file_id === target.file_id,
    )?.source?.path;
    open(
      "source",
      {
        project_id: session.project.id,
        file_id: target.file_id,
        project_revision_id: target.project_revision_id,
      },
      path?.split(/[\\/]/).at(-1) ?? "源码",
    );
  };
  const showData = async (target: TargetRef) => {
    try {
      let id: string | null | undefined = target.snapshot_id;
      if (!id && target.logical_key && c.revisionId) {
        const page = await c.queries.objects(c.revisionId, {
          file_id: target.file_id ?? undefined,
          run_id: c.runId || undefined,
          kind: "all",
          query: target.logical_key.split("::").at(-1),
          limit: 200,
        });
        id = page.items.find(
          (item) => item.target.logical_key === target.logical_key,
        )?.target.snapshot_id;
      }
      if (!id) {
        source(target);
        return;
      }
      const snapshot = await research.client.snapshot(id);
      open(
        "data",
        {
          snapshot_id: snapshot.id,
          run_id: snapshot.run_id,
          file_id: snapshot.source?.file_id,
          project_revision_id: snapshot.source?.project_revision_id,
        },
        snapshot.name,
      );
    } catch (e) {
      c.setError((e as Error).message);
    }
  };
  const selectVersion = (snapshot: SnapshotRef) =>
    open(
      "data",
      {
        snapshot_id: snapshot.id,
        run_id: snapshot.run_id,
        file_id: snapshot.source?.file_id,
        project_revision_id: snapshot.source?.project_revision_id,
      },
      snapshot.name,
    );
  const viewOutput = (output: ProbeOutput) =>
    typeof output.data.context_id === "string"
      ? open("context", { context_id: output.data.context_id })
      : open(
          output.definition_id === "view.compare" ? "comparison" : "result",
          { output_id: output.id },
          output.definition_id,
        );
  const selectedSnapshot =
    targets.length === 1
      ? [...c.state.latest.values()].find(
          (s) => s.logical_key === targets[0].logical_key,
        )
      : undefined;
  const frozenScope = {
    mode: range,
    block_id: range === "block" ? scope : null,
    targets: range === "selection" ? targets : [],
    excluded_keys: [],
  } as const;
  const execute = (operation: "compute" | "probes" | "replot") => {
    if (range === "selection" && !targets.length) {
      c.setError("请先选择对象");
      return;
    }
    if (range === "block" && !scope) {
      c.setError("请先进入一个块");
      return;
    }
    void c.execute(operation, {
      ...frozenScope,
      targets: [...frozenScope.targets],
      excluded_keys: [],
    });
    open("tasks");
  };
  const render = (doc: WorkspaceDocument) => {
    switch (doc.kind) {
      case "graph":
        return (
          <div className="project-graph-document">
            <div className="wb-view-toolbar">
              <button
                aria-label="返回上层范围"
                disabled={!history.length}
                onClick={() => {
                  setScope(history.at(-1) ?? null);
                  setHistory((h) => h.slice(0, -1));
                  setTargets([]);
                }}
              >
                ← Back
              </button>
              <button
                onClick={() => {
                  setScope(null);
                  setHistory([]);
                }}
              >
                Project
              </button>
              <button
                aria-pressed={mode === "code"}
                onClick={() => setMode("code")}
              >
                Code
              </button>
              <button
                aria-pressed={mode === "data"}
                onClick={() => setMode("data")}
              >
                Data
              </button>
              <small>
                {scope
                  ? (slice?.graph.blocks.find((b) => b.id === scope)?.label ??
                    "Scope")
                  : "Overview"}
              </small>
            </div>
            {graphError ? (
              <div role="alert">
                {graphError}
                <button onClick={() => setViewEpoch((n) => n + 1)}>重试</button>
              </div>
            ) : slice ? (
              <ProjectCanvas
                key={viewKey}
                slice={slice}
                selected={targets}
                onSelect={select}
                onSelectionChange={setTargets}
                onOpenSource={source}
                onEnterScope={enter}
                savedView={savedView ?? undefined}
                onViewChange={(view) => {
                  try {
                    localStorage.setItem(viewKey, JSON.stringify(view));
                  } catch {
                    c.setError("画布布局无法保存");
                  }
                }}
              />
            ) : (
              <p>读取计算关系…</p>
            )}
          </div>
        );
      case "source":
        return (
          <ProjectSourceDocument
            document={doc}
            queries={c.queries}
            targets={targets}
            onError={c.setError}
          />
        );
      case "data":
        return (
          <ProjectDataDocument
            document={doc}
            queries={c.queries}
            state={c.state}
            outputVersion={c.outputVersion}
            onSelectVersion={selectVersion}
            onEvaluate={(snapshot) => {
              void c
                .save()
                .then(() => wb.evaluate(snapshot.run_id, [snapshot.id]))
                .then(c.track)
                .catch((e) => c.setError(e.message));
            }}
            config={c.config}
            definitions={c.definitions}
            onConfig={c.editConfig}
            onSave={c.save}
            onOpenPresenter={(snapshot, id) =>
              open(
                "data",
                {
                  snapshot_id: snapshot.id,
                  run_id: snapshot.run_id,
                  instance_id: id,
                },
                snapshot.name,
              )
            }
            onOpenInspector={(snapshot, parsed) => {
              setAnalysis(parsed);
              setTargets([snapshotProbeTarget(snapshot, parsed)]);
              open("probes");
            }}
          />
        );
      case "probes":
        return c.config ? (
          <ProbeInspector
            selection={{ targets, anchor: null }}
            blockScope={scope}
            requested={requestedProbe}
            onRequestedHandled={() => setRequestedProbe("")}
            config={c.config}
            definitions={c.definitions}
            selected={selectedSnapshot}
            analysis={analysis}
            outputs={c.outputs}
            onChange={c.editConfig}
            onSave={c.save}
            onError={c.setError}
            onRecorded={c.record}
            onModelSettings={() => setModelsVisible(true)}
          />
        ) : null;
      case "tools":
        return (
          <ProbeLibrary
            definitions={c.definitions}
            config={c.config}
            onChange={c.editConfig}
            onSave={c.save}
            onModelSettings={() => setModelsVisible(true)}
            interpreter={c.config?.interpreter ?? ""}
            tasks={c.tasks}
            onTask={c.track}
            onError={c.setError}
            onRefresh={c.refresh}
            onBind={(id) => {
              setRequestedProbe(id);
              open("probes");
            }}
          />
        );
      case "tasks":
        return (
          <TaskPanel
            tasks={c.tasks}
            outputs={c.outputs}
            state={c.state}
            analysis={analysis}
            scope={scope}
            onContext={(id) => open("context", { context_id: id })}
            onChange={(id) => open("changes", { proposal_id: id })}
            onOutput={viewOutput}
            onSnapshot={(id) => {
              void research.client
                .snapshot(id)
                .then(selectVersion)
                .catch((e) => c.setError(e.message));
            }}
            onError={c.setError}
          />
        );
      case "terminal":
        return <CommandPane />;
      case "intelligence":
        return c.config ? (
          <ProjectIntelligencePanel
            key={session.project.id}
            projectId={session.project.id}
            revisionId={session.revisionId}
            entryId={c.entryId}
            selection={targets}
            config={c.config}
            onChange={c.editConfig}
            onSave={c.save}
            onTask={c.track}
            onModels={() => setModelsVisible(true)}
            onError={c.setError}
            onOpenChange={(id) => open("changes", { proposal_id: id })}
          />
        ) : null;
      case "changes":
        return (
          <ProjectChangeReview
            key={session.project.id}
            projectId={session.project.id}
            revisionId={session.revisionId}
            changeId={doc.reference.proposal_id}
            onRevision={session.onRevision}
            onError={c.setError}
          />
        );
      case "context":
        return (
          <ContextView
            id={doc.reference.context_id!}
            onError={c.setError}
            onProposal={(id) => open("changes", { proposal_id: id })}
          />
        );
      case "settings":
        return (
          <WorkbenchSettings
            version="0.6.0"
            onModels={() => setModelsVisible(true)}
            onTools={() => open("tools")}
            onError={c.setError}
            onApplied={(preferences) => {
              const value = preferences.values.workspace?.theme;
              if (typeof value === "string") setTheme(value);
            }}
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
            onData={(id) => {
              void research.client
                .snapshot(id)
                .then(selectVersion)
                .catch((e) => c.setError(e.message));
            }}
            onProposal={(proposal) =>
              open("changes", { proposal_id: proposal.id })
            }
            onError={c.setError}
          />
        );
    }
  };
  return (
    <main
      className="research-app scientific-workspace project-workbench"
      data-theme={theme}
    >
      <header className="wb-menubar">
        <h1>Scientific Dataflow Inspector</h1>
        <span className="wb-project-name">{session.project.name}</span>
        <div className="ri-header-actions">
          <button onClick={() => open("settings")}>设置</button>
          <button onClick={() => setModelsVisible(true)}>模型设置</button>
          <button
            aria-label="切换主题"
            onClick={() => {
              const value = theme === "light" ? "dark" : "light";
              setTheme(value);
              document.documentElement.dataset.theme = value;
              localStorage.setItem("cdaf-theme", value);
            }}
          >
            ◐
          </button>
        </div>
      </header>
      <div className="wb-main-toolbar">
        <button
          aria-expanded={entriesVisible}
          onClick={() => setEntriesVisible((v) => !v)}
        >
          运行入口
        </button>
        <select
          aria-label="项目运行入口"
          value={c.entryId}
          onChange={(e) => c.setEntryId(e.target.value)}
        >
          <option value="">选择入口</option>
          {c.config?.run_configurations.map((entry) => (
            <option key={entry.id} value={entry.id}>
              {entry.name}
            </option>
          ))}
        </select>
        <button
          className="wb-primary"
          disabled={
            c.busy ||
            !c.entryId ||
            c.tasks.some((t) => ["queued", "running"].includes(t.status))
          }
          onClick={() => execute("compute")}
        >
          运行
        </button>
        <select
          aria-label="探针应用范围"
          value={range}
          onChange={(e) => setRange(e.target.value as typeof range)}
        >
          <option value="project">整个项目</option>
          <option value="selection">当前选择 ({targets.length})</option>
          <option value="block" disabled={!scope}>
            当前块
          </option>
        </select>
        <button disabled={c.busy || !c.runId} onClick={() => execute("probes")}>
          执行探针
        </button>
        <button disabled={c.busy || !c.runId} onClick={() => execute("replot")}>
          重新绘图
        </button>
        <select
          aria-label="项目运行记录"
          value={c.runId}
          onChange={(e) => c.chooseRun(e.target.value)}
        >
          <option value="">当前源码</option>
          {c.runs.map((run) => (
            <option key={run.id} value={run.id}>
              {run.name || run.id.slice(0, 8)} · {run.status}
            </option>
          ))}
        </select>
        <button
          disabled={!c.dirty}
          onClick={() => void c.save().catch((e) => c.setError(e.message))}
        >
          保存配置{c.dirty ? " *" : ""}
        </button>
        <LayoutControls
          layout={workspace.layout}
          dispatch={workspace.dispatch}
        />
      </div>
      {entriesVisible && (
        <div className="project-entry-popover">
          <button
            aria-label="关闭运行入口"
            onClick={() => setEntriesVisible(false)}
          >
            ×
          </button>
          <ProjectRunConfigurations
            projectId={session.project.id}
            revisionId={session.revisionId}
            onSelect={c.setEntryId}
            onSaved={c.refresh}
            onError={c.setError}
          />
        </div>
      )}
      <div className="wb-body">
        <nav className="wb-activity" aria-label="项目工作区">
          {menu.map((kind) => (
            <button
              key={kind}
              aria-label={names[kind]}
              onClick={() => open(kind)}
            >
              {names[kind]}
            </button>
          ))}
        </nav>
        <aside className="wb-explorer" style={{ width: explorerWidth }}>
          {c.revisionId ? (
            <ProjectBrowser
              key={c.revisionId}
              project={session.project}
              revisionId={c.revisionId}
              runId={c.runId || undefined}
              scopeId={scope}
              refreshKey={`${c.config?.revision}:${c.outputVersion}`}
              queries={c.queries}
              selected={targets}
              onSelect={select}
              onSelectionChange={setTargets}
              onOpenSource={(target) => void showData(target)}
              onEnterScope={(target) =>
                enter(
                  target.block_id ?? target.object_id ?? target.file_id ?? null,
                )
              }
            />
          ) : (
            <p>读取运行版本…</p>
          )}
        </aside>
        <div
          role="separator"
          aria-label="调整对象侧栏"
          aria-orientation="vertical"
          className="workspace-separator horizontal"
          onPointerDown={(e) => {
            if (workspace.layout.locked) return;
            drag.current = { x: e.clientX, width: explorerWidth };
            e.currentTarget.setPointerCapture(e.pointerId);
          }}
          onPointerMove={(e) => {
            if (drag.current)
              setExplorerWidth(
                Math.max(
                  180,
                  Math.min(
                    500,
                    drag.current.width + e.clientX - drag.current.x,
                  ),
                ),
              );
          }}
          onPointerUp={() => {
            drag.current = undefined;
          }}
        />
        <WorkspaceShell
          layout={workspace.layout}
          dispatch={workspace.dispatch}
          render={render}
          onOpen={() => open("graph")}
        />
      </div>
      <footer className="wb-statusbar">
        <span>
          {targets.length} 个选中 · {c.runId ? c.state.status : "当前源码"} ·{" "}
          {c.revisionId?.slice(0, 8)}
        </span>
        {c.error ? (
          <span role="alert">
            {c.error}
            <button onClick={() => c.setError("")}>×</button>
          </span>
        ) : (
          <span>{c.notice}</span>
        )}
      </footer>
      {modelsVisible && (
        <ModelSettings visible onClose={() => setModelsVisible(false)} />
      )}
    </main>
  );
}
