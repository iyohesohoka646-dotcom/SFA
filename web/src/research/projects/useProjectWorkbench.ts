import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useResearchServices } from "../workspace/ResearchServices";
import { applyEvent, createState, indexSnapshot } from "../state";
import type { ObservationEvent } from "../generated";
import type { RunRecord } from "../client";
import type {
  ProbeDefinition,
  ProbeOutput,
  TaskRecord,
  WorkbenchConfig,
  ScopeSelector,
} from "../workspace/generated";
import { createProjectCommands } from "./projectCommands";
import { createProjectQueries } from "./queries";
import type { ProjectSession } from "./ProjectHost";

const active = (task: TaskRecord) =>
  ["queued", "running"].includes(task.status);
export function useProjectWorkbench(session: ProjectSession) {
  const { research, workbench: wb } = useResearchServices();
  const commands = useMemo(
    () => createProjectCommands().forProject(session.project.id),
    [session.project.id],
  );
  const queries = useMemo(
    () => createProjectQueries(session.project.id),
    [session.project.id],
  );
  const [config, setConfig] = useState<WorkbenchConfig>();
  const configRef = useRef(config),
    saveQueue = useRef<Promise<unknown>>(Promise.resolve());
  configRef.current = config;
  const [definitions, setDefinitions] = useState<ProbeDefinition[]>([]),
    [runs, setRuns] = useState<RunRecord[]>([]);
  const [runId, setRunId] = useState(""),
    [entryId, setEntryId] = useState(""),
    [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [outputs, setOutputs] = useState<ProbeOutput[]>([]),
    [notice, setNotice] = useState(""),
    [error, setError] = useState("");
  const [state, setState] = useState(() => createState("")),
    [busy, setBusy] = useState(false),
    [dirty, setDirty] = useState(false);
  const [refresh, setRefresh] = useState(0),
    [outputEpoch, setOutputEpoch] = useState(0);
  const mounted = useRef(true),
    runRef = useRef(runId),
    followed = useRef(""),
    dirtyRef = useRef(false);
  runRef.current = runId;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    const abort = new AbortController();
    setError("");
    void Promise.all([
      wb.configuration(abort.signal),
      wb.definitions(abort.signal),
      research.client.runs(abort.signal),
      wb.tasks(abort.signal),
    ])
      .then(([configuration, defs, history, jobs]) => {
        if (abort.signal.aborted) return;
        if (!configRef.current || !dirtyRef.current) setConfig(configuration);
        setDefinitions(defs);
        setRuns(history);
        setTasks(jobs);
        setEntryId((id) =>
          configuration.run_configurations.some((e) => e.id === id)
            ? id
            : (configuration.run_configurations[0]?.id ?? ""),
        );
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(e.message);
      });
    return () => abort.abort();
  }, [wb, research, session.revisionId, refresh]);
  const editConfig = useCallback((next: WorkbenchConfig) => {
    configRef.current = next;
    dirtyRef.current = true;
    setConfig(next);
    setDirty(true);
  }, []);
  const save = useCallback(() => {
    const operation = async () => {
      const current = configRef.current;
      if (!current) throw new Error("项目配置尚未读取");
      const saved = await wb.configure(current);
      if (!mounted.current) return saved;
      if (configRef.current === current) {
        configRef.current = saved;
        dirtyRef.current = false;
        setConfig(saved);
        setDirty(false);
      } else {
        const next = { ...configRef.current!, revision: saved.revision };
        configRef.current = next;
        setConfig(next);
      }
      return saved;
    };
    const pending = saveQueue.current.then(operation, operation);
    saveQueue.current = pending.then(
      () => undefined,
      () => undefined,
    );
    return pending;
  }, [wb]);
  const track = useCallback((task: TaskRecord) => {
    setTasks((current) =>
      [task, ...current.filter((t) => t.id !== task.id)].slice(0, 128),
    );
  }, []);
  const activeKey = tasks
    .filter(active)
    .map((t) => t.id)
    .sort()
    .join(":");
  useEffect(() => {
    if (!activeKey) return;
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const updated = await Promise.all(
          activeKey.split(":").map((id) => wb.task(id, abort.signal)),
        );
        if (abort.signal.aborted) return;
        setTasks((current) =>
          current.map((t) => updated.find((u) => u.id === t.id) ?? t),
        );
        const owned = updated.find((t) => t.id === followed.current);
        if (owned?.run_id && runRef.current !== owned.run_id)
          setRunId(owned.run_id);
        if (updated.some((t) => !active(t))) {
          setOutputEpoch((n) => n + 1);
          setRefresh((n) => n + 1);
        }
      } catch (e) {
        if (!abort.signal.aborted) setError((e as Error).message);
      }
      if (!abort.signal.aborted) timer = setTimeout(() => void poll(), 350);
    };
    void poll();
    return () => {
      abort.abort();
      clearTimeout(timer);
    };
  }, [activeKey, wb]);
  useEffect(() => {
    const abort = new AbortController();
    setState(createState(runId));
    setOutputs([]);
    if (!runId) return () => abort.abort();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const queue: ObservationEvent[] = [];
    const flush = () => {
      timer = undefined;
      const events = queue.splice(0);
      if (!abort.signal.aborted)
        setState((current) => events.reduce(applyEvent, current));
    };
    void research.client
      .bootstrap(runId, abort.signal)
      .then((boot) => {
        if (abort.signal.aborted) return;
        const next = createState(runId);
        next.status = boot.run.status;
        next.summary = boot.run.summary;
        next.lastSequence = boot.cursor;
        const parents = new Map(Object.entries(boot.parent_bindings));
        boot.snapshots.forEach((s) => indexSnapshot(next, s, parents));
        boot.operations.forEach((op) => next.operations.set(op.id, op));
        setState(next);
        setRuns((current) => [
          boot.run,
          ...current.filter((r) => r.id !== boot.run.id),
        ]);
        return research.subscribeRun(
          runId,
          boot.cursor,
          (event) => {
            queue.push(event);
            if (!timer) timer = setTimeout(flush, 40);
          },
          abort.signal,
        );
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(e.message);
      });
    return () => {
      abort.abort();
      clearTimeout(timer);
    };
  }, [runId, research]);
  useEffect(() => {
    if (!runId) return;
    const abort = new AbortController();
    void wb
      .outputs({ run_id: runId }, abort.signal)
      .then((result) => {
        if (!abort.signal.aborted) setOutputs(result);
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(e.message);
      });
    return () => abort.abort();
  }, [runId, wb, outputEpoch]);
  const run = runs.find((r) => r.id === runId);
  const evidenceRevision =
    typeof run?.environment.project_revision_id === "string"
      ? run.environment.project_revision_id
      : undefined;
  const revisionId = runId ? evidenceRevision : session.revisionId;
  const execute = async (
    scope: "compute" | "probes" | "replot",
    targetScope: ScopeSelector,
  ) => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await save();
      const frozenRevision =
        scope === "compute" ? session.revisionId : revisionId;
      if (!frozenRevision) throw new Error("运行版本尚未读取");
      if (scope === "compute" && !entryId)
        throw new Error("请选择并保存运行入口");
      if (scope !== "compute" && !runId)
        throw new Error("请先选择已保存的运行");
      const plan = await commands.plan({
        configuration_id: entryId || "saved",
        revision_id: frozenRevision,
        scope,
        run_id: scope === "compute" ? null : runId,
        target_scope: targetScope as unknown as Record<string, unknown>,
      });
      const task = await commands.execute(plan.id);
      if (!mounted.current) return;
      if (scope === "compute") followed.current = task.id;
      track(task);
      setNotice("任务已提交");
    } catch (e) {
      if (mounted.current) setError((e as Error).message);
    } finally {
      if (mounted.current) setBusy(false);
    }
  };
  const chooseRun = (id: string) => {
    followed.current = "";
    setRunId(id);
  };
  return {
    config,
    definitions,
    runs,
    runId,
    run,
    revisionId,
    entryId,
    setEntryId,
    tasks,
    outputs,
    state,
    busy,
    dirty,
    notice,
    error,
    setError,
    setNotice,
    editConfig,
    save,
    track,
    execute,
    chooseRun,
    queries,
    refresh: () => setRefresh((n) => n + 1),
    outputVersion: String(outputEpoch),
    record: (output: ProbeOutput) =>
      setOutputs((current) => [
        output,
        ...current.filter((o) => o.id !== output.id),
      ]),
  };
}
