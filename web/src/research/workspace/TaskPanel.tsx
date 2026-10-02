import { useState } from 'react';
import type { ProbeOutput, TaskRecord } from './generated';
import { wb } from './WorkbenchClient';
import { RunTimeline } from '../RunTimeline';
import type { ResearchState } from '../state';
import { client } from '../client';

export function TaskPanel({ tasks, outputs, state, onContext, onChange, onOutput, onSnapshot, onError }: {
  tasks: TaskRecord[]; outputs: ProbeOutput[]; onContext: (id: string) => void; onChange: (id: string) => void;
  state: ResearchState; onSnapshot: (id: string) => void; onOutput: (output: ProbeOutput) => void; onError: (message: string) => void;
}) {
  const [mode, setMode] = useState('tasks');
  return <div className="wb-full-pane"><div className="wb-view-toolbar"><button aria-pressed={mode === 'tasks'} onClick={() => setMode('tasks')}>任务</button><button aria-pressed={mode === 'outputs'} onClick={() => setMode('outputs')}>探针结果 · {outputs.length}</button><button aria-pressed={mode === 'events'} onClick={() => setMode('events')}>运行事件</button></div><div className="wb-scroll">
    {mode === 'events' ? <RunTimeline runId={state.runId} live={state.timeline} onSnapshot={onSnapshot} /> : mode === 'tasks' ? tasks.map(task => <div key={task.id} data-testid="task-record" className={'wb-task-row ' + task.status}><strong>{task.kind}<span>{task.status}</span></strong><small>{task.calculation_status && '计算 ' + task.calculation_status + ' · '}{task.message || task.run_id?.slice(0, 8)} · {task.output_ids.length} 项结果</small>
      {['queued', 'running'].includes(task.status) && <button onClick={() => void wb.cancel(task.id).catch(e => onError(e.message))}>取消任务</button>}
      {task.run_id && task.status === 'running' && (task.calculation_status === 'paused' || task.run_id === state.runId && state.status === 'paused') && <button onClick={() => void client.control(task.run_id!, 'resume').catch(e => onError(e.message))}>继续计算</button>}
      {task.run_id === state.runId && state.status === 'paused' && <span className="wb-paused-gate">{state.timeline.filter(e => e.kind === 'probe.evaluated').slice(-4).map(e => { const r = e.payload.result as {status?:string;message?:string} | undefined; return r && r.status !== 'pass' ? <small key={e.sequence}>{r.status} · {r.message}</small> : null; })}</span>}
      {typeof task.receipt.context_id === 'string' && <button onClick={() => onContext(task.receipt.context_id as string)}>查看智能结果</button>}
      {Array.isArray(task.receipt.proposal_ids) && task.receipt.proposal_ids.map(id => <button key={String(id)} onClick={() => onChange(String(id))}>审查代码提案</button>)}
      {Object.keys(task.receipt).length > 0 && <details><summary>详情</summary><pre className="wb-json">{JSON.stringify(task.receipt, null, 2)}</pre></details>}
    </div>) : outputs.map(output => <button className={'wb-result-row ' + output.status} key={output.id} onClick={() => onOutput(output)}><strong>{output.definition_id}<span>{output.status}</span></strong><small>{output.message} · {output.execution} · {output.fidelity}</small></button>)}
    {!tasks.length && mode === 'tasks' && <div className="wb-empty">暂无任务</div>}
  </div></div>;
}
