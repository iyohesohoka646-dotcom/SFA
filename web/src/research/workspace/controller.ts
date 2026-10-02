import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { client, subscribeRun, type ResearchInfo, type RunRecord, type SourceFile } from '../client';
import type { ObservationEvent, SnapshotRef } from '../generated';
import { applyEvent, createState, indexSnapshot } from '../state';
import { useOperation } from '../operations';
import type { AnalysisDocument, ProbeDefinition, ProbeOutput, TaskRecord, WorkbenchConfig } from './generated';
import { useWorkspace } from './useWorkspace';
import { wb } from './WorkbenchClient';
import {scopeSelector,type Selection} from './selection';
import { groups, type DocumentKind, type WorkspaceDocument } from './layout';

export function useWorkbench() {
  const [info, setInfo] = useState<ResearchInfo>(), [runs, setRuns] = useState<RunRecord[]>([]), [runId, setRunIdRaw] = useState('');
  const [config, setConfig] = useState<WorkbenchConfig>(), [definitions, setDefinitions] = useState<ProbeDefinition[]>([]);
  const [script, setScriptRaw] = useState(''), [interpreter, setInterpreterRaw] = useState(''), [analysis, setAnalysis] = useState<AnalysisDocument>(), [file, setFile] = useState<SourceFile>();
  const [selection,setSelection] = useState<Selection>({targets:[],anchor:null}), [blockScope,setBlockScope]=useState<string|null>(null), [probeRange,setProbeRange]=useState<'selection'|'block'|'project'>('project');
  const [state, setState] = useState(() => createState('')), [selected, setSelected] = useState(''), [focusSnapshot, setFocusSnapshot] = useState<SnapshotRef>(), [selectedObject, setSelectedObject] = useState('');
  const [tasks, setTasks] = useState<TaskRecord[]>([]), [outputs, setOutputs] = useState<ProbeOutput[]>([]), [notice, setNotice] = useState(''), [dirty, setDirty] = useState(false);
  const changed = useRef(new Set<string>()), importVersion = useRef(0), runRef = useRef(runId), stateRef = useRef(state);
  const followedTask = useRef<string | null>(null);
  const setRunId = useCallback((id: string) => { followedTask.current = null; setRunIdRaw(id); }, []);
  runRef.current = runId; stateRef.current = state;
  const workspace = useWorkspace('cdaf-workbench-layout:' + (info?.root ?? 'loading'));
  const loading = useOperation('workbench-import'), preparing = useOperation('workbench-plan');
  const setScript = (value: string) => { changed.current.add('script'); setScriptRaw(value); };
  const setInterpreter = (value: string) => { changed.current.add('interpreter'); setInterpreterRaw(value); setDirty(true); };
  const open = useCallback((kind: DocumentKind, reference: WorkspaceDocument['reference'] = {}, title?: string, pinned = false, group?: string, background = false) => {
    const id = kind + ':' + ((reference.snapshot_id ? reference.snapshot_id + (reference.instance_id ? ':'+reference.instance_id : '') : undefined) ?? reference.context_id ?? reference.proposal_id ?? reference.output_id ?? reference.analysis_id ?? reference.run_id ?? 'workspace');
    workspace.dispatch({ type: 'open', background, document: { id, kind, reference, title: title ?? ({ source: '源码', data: '数据探针', graph: '计算关系图', probes: '探针台', tools: '工具库', intelligence: '智能助手', changes: '代码审查', context: '上下文记录', tasks: '任务与结果', terminal: '终端',comparison:'并排比较',settings:'设置' }[kind]), pinned }, group: group ?? (kind === 'source' ? 'source' : kind === 'tasks' ? 'bottom' : 'main') });
  }, [workspace.dispatch]);
  const track = useCallback((task: TaskRecord) => { if (task.kind === 'compute') followedTask.current = task.id; setTasks(current => [task, ...current.filter(t => t.id !== task.id)].slice(0, 64)); open('tasks', {}, '任务与结果', true, 'bottom'); }, [open]);
  const editConfig = (next: WorkbenchConfig) => { changed.current.add('config'); setConfig(next); setDirty(true); };
  const imported = useCallback(async (path: string, signal?: AbortSignal, background = false) => {
    const version = ++importVersion.current;
    const next = await wb.importSource(path, signal);
    const source = await wb.source(next.id, signal);
    if (signal?.aborted || version !== importVersion.current) return;
    setAnalysis(next); setFile(source); setSelectedObject(''); setSelection({targets:[],anchor:null}); setBlockScope(null);
    open('source', { analysis_id: next.id }, path.split(/[\\/]/).at(-1) ?? '源码', false, 'source', background);
    if (!next.diagnostics.length) setNotice('源码已解析 · ' + next.objects.length + ' 个对象');
    else setNotice(next.diagnostics.join('；'));
    return next;
  }, [open]);

  useEffect(() => {
    const abort = new AbortController();
    void Promise.all([client.info(abort.signal), wb.configuration(abort.signal), wb.definitions(abort.signal), client.runs(abort.signal), wb.tasks(abort.signal)])
      .then(([info, cfg, defs, runs, tasks]) => {
        if (abort.signal.aborted) return;
        setInfo(info); if (!changed.current.has('config')) setConfig(cfg); setDefinitions(defs); setRuns(runs); setTasks(tasks);
        const path = cfg.script || info.examples[0]?.script || '';
        if (!changed.current.has('script')) { setScriptRaw(path); if (path) void imported(path, abort.signal, true).catch(error => { if (!abort.signal.aborted) setNotice(error.message); }); }
        if (!changed.current.has('interpreter')) setInterpreterRaw(cfg.interpreter || info.interpreter);
        setRunIdRaw(id => id || runs[0]?.id || '');
      }).catch(error => { if (!abort.signal.aborted) setNotice(error.message); });
    return () => abort.abort();
  }, [imported, open]);

  useEffect(() => {
    if (!info || !workspace.ready) return;
    if (!groups(workspace.layout.tree).some(g => g.tabs.length)) {
      open('probes', {}, '探针台', true, 'detail'); open('tasks', {}, '任务与结果', true, 'bottom');
      if (analysis) open('source', { analysis_id: analysis.id }, analysis.path.split(/[\\/]/).at(-1));
    }
  }, [info?.root, workspace.ready]);

  useEffect(() => {
    const abort = new AbortController(); setState(createState(runId)); setSelected(''); setFocusSnapshot(undefined);
    if (!runId) return () => abort.abort();
    const queue: ObservationEvent[] = []; let timer: ReturnType<typeof setTimeout> | undefined;
    const flush = () => { timer = undefined; const pending = queue.splice(0); if (!abort.signal.aborted) setState(current => pending.reduce(applyEvent, current)); };
    void client.bootstrap(runId, abort.signal).then(result => {
      if (abort.signal.aborted) return;
      let next = createState(runId); const parents = new Map(Object.entries(result.parent_bindings));
      for (const value of result.snapshots) indexSnapshot(next, value, parents);
      for (const operation of result.operations) next.operations.set(operation.id, operation);
      for (const event of result.probe_events) next = applyEvent(next, event);
      next.status = result.run.status; next.summary = result.run.summary; next.lastSequence = result.cursor; setState(next);
      return subscribeRun(runId, result.cursor, event => { queue.push(event); timer ??= setTimeout(flush, 32); }, abort.signal);
    }).catch(error => { if (!abort.signal.aborted) setNotice(error.message); });
    void wb.outputs({ run_id: runId }, abort.signal).then(value => { if (!abort.signal.aborted) setOutputs(value); }).catch(error => { if (!abort.signal.aborted) setNotice(error.message); });
    return () => { abort.abort(); if (timer) clearTimeout(timer); };
  }, [runId]);

  const activeKey = tasks.filter(t => ['queued', 'running'].includes(t.status)).map(t => t.id).sort().join('|');
  useEffect(() => {
    if (!activeKey) return;
    const abort = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      const records = await Promise.allSettled(activeKey.split('|').map(id => wb.task(id, abort.signal)));
      if (abort.signal.aborted) return;
      const updates = records.flatMap(r => r.status === 'fulfilled' ? [r.value] : []);
      for (const task of updates) {
        if (task.id === followedTask.current && task.run_id && task.run_id !== runRef.current) setRunIdRaw(task.run_id);
        if (!['queued', 'running'].includes(task.status)) {
          if (task.run_id === runRef.current) await wb.outputs({ run_id: task.run_id }, abort.signal).then(value => { if (!abort.signal.aborted) setOutputs(value); }).catch(() => {});
          await client.runs(abort.signal).then(value => { if (!abort.signal.aborted) setRuns(value); }).catch(() => {});
        }
      }
      if (abort.signal.aborted) return;
      setTasks(current => current.map(t => updates.find(u => u.id === t.id) ?? t));
      timer = setTimeout(() => void poll(), 400);
    };
    void poll(); return () => { abort.abort(); clearTimeout(timer); };
  }, [activeKey]);

  useEffect(() => {
    const finished = tasks.find(t => t.run_id === runId && !['queued','running'].includes(t.status) && ['completed','failed','cancelled','timeout','interrupted'].includes(t.calculation_status));
    if (finished) setState(current => current.runId === runId && current.status !== finished.calculation_status ? { ...current, status: finished.calculation_status } : current);
  }, [tasks, runId, state.status]);

  const selectSnapshot = useCallback((value: SnapshotRef, group = 'main') => {
    setSelected(value.binding_id); setFocusSnapshot(value);
    if (analysis && value.source?.digest === analysis.source_digest) {
      const chooseTargets = (next:Selection) => { setSelection(next); const target=next.targets.at(-1); if(next.targets.length===1&&target){setSelectedObject(target.object_id??'');const value=target.snapshot_id ? values.find(v=>v.id===target.snapshot_id) : values.find(v=>v.logical_key===target.logical_key);setFocusSnapshot(value);setSelected(value?.binding_id??'');}else{setSelectedObject('');setFocusSnapshot(undefined);setSelected('');} };
  const enterScope=(id:string|null)=>{setBlockScope(id);chooseTargets({targets:[],anchor:null});};
  const object = analysis.objects.find(o => o.line === value.source?.line && o.name === value.name) ?? analysis.objects.find(o => o.qualname === value.source?.qualname);
      if (object) setSelectedObject(object.id);
      open('source', { analysis_id: analysis.id }, analysis.path.split(/[\\/]/).at(-1), false, 'source');
    } else {
      setSelectedObject('');
      open('source', { run_id: value.run_id }, '运行源码 · ' + value.run_id.slice(0, 6), false, 'source');
    }
    if (group !== 'main') workspace.dispatch({ type: 'move', documentId: 'data:' + value.id, group });
    open('data', { snapshot_id: value.id, run_id: value.run_id }, `${value.name} · v${value.version}`, false, group);
  }, [open, analysis]);
  const selectBinding = useCallback((id: string) => { const value = stateRef.current.latest.get(id); if (value) selectSnapshot(value); }, [selectSnapshot]);
  const parse = () => loading.run(signal => imported(script, signal));
  const saveConfig = async (signal?: AbortSignal) => {
    if (!config || !analysis) throw new Error('先导入源码');
    const next = await wb.configure({ ...config, script: analysis.path, interpreter }, signal);
    if (!signal?.aborted) { setConfig(next); setDirty(false); setNotice('配置已保存'); }
    return next;
  };
  const run = (scope: 'compute' | 'probes' | 'replot' = 'compute') => preparing.run(async signal => {
    if (!analysis || script !== analysis.path && script !== config?.script) throw new Error('先导入当前源码');
    await saveConfig(signal);
    const task = scope === 'compute' ? await wb.execute((await wb.plan(analysis.id, signal, scopeSelector(blockScope,selection.targets,probeRange))).id, signal) :
      scope === 'probes' ? await wb.evaluate(runId, [],undefined, scopeSelector(blockScope,selection.targets,probeRange)) : await wb.replot(runId, [],undefined,scopeSelector(blockScope,selection.targets,probeRange));
    if (!signal.aborted) track(task);
    return task;
  });
  const values = useMemo(() => [...state.latest.values()], [state.runId, state.lastSequence]);
  const chooseTargets = (next:Selection) => { setSelection(next); const target=next.targets.at(-1); if(next.targets.length===1&&target){setSelectedObject(target.object_id??'');const value=target.snapshot_id ? values.find(v=>v.id===target.snapshot_id) : values.find(v=>v.logical_key===target.logical_key);setFocusSnapshot(value);setSelected(value?.binding_id??'');}else{setSelectedObject('');setFocusSnapshot(undefined);setSelected('');} };
  const enterScope=(id:string|null)=>{setBlockScope(id);chooseTargets({targets:[],anchor:null});};
  const object = analysis?.objects.find(o => o.id === selectedObject);
  return { ...workspace, info, runs, runId, setRunId, script, setScript, interpreter, setInterpreter, config, editConfig, definitions, analysis, file,
    state, values, selection, chooseTargets, blockScope,enterScope,probeRange,setProbeRange, selected, focusSnapshot, selectedObject, setSelectedObject, object, tasks, outputs, notice, setNotice, dirty, loading, preparing,
    recordOutput: (output: ProbeOutput) => setOutputs(current => [output, ...current.filter(o => o.id !== output.id)]),
    refreshDefinitions:()=>void wb.definitions().then(setDefinitions).catch(e=>setNotice(e.message)), open, track, selectSnapshot, selectBinding, parse, saveConfig, run, imported };
}
