import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Background, Controls, Handle, MiniMap, Position, ReactFlow, useEdgesState, useNodesState, useReactFlow, MarkerType } from '@xyflow/react';
import type { Connection, NodeProps, Node, Edge } from '@xyflow/react';
import type { ProjectSpec } from './generated';
import { api, download, runEvents, streamRun, projectPrefix } from './api';
import { ConnectionHelp, Dialog, Tabs } from './components';
import { ProjectTools } from './tools';
import { layoutGraph, reachable } from './graph';
import type { View } from './graph';

type Mode = 'Architecture' | 'Runs' | 'Probes' | 'Review';
const MODES: Mode[] = ['Architecture', 'Runs', 'Probes', 'Review'];
const json = (value: unknown) => JSON.stringify(value, null, 2);
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
const short = (value: string) => value?.slice(0, 8) || '—';
const emptyView: View = { positions: {}, collapsed: [], theme: 'dark' };

function Icon({ name, size = 16 }: { name: string; size?: number }) {
  const paths: Record<string, string> = {
    flow: 'M4 4h5v5H4z M15 15h5v5h-5z M15 4h5v5h-5z M9 6h6 M6 9v8h9',
    play: 'M7 4l14 8-14 8z', search: 'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14 M15 15l6 6',
    probe: 'M9 3h6 M10 3v7l-6 9a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2l-6-9V3 M8 15h8',
    review: 'M8 3h12v18H4V7z M8 3v4H4 M8 12h8 M8 16h6', plus: 'M12 4v16 M4 12h16',
    chevron: 'M9 5l7 7-7 7', check: 'M4 12l5 5L20 6', close: 'M5 5l14 14 M19 5L5 19',
    sun: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M12 2v2 M12 20v2 M2 12h2 M20 12h2 M5 5l2 2 M17 17l2 2 M5 19l2-2 M17 7l2-2',
    export: 'M12 3v12 M7 8l5-5 5 5 M4 14v7h16v-7', undo: 'M8 4L3 9l5 5 M3 9h10a7 7 0 0 1 7 7v4',
    fit: 'M4 9V4h5 M15 4h5v5 M20 15v5h-5 M9 20H4v-5', code: 'M8 5l-6 7 6 7 M16 5l6 7-6 7 M14 3l-4 18',
    layers: 'M12 2L2 7l10 5 10-5z M2 12l10 5 10-5 M2 17l10 5 10-5', pause: 'M8 4v16 M16 4v16',
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name] || paths.flow} /></svg>;
}

function ModuleNode({ data, selected }: NodeProps) {
  const m = data.module as any;
  const inputs = Object.keys(m.contract?.input?.properties || {});
  const status = String(data.status || 'designed'); const quality = data.quality as string | undefined;
  return <div className={`module-node ${selected ? 'selected' : ''} ${data.dim ? 'dimmed' : ''} ${m.kind} ${quality ? 'quality-' + quality : ''}`}>
    <div className="node-heading"><span className={`node-kind ${m.kind}`}><Icon name={m.kind === 'composite' ? 'layers' : m.kind === 'decision' ? 'flow' : 'code'} /></span><span className="node-meta">{m.kind === 'python' ? 'PYTHON MODULE' : m.kind.toUpperCase()}<small>{m.id}</small></span><span className={`state-dot ${status}`} /></div>
    <strong className="node-name">{m.name || m.id}</strong>
    {data.parentName ? <span className="node-parent">↳ {String(data.parentName)}</span> : null}
    <div className="node-ports">{inputs.map(port => <div className="port" key={port}><Handle type="target" position={Position.Left} id={port} style={{ top: '50%' }} /><span>{port}</span><small>{String(m.contract.input.properties[port]?.type || 'dynamic')}</small></div>)}<span className="output-port">{String(m.contract?.output?.type || 'output')}<Handle type="source" position={Position.Right} id="out" /></span></div>
    <div className="node-footer"><span className={`node-status ${status}`}>{status === 'completed' ? '✓ Completed' : status === 'started' ? '● Running' : status === 'designed' ? '○ Ready' : status}</span>{quality ? <span className="quality-label">{quality === 'fail' ? 'Quality failed' : 'Observer error'}</span> : <span>{Number(data.probeCount) || 0} probes</span>}</div>
    {m.kind === 'composite' && <button className="expand-node nodrag" onClick={() => (data.onExpand as (id: string) => void)(m.id)}>{data.collapsed ? 'Expand subgraph' : 'Collapse subgraph'} <Icon name="chevron" size={12} /></button>}
  </div>;
}
const nodeTypes = { module: ModuleNode };

function JsonEditor({ label, value, onChange, rows = 10 }: { label: string; value: string; onChange: (value: string) => void; rows?: number }) {
  return <label className="field json-field"><span>{label}</span><textarea aria-label={label} spellCheck={false} rows={rows} value={value} onChange={e => onChange(e.target.value)} /></label>;
}

function InputBinding({ module, port, draft, edit }: { module: any; port: string; draft: any; edit: (next: any) => void }) {
  const current = draft.bindings.find((b: any) => b.target === module.id && b.port === port);
  const [sourceId, setSourceId] = useState(current?.source.kind === 'module' ? current.source.module : current?.source.kind || 'project');
  const [pointer, setPointer] = useState(current?.source.pointer ?? '/' + port);
  const [literal, setLiteral] = useState(json(current?.source.value ?? null));
  const [dynamic, setDynamic] = useState(current?.dynamic || false);
  const [visibility, setVisibility] = useState(current?.visibility || 'L2');
  const [message, setMessage] = useState('');
  function apply() {
    try {
      const source = sourceId === 'literal' ? { kind: 'literal', module: null, pointer: '', value: JSON.parse(literal) } : { kind: sourceId === 'project' ? 'project' : 'module', module: sourceId === 'project' ? null : sourceId, pointer, value: null };
      const binding = { id: current?.id || `${module.id}_${port}`, target: module.id, port, source, dynamic, visibility, provenance: 'designed' };
      edit({ ...draft, bindings: [...draft.bindings.filter((b: any) => !(b.target === module.id && b.port === port)), binding] });
      setMessage('Binding added to draft');
    } catch { setMessage('Literal value must be valid JSON'); }
  }
  return <section className="binding-editor"><strong>{port}</strong><label className="field"><span>Source</span><select aria-label={`Source for ${port}`} value={sourceId} onChange={e => setSourceId(e.target.value)}><option value="project">Project input</option><option value="literal">Literal / default</option>{draft.modules.filter((m: any) => m.id !== module.id).map((m: any) => <option key={m.id} value={m.id}>{m.name || m.id}</option>)}</select></label>{sourceId === 'literal' ? <JsonEditor label={`Literal value for ${port}`} value={literal} onChange={setLiteral} rows={2} /> : <label className="field"><span>JSON Pointer</span><input aria-label={`Binding pointer for ${port}`} value={pointer} onChange={e => setPointer(e.target.value)} placeholder="/field (empty = entire value)" /></label>}<label className="field"><span>AI visibility cap</span><select aria-label={`Visibility cap for ${port}`} value={visibility} onChange={e => setVisibility(e.target.value)}>{['L1', 'L2', 'L3', 'L4'].map(level => <option key={level}>{level}</option>)}</select></label><label className="checkbox"><input type="checkbox" checked={dynamic} onChange={e => setDynamic(e.target.checked)} /> Allow a dynamic schema boundary</label><button aria-label={`Apply binding for ${port}`} onClick={apply}>Apply binding</button>{message && <small>{message}</small>}</section>;
}

function InputBindings({ module, draft, edit }: { module: any; draft: any; edit: (next: any) => void }) {
  return <details className="advanced-editor"><summary>Bind module inputs</summary>{Object.keys(module.contract.input.properties || {}).map(port => <InputBinding key={module.id + port} module={module} port={port} draft={draft} edit={edit} />)}</details>;
}

export default function App() {
  const [project, setProject] = useState<any>(null); const [draft, setDraft] = useState<any>(null); const [revision, setRevision] = useState('');
  const [view, setView] = useState<View>(emptyView); const [viewRevision, setViewRevision] = useState('');
  const [mode, setMode] = useState<Mode>('Architecture'); const [selected, setSelected] = useState(''); const [selectedEdge, setSelectedEdge] = useState<string | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]); const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [runs, setRuns] = useState<any[]>([]); const [run, setRun] = useState<any>(null); const [events, setEvents] = useState<any[]>([]); const [historyProject, setHistoryProject] = useState<any>(null);
  const [changes, setChanges] = useState<any[]>([]); const [changeId, setChangeId] = useState('');
  const [diagnostics, setDiagnostics] = useState<any[]>([]); const [notice, setNotice] = useState(''); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState(''); const [focus, setFocus] = useState<'off' | 'upstream' | 'downstream' | 'both'>('off');
  const [inspector, setInspector] = useState('Overview'); const [contractText, setContractText] = useState(''); const [moduleText, setModuleText] = useState('');
  const [inputText, setInputText] = useState('{}'); const [probeExpression, setProbeExpression] = useState('$output != None'); const [probeKind, setProbeKind] = useState('assertion'); const [probePolicy, setProbePolicy] = useState('continue'); const [probeBoundary, setProbeBoundary] = useState('output'); const [previewText, setPreviewText] = useState('{}'); const [probePreview, setProbePreview] = useState<any>(null);
  const [probePointer, setProbePointer] = useState('');
  const [context, setContext] = useState<any>(null); const [contextLevel, setContextLevel] = useState('L2'); const [candidate, setCandidate] = useState('');
  const [showCreate, setShowCreate] = useState(false); const [newName, setNewName] = useState(''); const [newKind, setNewKind] = useState('python'); const [newParent, setNewParent] = useState('');
  const [createContract, setCreateContract] = useState('{"input":{"type":"object","properties":{},"additionalProperties":false},"output":{},"examples":[]}');
  const [cursor, setCursor] = useState(0); const [layoutMs, setLayoutMs] = useState(0); const [candidates, setCandidates] = useState<any[]>([]);
  const [projectEditor, setProjectEditor] = useState<string | null>(null);
  const [showTools, setShowTools] = useState(false);
  const [provider, setProvider] = useState('mock'); const [model, setModel] = useState(''); const [providerList, setProviderList] = useState<any[]>([]);
  const [probeId, setProbeId] = useState<string | null>(null); const [probeText, setProbeText] = useState('');
  const [connection, setConnection] = useState('Connecting');
  const closeCreate = useCallback(() => setShowCreate(false), []);
  const closeSettings = useCallback(() => setProjectEditor(null), []);
  const undo = useRef<any[]>([]); const redo = useRef<any[]>([]); const stream = useRef<AbortController | null>(null); const diagram = useReactFlow();
  const runSelection=useRef(0),runRequest=useRef<AbortController|null>(null);
  const dirty = !!project && json(project) !== json(draft);
  const graphModel = mode === 'Runs' && historyProject ? historyProject : draft;
  const graphModules = graphModel?.modules || [];
  const selectedModule = graphModules.find((m: any) => m.id === selected);
  const selectedChange = changes.find(c => c.id === changeId) || changes[0];
  const selectedBinding = draft?.bindings.find((b: any) => b.id === selectedEdge);
  const overlayAllowed = mode === 'Runs' || mode === 'Probes' && run?.revision === revision && !dirty;
  const visibleEvents = overlayAllowed ? (cursor ? events.filter(e => e.sequence <= cursor) : events) : [];
  const probeEvents = visibleEvents.filter(e => e.kind === 'probe.result');
  const failedProbes = probeEvents.filter(e => ['fail', 'error'].includes(e.data.status));
  const nodeEvents = visibleEvents.filter(e => e.module === selected);
  const latestOutput = nodeEvents.filter(e => e.kind === 'module.completed').at(-1)?.data.output || nodeEvents.filter(e => e.kind === 'composite.output').at(-1)?.data.capture;

  const act = useCallback(async (fn: () => Promise<void>) => { setError(''); setBusy(true); try { await fn(); } catch (err) { setError((err as Error).message); } finally { setBusy(false); } }, []);
  const refresh = useCallback(async () => {
    const [doc, runList, proposalList] = await Promise.all([api<{ project: ProjectSpec; revision: string; view: any }>('/project'), api('/runs'), api('/changes')]);
    setProject(doc.project); setDraft(clone(doc.project)); setRevision(doc.revision); setView({ ...emptyView, ...doc.view.view }); setViewRevision(doc.view.revision); setRuns(runList); setChanges(proposalList); setConnection('Connected');
    setInputText(json((doc.project.metadata as any)?.inputs?.success || {}));
    setSelected(current => current || (doc.project.modules || []).find(m => m.id === 'summarize')?.id || doc.project.modules?.[0]?.id || '');
    return { doc, runList };
  }, []);

  const selectRun = useCallback(async (id: string, switchMode = true) => {
    stream.current?.abort();runRequest.current?.abort();
    const generation=++runSelection.current,controller=new AbortController();runRequest.current=controller;
    let detail:any,eventList:any[];
    try{[detail,eventList]=await Promise.all([api('/runs/'+id,'GET',undefined,false,controller.signal),runEvents(id,controller.signal)]);}
    catch(error){if(controller.signal.aborted)return;throw error;}
    if(controller.signal.aborted||generation!==runSelection.current)return;
    setRun(detail); setHistoryProject(detail.graph); setEvents(eventList); setCursor(0);
    if (switchMode) setMode('Runs');
    if (['queued', 'running', 'paused'].includes(detail.status)) {
      stream.current = controller;
      void streamRun(id, event => {
        if(controller.signal.aborted||generation!==runSelection.current)return;
        setEvents(old => old.some(e => e.sequence === event.sequence) ? old : [...old, event]);
        if (event.kind === 'run.started') setRun((old: any) => ({ ...old, status: 'running' }));
        if (event.kind === 'control.paused') setRun((old: any) => ({ ...old, status: 'paused' }));
        if (event.kind === 'control.resumed') setRun((old: any) => ({ ...old, status: 'running' }));
        if (event.kind === 'run.finished') { setRun((old: any) => ({ ...old, ...event.data })); void api('/runs').then(values=>{if(generation===runSelection.current)setRuns(values);}); }
      }, controller.signal, eventList.at(-1)?.sequence || 0);
    }
  }, []);

  useEffect(() => { void act(async () => { const result = await refresh(); const params = new URLSearchParams(location.hash.slice(1)); if (params.get('module')) setSelected(params.get('module')!); const id = params.get('run') || result.runList[0]?.id; if (id) await selectRun(id, !!params.get('run')); }); return () => stream.current?.abort(); }, [act, refresh, selectRun]);
  useEffect(() => { document.documentElement.dataset.theme = view.theme; }, [view.theme]);
  useEffect(() => {
    void api('/providers').then(setProviderList).catch(() => {});
    const timer = window.setInterval(() => { void api('/studio').then(() => setConnection('Connected')).catch(() => setConnection('Disconnected · reopen with cdaf studio')); }, 10000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => { if (selectedModule) { setContractText(json(selectedModule.contract)); setModuleText(json(selectedModule)); const ex = selectedModule.contract.examples?.[0]; setPreviewText(json(ex?.output ?? {})); } setContext(null); setProbePreview(null); }, [selected, graphModel]);

  function edit(next: any) { undo.current.push(clone(draft)); redo.current = []; setDraft(next); setNotice('Draft updated · validate and review to apply'); }
  function undoEdit() { const previous = undo.current.pop(); if (previous) { redo.current.push(clone(draft)); setDraft(previous); } }
  function redoEdit() { const next = redo.current.pop(); if (next) { undo.current.push(clone(draft)); setDraft(next); } }
  function expand(id: string) { setView(v => ({ ...v, collapsed: v.collapsed.includes(id) ? v.collapsed.filter(x => x !== id) : [...v.collapsed, id] })); }
  useEffect(() => {
    if (!graphModel) return;
    let active = true;
    void layoutGraph(graphModel, view).then(result => { if (active) { setNodes(result.nodes as any); setEdges(result.edges as any); setLayoutMs(result.elapsed); setTimeout(() => diagram.fitView({ padding: .22, duration: 0 }), 50); } }).catch(err => setError(err.message));
    return () => { active = false; };
  }, [graphModel, view.collapsed, setNodes, setEdges]);

  const displayNodes = useMemo(() => {
    const active = focus !== 'off' && selected ? reachable(edges, selected, focus) : null;
    return nodes.map((node: any) => {
      const m = node.data.module; const event = visibleEvents.filter(e => e.module === node.id && (e.kind.startsWith('module.') || e.kind.startsWith('composite.'))).at(-1);
      const failed = visibleEvents.find(e => e.module === node.id && e.kind === 'probe.result' && ['fail', 'error'].includes(e.data.status));
      return { ...node, selected: node.id === selected, data: { ...node.data, onExpand: expand,
        status: mode === 'Runs' || mode === 'Probes' ? ({ input: 'started', output: 'completed' }[event?.kind.split('.')[1] as 'input' | 'output'] || event?.kind.split('.')[1]) : 'designed', quality: mode !== 'Architecture' ? failed?.data.status : null,
        probeCount: (graphModel?.probes || []).filter((p: any) => p.module === node.id).length,
        dim: !!search && !(m.id + m.name + m.description).toLowerCase().includes(search.toLowerCase()) || active && !active.has(node.id) } };
    });
  }, [nodes, edges, events, cursor, selected, search, focus, mode, graphModel, overlayAllowed]);
  const displayEdges = useMemo(() => edges.map((edge: any) => {
    const observed = (mode === 'Runs' || mode === 'Probes') && visibleEvents.some(e => e.binding === edge.id && e.kind === 'binding.transferred');
    const active = mode === 'Runs' && run?.status === 'running' && observed;
    return { ...edge, selected: edge.id === selectedEdge, animated: active && !matchMedia('(prefers-reduced-motion: reduce)').matches,
      markerEnd: { type: MarkerType.ArrowClosed, color: observed ? '#65d9b4' : '#52708a', width: 14, height: 14 },
      style: { stroke: observed ? '#65d9b4' : '#52708a', strokeWidth: observed ? 2 : 1.5, strokeDasharray: edge.data?.relation === 'migrated' ? '5 4' : undefined } };
  }), [edges, events, cursor, mode, run, selectedEdge, overlayAllowed]);

  function pick(id: string) { setSelected(id); setSelectedEdge(null); setInspector('Overview'); const params = new URLSearchParams(); params.set('module', id); if (mode === 'Runs' && run) params.set('run', run.id); history.replaceState(null, '', '#' + params); }
  function connect(connection: Connection) {
    if (mode !== 'Architecture') return;
    const source = draft.modules.find((m: any) => m.id === connection.source);
    const props = Object.keys(source.contract.output.properties || {});
    const pointer = props.length === 1 ? '/' + props[0] : '';
    edit({ ...draft, bindings: [...draft.bindings, { id: `binding_${crypto.randomUUID().slice(0, 8)}`, target: connection.target, port: connection.targetHandle || '', source: { kind: 'module', module: connection.source, pointer, value: null }, dynamic: false, visibility: 'L2', provenance: 'designed' }] });
    setNotice('Connection added to draft. Inspect its source pointer and validate the binding.');
  }
  async function updateModule(updated: any) { const next = { ...draft, modules: draft.modules.map((m: any) => m.id === selected ? updated : m) }; await api('/check', 'POST', next); edit(next); }
  async function validate() { const result = await api('/check', 'POST', draft); setDiagnostics(result.diagnostics); setNotice(result.valid ? 'Compilation passed · every required input has one source' : 'Compilation failed · inspect the diagnostics'); return result; }
  async function proposeDraft() { const result = await validate(); if (!result.valid) return; const change = await api('/changes/architecture', 'POST', { project: draft, base_revision: revision, title: 'Studio architecture edit' }); setChanges(await api('/changes')); setChangeId(change.id); setMode('Review'); setNotice('Proposal ready for review'); }
  async function saveLayout() { const positions = Object.fromEntries(nodes.map(n => [n.id, n.position])); const result = await api('/view', 'PUT', { view: { ...view, positions }, base_revision: viewRevision }); setView(result.view); setViewRevision(result.revision); setNotice('View saved · execution revision unchanged'); }
  async function startRun() {
    if (dirty) throw new Error('Review the architecture draft before running it');
    const input = JSON.parse(inputText);
    stream.current?.abort();runRequest.current?.abort();runSelection.current++; setMode('Runs'); setRun(null); setEvents([]); setCursor(0); setHistoryProject(null);
    const result = await api('/runs', 'POST', { input, base_revision: revision });
    for (let i = 0; i < 20; i++) { try { await selectRun(result.id, false); return; } catch { await new Promise(r => setTimeout(r, 150)); } }
    throw new Error('Run was queued; refresh the run list to inspect it');
  }
  async function addProbe() {
    const p = { id: `probe_${crypto.randomUUID().slice(0, 8)}`, module: selected, binding: selectedEdge, boundary: selectedEdge ? 'input' : probeBoundary, kind: probeKind, expression: probeExpression, policy: probePolicy, pointer: probePointer, enabled: true, language_version: 1, true_target: null, false_target: null };
    edit({ ...draft, probes: [...draft.probes, p] }); setNotice('Probe added to draft · review the architecture change to activate it');
  }
  function removeModule() {
    const ids = new Set([selected]);
    for (let count = 0; count < draft.modules.length; count++) draft.modules.forEach((module: any) => { if (ids.has(module.parent)) ids.add(module.id); });
    edit({ ...draft, modules: draft.modules.filter((module: any) => !ids.has(module.id)), probes: draft.probes.filter((probe: any) => !ids.has(probe.module)), bindings: draft.bindings.filter((binding: any) => !ids.has(binding.target) && !ids.has(binding.source.module)) });
    setSelected(''); setNotice('Module and contained subgraph removed from draft. Validate remaining public ports and guards before review.');
  }
  async function createModule() {
    const id = newName.trim(); if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(id) || draft.modules.some((m: any) => m.id === id)) throw new Error('Choose a unique Python identifier');
    const m = { id, name: id.replaceAll('_', ' '), description: '', kind: newKind, symbol: newKind === 'python' ? { path: `src/${id}.py`, qualname: id, digest: '' } : null,
      contract: JSON.parse(createContract), parent: newParent || null, outputs: {}, condition: newKind === 'decision' ? 'True' : null, guard: null, timeout_seconds: 30, retries: 0, idempotent: false, allowed_imports: ['json', 'math', 'typing', 'dataclasses', '__future__'], dependencies: [], side_effects: false };
    const next = { ...draft, modules: [...draft.modules, m] }; await api('/check', 'POST', next);
    edit(next); setSelected(id); setShowCreate(false); setNewName('');
  }
  useEffect(() => { const listener = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key === 'k') { e.preventDefault(); (document.querySelector('input[aria-label="Search modules"]') as HTMLInputElement)?.focus(); } if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !(e.target instanceof HTMLTextAreaElement) && !(e.target instanceof HTMLInputElement)) { e.preventDefault(); e.shiftKey ? redoEdit() : undoEdit(); } if (e.key === 'Escape') { setShowCreate(false); setProjectEditor(null); setSelectedEdge(null); } }; window.addEventListener('keydown', listener); return () => window.removeEventListener('keydown', listener); });

  if (!project) return error ? <ConnectionHelp error={error} retry={() => void act(refresh as any)} /> : <main className="loading"><h1>Contract-Driven AI Flow</h1><p>Opening your local project…</p></main>;

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href={projectPrefix ? '/' : '#'} onClick={e => { if (!projectPrefix) { e.preventDefault(); setMode('Architecture'); setShowTools(false); } }}><span className="brand-mark"><Icon name="flow" size={23} /></span><span>Contract Flow<small>Local code studio</small></span></a>
      <div className="workspace-label">LOCAL WORKSPACE <span className="online-dot" /></div><div className="project-card"><Icon name="layers" /><div><strong>{project.name.split(' · ')[0]}</strong><small>Python · {project.modules.length} modules</small></div></div>
      <div className="section-label">WORKBENCH</div><nav aria-label="Workbench">{MODES.map((item, i) => <button key={item} aria-label={item} className={!showTools && mode === item ? 'nav-item active' : 'nav-item'} onClick={() => { setMode(item); setShowTools(false); }}><Icon name={['flow', 'play', 'probe', 'review'][i]} /><span>{item}</span>{item === 'Review' && changes.filter(c => c.status === 'proposed').length > 0 && <em>{changes.filter(c => c.status === 'proposed').length}</em>}</button>)}</nav>
      <div className="section-label">MODULE EXPLORER <span>{graphModules.length}</span></div><div className="module-list">{graphModules.map((m: any) => <button key={m.id} className={'module-list-item ' + (m.id === selected ? 'active' : '')} style={{ paddingLeft: m.parent ? 27 : 12 }} onClick={() => pick(m.id)}><span className={'list-icon ' + m.kind}><Icon name={m.kind === 'composite' ? 'layers' : 'code'} size={14} /></span><span>{m.name || m.id}</span>{m.kind === 'composite' && <span onClick={e => { e.stopPropagation(); expand(m.id); }}>⌄</span>}</button>)}</div>
      <button className="add-module" onClick={() => { setMode('Architecture'); setShowCreate(true); }}><Icon name="plus" /> New module</button>
      <div className="sidebar-bottom">{projectPrefix && <a className="back-workspace" href="/?legacy=1">All projects</a>}<span className="local-badge">{connection} local session</span><div className="sidebar-version">CDAF <span>v0.2.0</span></div></div>
    </aside>

    <section className="workbench">
      <header className="topbar"><div className="breadcrumb">Workspace <Icon name="chevron" size={12} /> <strong>{project.name.split(' · ')[0]}</strong><span className="pill">{dirty ? 'UNREVIEWED DRAFT' : 'VERSIONED'}</span></div><div className="top-actions"><button className="icon-button" aria-label="Toggle theme" title="Toggle theme" onClick={() => setView(v => ({ ...v, theme: v.theme === 'dark' ? 'light' : 'dark' }))}><Icon name="sun" /></button><select aria-label="Export format" value="" onChange={e => void act(async () => { await download(e.target.value, mode === 'Runs' ? run?.id : undefined); setNotice('Sanitized export downloaded'); })}><option value="" disabled>Export ↗</option>{['html', 'svg', 'png', 'mermaid', 'json'].map(f => <option key={f}>{f}</option>)}</select><button aria-pressed={showTools} onClick={() => setShowTools(value => !value)}>Project tools</button></div></header>
      <div className="page-heading"><div><h1>{showTools ? 'Project tools.' : mode === 'Architecture' ? 'Design with clear boundaries.' : mode === 'Runs' ? 'Every run tells a story.' : mode === 'Probes' ? 'Observe what matters.' : 'Review before it changes.'}</h1><p>{showTools ? 'Inspect sources, manage local storage and find commands.' : mode === 'Architecture' ? 'Connect explicit ports. Review the contracts. Keep implementations bounded.' : mode === 'Runs' ? 'Follow the actual execution path, from input to quality checks.' : mode === 'Probes' ? 'Read-only observations with independent control policies.' : 'Architecture and implementation proposals share one reviewable history.'}</p></div><div className="heading-actions">{showTools ? <button onClick={() => setShowTools(false)}>Back to canvas</button> : mode === 'Architecture' ? <><button onClick={() => void act(async () => { await validate(); })} disabled={busy}><Icon name="check" /> Validate</button><button className="primary" onClick={() => void act(proposeDraft)} disabled={busy || !dirty}><Icon name="review" /> Review &amp; save</button></> : <button className="primary" onClick={() => void act(startRun)} disabled={busy || dirty}><Icon name="play" /> Run flow</button>}</div></div>
      <div className="mode-tabs"><Tabs items={MODES} value={mode} onChange={(value: Mode) => { setMode(value); setShowTools(false); }} label="Canvas mode" prefix="canvas-mode" /><span className="revision-label">{mode === 'Runs' && run ? 'RUN GRAPH ' + short(run.revision) : 'REV ' + short(revision)}{mode === 'Probes' && run && <span> · {overlayAllowed ? 'OBSERVATIONS RUN ' : 'NO MATCHING OVERLAY · RUN '}{short(run.id)}</span>}{dirty ? ' · draft' : ''}</span></div>
      {(error || notice) && <div className={'notice ' + (error ? 'error' : '')} role={error ? 'alert' : 'status'}><span>{error || notice}</span><button aria-label="Dismiss notification" onClick={() => { setError(''); setNotice(''); }}><Icon name="close" size={13} /></button></div>}
      <div className="canvas-toolbar" hidden={showTools}><label className="search"><Icon name="search" /><input placeholder="Search modules, contracts…" aria-label="Search modules" value={search} onChange={e => setSearch(e.target.value)} /><kbd>⌘ K</kbd></label><div className="canvas-tools"><select aria-label="Path focus" value={focus} onChange={e => setFocus(e.target.value as any)}><option value="off">All connections</option><option value="upstream">Upstream path</option><option value="downstream">Downstream path</option><option value="both">Connected component</option></select><button className="icon-button" aria-label="Undo architecture edit" title="Undo" onClick={undoEdit}><Icon name="undo" /></button><button className="icon-button redo" aria-label="Redo architecture edit" title="Redo" onClick={redoEdit}><Icon name="undo" /></button><button className="icon-button" aria-label="Fit graph" title="Fit graph" onClick={() => diagram.fitView({ padding: .22, duration: 0 })}><Icon name="fit" /></button><button onClick={() => void act(async () => { const result = await layoutGraph(graphModel, { ...view, positions: {} }); setNodes(result.nodes as any); setEdges(result.edges as any); setLayoutMs(result.elapsed); diagram.fitView({ padding: .22 }); })}>Auto layout</button><button onClick={() => void act(saveLayout)}>Save view</button></div></div>
      <div className="editor-body" id="canvas-mode-panel" role="tabpanel" aria-labelledby={`canvas-mode-${MODES.indexOf(mode)}`} hidden={showTools}>
        <div className="canvas-and-timeline">
          <div className="flow-canvas" data-testid="flow-canvas"><ReactFlow nodes={displayNodes} edges={displayEdges} onNodesChange={onNodesChange as any} onEdgesChange={onEdgesChange as any} nodeTypes={nodeTypes} onNodeClick={(_, n) => pick(n.id)} onEdgeClick={(_, e) => { setSelectedEdge(e.id); setSelected(e.target); }} onConnect={connect} nodesConnectable={mode === 'Architecture'} nodesDraggable={mode === 'Architecture'} edgesReconnectable={false} deleteKeyCode={null} minZoom={.15} maxZoom={1.8} fitView colorMode={view.theme === 'dark' ? 'dark' : 'light'} onlyRenderVisibleElements>
            <Background gap={24} size={1} color="var(--grid)" /><Controls showInteractive={false} /><MiniMap nodeColor={n => n.selected ? '#67dcbc' : '#3c5b70'} maskColor={view.theme === 'dark' ? '#0a151d99' : '#f1f5f799'} pannable zoomable ariaLabel="Graph overview" />
          </ReactFlow><div className="canvas-legend"><span><i className="line-key" /> Designed connection</span>{(mode === 'Runs' || mode === 'Probes') && <span><i className="line-key observed" /> Observed transfer</span>}<span>Static path = reachability</span></div></div>
          {mode === 'Runs' && <div className="timeline-panel"><div className="panel-heading"><strong><Icon name="play" /> Execution timeline</strong><select aria-label="Select run" value={run?.id || ''} onChange={e => void act(() => selectRun(e.target.value))}><option value="" disabled>Select run</option>{runs.map(r => <option key={r.id} value={r.id}>{short(r.id)} · {r.status} / {r.quality}</option>)}</select>{run && <span className={'quality-pill ' + run.quality}>{run.status} · quality {run.quality}</span>}</div><div className="timeline-controls"><small>{cursor ? 'Replay through event ' + cursor : 'All recorded events'} · {events.length} events</small><input type="range" aria-label="Replay timeline" min="0" max={events.length} value={cursor ? events.findIndex(e => e.sequence === cursor) + 1 : events.length} onChange={e => setCursor(Number(e.target.value) ? events[Number(e.target.value) - 1].sequence : events[0]?.sequence || 0)} /><button onClick={() => setCursor(0)}>Latest</button>{run && ['queued', 'running', 'paused'].includes(run.status) && <>{run.status !== 'queued' && <button onClick={() => void act(async () => { await api(`/runs/${run.id}/${run.status === 'paused' ? 'resume' : 'pause'}`, 'POST'); })}>{run.status === 'paused' ? 'Resume' : 'Pause'}</button>}<button className="danger" onClick={() => void act(async () => { await api(`/runs/${run.id}/cancel`, 'POST'); })}>Cancel</button></>}</div><div className="timeline-rows">{graphModules.filter((m: any) => m.kind !== 'composite').map((m: any) => { const e = visibleEvents.filter(x => x.module === m.id && x.kind.startsWith('module.')).at(-1); const duration = visibleEvents.find(x => x.module === m.id && x.kind === 'module.completed')?.data.duration_ms; return <button key={m.id} onClick={() => pick(m.id)}><span>{m.name || m.id}</span><div className="time-track"><i className={e?.kind.split('.')[1] || ''} style={{ width: `${Math.max(8, Math.min(95, (duration || 0) / 12))}%` }} /></div><small>{e?.kind.split('.')[1] || 'pending'}</small><time>{duration ? `${Math.round(duration)} ms` : '—'}</time></button>; })}</div></div>}
          {mode === 'Probes' && <div className="timeline-panel"><div className="panel-heading"><strong><Icon name="probe" /> Probe observations</strong><span>{failedProbes.length} checks need attention</span></div><div className="probe-results">{draft.probes.map((p: any) => { const result = probeEvents.filter(e => e.data.probe === p.id).at(-1); return <button key={p.id} onClick={() => { pick(p.module); setProbeId(p.id); setProbeText(json(p)); setProbeExpression(p.expression || 'True'); setProbeKind(p.kind); setProbePolicy(p.policy); setProbeBoundary(p.boundary); setProbePointer(p.pointer || ''); }}><span className={'result-dot ' + (result?.data.status || 'pending')} /><strong>{p.id}</strong><small>{p.module} · {p.kind}</small><code>{p.expression}</code><span>{result?.data.status || 'unobserved'}</span></button>; })}</div></div>}
          {mode === 'Review' && <div className="review-workspace"><div className="proposal-list"><div className="panel-heading"><strong>Change proposals</strong><span>{changes.length}</span></div>{changes.length === 0 && <p className="empty">Edit the architecture or generate a module to create a proposal.</p>}{changes.map(c => <button className={c.id === selectedChange?.id ? 'active' : ''} key={c.id} onClick={() => setChangeId(c.id)}><span className={'pill ' + c.status}>{c.status}</span><strong>{c.title}</strong><small>{c.kind} · {short(c.base_revision)}</small></button>)}</div><div className="diff-pane">{selectedChange && <><div className="panel-heading"><strong>{selectedChange.title}</strong><span>Base {short(selectedChange.base_revision)}</span></div>{selectedChange.diagnostics.map((d: any, i: number) => <p className="diagnostic error" key={i}>{d.code}: {d.message}</p>)}<pre className="diff">{(selectedChange.diff || 'No textual changes').split('\n').map((line: string, i: number) => <div key={i} className={line.startsWith('+') ? 'added' : line.startsWith('-') ? 'removed' : ''}>{line || ' '}</div>)}</pre><div className="review-actions">{selectedChange.status === 'proposed' && <><button onClick={() => void act(async () => { await api(`/changes/${selectedChange.id}/reject`, 'POST'); setChanges(await api('/changes')); })}>Reject proposal</button><button className="primary" onClick={() => void act(async () => { await api(`/changes/${selectedChange.id}/accept`, 'POST', { base_revision: revision }); await refresh(); setNotice('Accepted · validated changes applied atomically'); })}><Icon name="check" /> Accept reviewed change</button></>}{selectedChange.status === 'accepted' && selectedChange.kind !== 'architecture' && <button onClick={() => void act(async () => { const c = await api(`/changes/${selectedChange.id}/rollback`, 'POST'); setChanges(await api('/changes')); setChangeId(c.id); })}>Propose rollback</button>}</div></>}</div></div>}
          {diagnostics.length > 0 && mode === 'Architecture' && <div className="diagnostics"><div className="panel-heading"><strong>Compiler diagnostics</strong><button onClick={() => setDiagnostics([])}>Close</button></div>{diagnostics.map((d, i) => <button className={'diagnostic ' + d.severity} key={i} onClick={() => d.module && pick(d.module)}><strong>{d.code}</strong><span>{d.message}</span></button>)}</div>}
        </div>

        <aside className="inspector">
          <div className="inspector-title"><span className="eyebrow">{selectedEdge ? 'CONNECTION' : 'MODULE DETAILS'}</span><span className="pill">{selectedModule?.kind || 'workspace'}</span></div>
          <h2>{selectedModule?.name || selected || 'Flow settings'}</h2><p className="inspector-description">{selectedModule?.description || 'Select a node or a connection to inspect its contract and evidence.'}</p>
          {mode === 'Architecture' && selectedBinding ? <><label className="field"><span>Target port</span><input value={selectedBinding.port} onChange={e => edit({ ...draft, bindings: draft.bindings.map((b: any) => b.id === selectedEdge ? { ...b, port: e.target.value } : b) })} /></label><JsonEditor label="Explicit source binding" value={moduleText.startsWith('{') ? json(selectedBinding.source) : '{}'} onChange={value => { try { edit({ ...draft, bindings: draft.bindings.map((b: any) => b.id === selectedEdge ? { ...b, source: JSON.parse(value) } : b) }); } catch { setNotice('Use the module JSON editor for a multiline binding edit'); } }} rows={9} /><label className="checkbox"><input type="checkbox" checked={selectedBinding.dynamic} onChange={e => edit({ ...draft, bindings: draft.bindings.map((b: any) => b.id === selectedEdge ? { ...b, dynamic: e.target.checked } : b) })} /> Declare dynamic schema boundary</label><button className="danger" onClick={() => { edit({ ...draft, bindings: draft.bindings.filter((b: any) => b.id !== selectedEdge) }); setSelectedEdge(null); }}>Remove connection</button></> : mode === 'Probes' ? <>
            <div className="inspector-section"><strong>{probeId ? `Edit ${probeId}` : 'Add an observation'}</strong><p className="muted">Rules observe a boundary; policies decide whether execution continues.</p><label className="field"><span>Kind</span><select aria-label="Probe kind" value={probeKind} onChange={e => setProbeKind(e.target.value)}>{['assertion', 'metric', 'capture', 'branch_observer'].map(k => <option key={k}>{k}</option>)}</select></label><div className="field-row"><label className="field"><span>Boundary</span><select value={probeBoundary} onChange={e => setProbeBoundary(e.target.value)}><option>output</option><option>input</option></select></label><label className="field"><span>Policy</span><select value={probePolicy} onChange={e => setProbePolicy(e.target.value)}>{['continue', 'block', 'pause', 'breakpoint'].map(k => <option key={k}>{k}</option>)}</select></label></div><label className="field"><span>JSON Pointer (capture / metric)</span><input aria-label="Probe data pointer" value={probePointer} onChange={e => setProbePointer(e.target.value)} placeholder="/field (empty = whole boundary)" /></label><JsonEditor label="Probe expression" value={probeExpression} onChange={setProbeExpression} rows={3} /><JsonEditor label="Preview sample" value={previewText} onChange={setPreviewText} rows={5} /><div className="button-row"><button onClick={() => void act(async () => { setProbePreview(await api('/probes/preview', 'POST', { probe: { id: 'preview', module: selected, expression: probeExpression, kind: probeKind, boundary: probeBoundary, policy: probePolicy, pointer: probePointer }, input: probeBoundary === 'input' ? JSON.parse(previewText) : {}, output: probeBoundary === 'output' ? JSON.parse(previewText) : null })); })}>Preview rule</button>{probeId ? <button className="primary" disabled={!selectedModule} onClick={() => edit({ ...draft, probes: draft.probes.map((probe: any) => probe.id === probeId ? { ...probe, expression: probeExpression, kind: probeKind, policy: probePolicy, boundary: probeBoundary, pointer: probePointer } : probe) })}>Update selected probe</button> : <button className="primary" disabled={!selectedModule} onClick={() => void act(addProbe)}>Add to draft</button>}</div>{probePreview && <pre className={'preview-result ' + probePreview.status}>{json(probePreview)}</pre>}{probeId && <><label className="checkbox"><input type="checkbox" checked={draft.probes.find((probe: any) => probe.id === probeId)?.enabled ?? true} onChange={event => edit({ ...draft, probes: draft.probes.map((probe: any) => probe.id === probeId ? { ...probe, enabled: event.target.checked } : probe) })} /> Probe enabled</label><details><summary>Advanced probe fields and branch targets</summary><JsonEditor label="Selected probe JSON" value={probeText} onChange={setProbeText} rows={10} /><button onClick={() => void act(async () => { const probe = JSON.parse(probeText); if (probe.id !== probeId) throw new Error('Keep the probe ID stable'); edit({ ...draft, probes: draft.probes.map((item: any) => item.id === probeId ? probe : item) }); })}>Apply advanced probe fields</button></details><div className="button-row"><button onClick={() => setProbeId(null)}>New observation</button><button className="danger" onClick={() => { edit({ ...draft, probes: draft.probes.filter((probe: any) => probe.id !== probeId) }); setProbeId(null); }}>Remove selected probe</button></div></>}<button className="full-width" disabled={!dirty} onClick={() => void act(proposeDraft)}>Review probe changes</button></div>
          </> : <>
            <div className="inspector-tabs">{['Overview', 'Contract', 'Context'].map(tab => <button className={inspector === tab ? 'active' : ''} key={tab} onClick={() => setInspector(tab)}>{tab}</button>)}</div>
            {inspector === 'Contract' && selectedModule && <><JsonEditor label="Module contract JSON" value={contractText} onChange={setContractText} rows={18} /><button className="primary full-width" disabled={mode !== 'Architecture'} onClick={() => void act(async () => updateModule({ ...selectedModule, contract: JSON.parse(contractText) }))}>Update draft contract</button><p className="muted">Examples belong to the contract version. Source, ports and examples are reviewed together.</p></>}
            {inspector === 'Context' && selectedModule && <><label className="field"><span>Visibility preset</span><select value={contextLevel} onChange={e => setContextLevel(e.target.value)}>{['L1', 'L2', 'L3', 'L4'].map(l => <option key={l}>{l}</option>)}</select></label><button className="full-width" disabled={busy} onClick={() => void act(async () => setContext(await api(`/context/${selected}?level=${contextLevel}`)))}>Inspect exact context</button>{context && <><p className="muted">{context.bytes.toLocaleString()} bytes · ~{context.estimated_tokens} tokens · {context.entries.length} entries</p><pre className="context-json">{json(context)}</pre></>}<label className="field"><span>Generation provider</span><select value={provider} onChange={event => setProvider(event.target.value)}>{(providerList.length ? providerList : [{ id: 'mock', name: 'Offline contract fixtures', configured: true, installed: true }]).map(item => <option key={item.id} value={item.id}>{item.name}{item.configured && item.installed ? '' : ' (not configured)'}</option>)}</select></label>{provider !== 'mock' && <label className="field"><span>Explicit model name</span><input value={model} onChange={event => setModel(event.target.value)} placeholder="Model configured for this provider" /></label>}<button className="primary full-width" disabled={busy || provider !== 'mock' && (!model || !providerList.find(item => item.id === provider)?.configured || !providerList.find(item => item.id === provider)?.installed)} onClick={() => void act(async () => { const c = await api('/generate', 'POST', { module: selected, level: contextLevel, provider, model: model || null }); setChanges(await api('/changes')); setChangeId(c.id); setMode('Review'); })}>{provider === 'mock' ? 'Generate from offline fixtures' : 'Generate reviewed candidate'}</button>{provider !== 'mock' && <p className="muted">This sends the displayed context to the configured provider and may incur usage charges. Configure environment credentials in Project tools / Installation.</p>}<JsonEditor label="External AI candidate function" value={candidate} onChange={setCandidate} rows={8} /><button className="full-width" onClick={() => void act(async () => { const c = await api('/changes/implementation', 'POST', { module: selected, candidate }); setChanges(await api('/changes')); setChangeId(c.id); setMode('Review'); })}>Validate candidate &amp; review</button></>}
            {inspector === 'Overview' && <>
              {selectedModule && <><div className="inspector-section"><span className="section-label">BOUNDARY CONTRACT</span><div className="contract-ports">{Object.entries(selectedModule.contract.input.properties || {}).map(([key, val]: any) => <div key={key}><span className="port-dot" /><code>{key}</code><span>{val.type || 'dynamic'}</span><small>in</small></div>)}<div><span className="port-dot out" /><code>result</code><span>{selectedModule.contract.output.type || 'dynamic'}</span><small>out</small></div></div></div><div className="source-location"><Icon name="code" /><div><code>{selectedModule.symbol?.path || 'Compiled graph node'}</code><small>{selectedModule.symbol?.qualname || selectedModule.kind}</small></div></div></>}
              {mode === 'Runs' && <><div className="inspector-section"><span className="section-label">EXECUTION &amp; QUALITY</span><div className="evidence-stats"><div><strong>{nodeEvents.filter(e => e.kind === 'module.started').length}</strong><small>attempts</small></div><div><strong>{nodeEvents.filter(e => e.kind === 'probe.result').length}</strong><small>checks</small></div><div><strong>{nodeEvents.filter(e => e.kind === 'probe.result' && e.data.status === 'fail').length}</strong><small>failed</small></div></div>{nodeEvents.filter(e => e.kind === 'probe.result').map(e => <div className={'probe-result-card ' + e.data.status} key={e.sequence}><span>{e.data.status === 'pass' ? '✓' : '!'}</span><div><strong>{e.data.probe}</strong><small>{e.data.status} · {e.data.policy}</small></div></div>)}</div><div className="inspector-section"><span className="section-label">CAPTURED OUTPUT</span><pre>{latestOutput ? json(latestOutput) : 'No completed output at this replay position.'}</pre></div><details><summary>All node events ({nodeEvents.length})</summary><pre>{json(nodeEvents)}</pre></details></>}
              {mode !== 'Runs' && selectedModule && <><div className="inspector-section"><span className="section-label">MODULE POLICY</span><dl><dt>Timeout</dt><dd>{selectedModule.timeout_seconds} s</dd><dt>Automatic retries</dt><dd>{selectedModule.retries}</dd><dt>Side effects</dt><dd>{selectedModule.side_effects ? 'Declared' : 'None declared'}</dd><dt>Capture</dt><dd>{draft.capture.level}</dd></dl></div>{mode === 'Architecture' && <details className="advanced-editor"><summary>Edit module, group &amp; public ports</summary><JsonEditor label="Module specification JSON" value={moduleText} onChange={setModuleText} rows={18} /><button onClick={() => void act(async () => { const value = JSON.parse(moduleText); if (value.id !== selected) throw new Error('Module IDs stay stable; create a new module to change identity'); await updateModule(value); })}>Update module draft</button><button className="danger full-width" onClick={removeModule}>Remove module from draft</button></details>}</>}
              {mode === 'Architecture' && selectedModule && <InputBindings module={selectedModule} draft={draft} edit={edit} />}
              {mode === 'Architecture' && <button className="full-width" onClick={() => setProjectEditor(json(draft))}>Edit flow settings &amp; inputs</button>}
              <div className="inspector-section"><span className="section-label">NEXT RUN INPUT</span><JsonEditor label="Run input JSON" value={inputText} onChange={setInputText} rows={6} /><div className="button-row"><button onClick={() => setInputText(json(project.metadata?.inputs?.success || {}))}>Success fixture</button><button onClick={() => setInputText(json(project.metadata?.inputs?.failure || {}))}>Failure fixture</button></div><button className="primary full-width" disabled={dirty || busy} onClick={() => void act(startRun)}><Icon name="play" /> Run with this input</button></div>
            </>}
          </>}
        </aside>
      </div>
      <footer className="statusbar"><span>{connection} to local runtime</span><span>{graphModules.length} modules · {graphModel.bindings.length} bindings · ELK {layoutMs.toFixed(0)} ms</span><span>{mode === 'Runs' ? 'Historical graph · ' + short(run?.revision) : 'View changes preserve execution semantics'}</span></footer>
      {showTools && <ProjectTools project={project} revision={revision} refresh={async () => setRuns(await api('/runs'))} onProposal={async proposal => { setChanges(await api('/changes')); setChangeId(proposal.id); setMode('Review'); setShowTools(false); }} />}
    </section>

    {projectEditor !== null && <Dialog title="Flow settings" onClose={closeSettings}><div className="panel-heading"><h2>Flow settings</h2><button aria-label="Close flow settings" onClick={() => setProjectEditor(null)}><Icon name="close" /></button></div><JsonEditor label="Project specification JSON" value={projectEditor} onChange={setProjectEditor} rows={22} /><button className="primary" onClick={() => void act(async () => { const value = JSON.parse(projectEditor); await api('/check', 'POST', value); edit(value); setProjectEditor(null); })}>Update flow draft</button></Dialog>}
    {showCreate && <Dialog title="Create module" onClose={closeCreate}><div className="panel-heading"><h2>Create a module</h2><button aria-label="Close create module" onClick={() => setShowCreate(false)}><Icon name="close" /></button></div><p className="muted">Start with the public contract; acceptance creates a Python skeleton for reviewable implementation.</p><label className="field"><span>Module identifier</span><input autoFocus value={newName} onChange={e => setNewName(e.target.value)} placeholder="validate_order" /></label><div className="field-row"><label className="field"><span>Module kind</span><select value={newKind} onChange={e => setNewKind(e.target.value)}><option>python</option><option>composite</option><option>decision</option></select></label><label className="field"><span>Parent composite</span><select value={newParent} onChange={e => setNewParent(e.target.value)}><option value="">Top level</option>{draft.modules.filter((m: any) => m.kind === 'composite').map((m: any) => <option key={m.id} value={m.id}>{m.name || m.id}</option>)}</select></label></div><JsonEditor label="New module contract" value={createContract} onChange={setCreateContract} rows={8} /><details><summary onClick={() => void act(async () => setCandidates(await api('/candidates')))}>Import an existing Python symbol</summary>{candidates.map(c => <button className="candidate-row" key={c.symbol.path + c.symbol.qualname} onClick={() => { const base = c.symbol.qualname.replaceAll('.', '_'); const id = draft.modules.some((module: any) => module.id === base) ? base + '_' + crypto.randomUUID().slice(0, 8) : base; const m = { id, name: id, kind: 'python', symbol: c.symbol, contract: JSON.parse(createContract) }; edit({ ...draft, modules: [...draft.modules, m] }); setSelected(id); setShowCreate(false); }}><code>{c.symbol.path}:{c.symbol.qualname}</code><small>Candidate · dependencies require review</small></button>)}</details><div className="modal-actions"><button onClick={() => setShowCreate(false)}>Cancel</button><button className="primary" onClick={() => void act(async () => createModule())}>Add to architecture draft</button></div></Dialog>}
  </div>;
}
