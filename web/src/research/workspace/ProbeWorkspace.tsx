import { memo, useEffect, useState } from 'react';
import { MatrixView } from '../MatrixView';
import { TableView } from '../TableView';
import { displayCell } from '../matrix-renderer';
import { renderers } from '../renderer-registry';
import { client } from '../client';
import type { SnapshotRef } from '../generated';
import type { ProbeOutput } from './generated';
import type { WorkspaceDocument } from './layout';
import { useSnapshot } from './evidence';
import { wb } from './WorkbenchClient';
import { ArtifactView } from './ArtifactView';
import { OperationView } from '../OperationView';
import type { ResearchState } from '../state';

export const ProbeWorkspace = memo(function ProbeWorkspace({ document, state, outputVersion, onSelectVersion, onEvaluate }: {
  document: WorkspaceDocument; state: ResearchState; outputVersion: string; onSelectVersion: (snapshot: SnapshotRef, pinned?: boolean) => void; onEvaluate: (id: string) => void;
}) {
  const { snapshot, error } = useSnapshot(document.reference.snapshot_id);
  const [mode, setMode] = useState('auto'), [history, setHistory] = useState<SnapshotRef[]>([]), [outputs, setOutputs] = useState<ProbeOutput[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false), [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const abort = new AbortController();
    if (snapshot) {
      void client.history(snapshot.run_id, snapshot.binding_id, undefined, abort.signal).then(setHistory).catch(() => {});
      void wb.outputs({ snapshot_id: snapshot.id }, abort.signal).then(setOutputs).catch(() => {});
    }
    return () => abort.abort();
  }, [snapshot?.id, refresh, outputVersion]);
  if (error) return <div className="wb-empty" role="alert">{error}</div>;
  if (!snapshot) return <div className="wb-empty" role="status">读取此版本数据…</div>;
  const plugin = renderers.resolve(snapshot.descriptor);
  const renderer = mode === 'auto' ? plugin ? 'plugin' : snapshot.sample.columns ? 'table' : snapshot.descriptor.shape ? 'matrix' : 'raw' : mode;
  const artifacts = outputs.filter(o => o.artifact_id);
  return <div className="wb-data-pane">
    <div className="wb-view-toolbar"><strong data-testid="matrix-definition"><span data-testid="current-variable">{snapshot.name}</span> <small>v{snapshot.version} · {snapshot.descriptor.shape?.join(' × ') ?? snapshot.descriptor.kind}</small></strong>
      <select aria-label="数据呈现" value={mode} onChange={e => setMode(e.target.value)}><option value="auto">自动</option><option value="matrix">热图</option><option value="table">数据表</option><option value="raw">纯数据</option>{plugin && <option value="plugin">{plugin.id}</option>}{artifacts.map(o => <option key={o.id} value={o.id}>{o.definition_id}</option>)}</select>
      <button aria-label="查看变量历史" aria-expanded={historyOpen} onClick={() => setHistoryOpen(!historyOpen)}>版本</button>
      <button onClick={() => { onEvaluate(snapshot.id); setRefresh(refresh + 1); }}>执行探针</button>
    </div>
    {historyOpen && <div className="wb-version-strip">{history.map(value => <button key={value.id} aria-label={'版本 ' + value.version} aria-pressed={value.id === snapshot.id} onClick={() => onSelectVersion(value)}>v{value.version}</button>)}<button onClick={() => onSelectVersion(snapshot, true)}>并排固定此版本</button></div>}
    <div className="wb-data-content">{artifacts.find(o => o.id === mode)?.artifact_id ? <ArtifactView id={artifacts.find(o => o.id === mode)!.artifact_id!} /> : renderer === 'plugin' && plugin ? <plugin.Component snapshot={snapshot} /> : renderer === 'matrix' && snapshot.descriptor.shape ? <MatrixView snapshot={snapshot} /> : renderer === 'table' && snapshot.sample.values ? <TableView snapshot={snapshot} /> : <pre className="wb-json" data-testid="raw-data">{snapshot.descriptor.kind === 'scalar' && Array.isArray(snapshot.sample.values) ? displayCell((snapshot.sample.values as unknown[][])[0]?.[0]) : JSON.stringify({ descriptor: snapshot.descriptor, sample: snapshot.sample, coverage: snapshot.coverage, fidelity: snapshot.fidelity }, null, 2)}</pre>}</div>
    {snapshot.run_id === state.runId && snapshot.operation_id && state.operations.has(snapshot.operation_id) && <details className="wb-operation-details"><summary>计算定义与解释</summary><OperationView operation={state.operations.get(snapshot.operation_id)} snapshots={state.snapshots} model={false} /></details>}
    <div className="wb-evidence-bar"><span>{snapshot.fidelity} · {snapshot.descriptor.backend}</span><span>{snapshot.redacted.length ? '已脱敏' : '已保存证据'} · {snapshot.run_id.slice(0, 8)}</span></div>
  </div>;
});
