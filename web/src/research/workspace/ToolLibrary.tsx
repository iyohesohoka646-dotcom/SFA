import { useEffect, useState } from 'react';
import { wb, type PublicTool } from './WorkbenchClient';
import type { TaskRecord } from './generated';

export function ToolLibrary({ interpreter, tasks, onTask, onError }: { interpreter: string; tasks: TaskRecord[]; onTask: (task: TaskRecord) => void; onError: (message: string) => void }) {
  const [tools, setTools] = useState<PublicTool[]>([]), [query, setQuery] = useState('');
  const version = tasks.filter(t => t.kind.startsWith('tools.') && t.status === 'completed').map(t => t.id).join('|');
  useEffect(() => { const abort = new AbortController(); void wb.tools(abort.signal).then(setTools).catch(error => { if (!abort.signal.aborted) onError(error.message); }); return () => abort.abort(); }, [version]);
  const submit = (operation: Promise<TaskRecord>) => void operation.then(onTask).catch(error => onError(error.message));
  return <div className="wb-full-pane"><div className="wb-view-toolbar"><strong>绘图工具</strong><input type="search" aria-label="搜索绘图工具" placeholder="搜索" value={query} onChange={e => setQuery(e.target.value)} /><button onClick={() => submit(wb.scanTools(interpreter))}>检测工具</button></div>
    <div className="wb-scroll"><table className="wb-catalog"><thead><tr><th>工具</th><th>适配</th><th>当前环境</th><th>产物</th><th>管理</th></tr></thead><tbody>{tools.filter(t => (t.label + ' ' + t.format).toLowerCase().includes(query.toLowerCase())).map(tool => <tr key={tool.id}><td><a href={tool.url} target="_blank" rel="noreferrer">{tool.label}</a></td><td>{tool.adapter_status === 'implemented' ? '可使用' : '待适配'}</td><td title={tool.interpreter ?? ''}>{tool.available ? tool.version + (tool.managed ? ' · 托管' : ' · 已安装') : '未检测到'}</td><td>{tool.format}</td><td><button onClick={() => submit(wb.installTool(tool.id))}>安装到工具环境</button><button onClick={() => void wb.disableTool(tool.id, tool.enabled).then(setTools).catch(e => onError(e.message))}>{tool.enabled ? '停用' : '启用'}</button>{tool.managed && <button onClick={() => submit(wb.removeTool(tool.id))}>卸载</button>}</td></tr>)}</tbody></table></div>
  </div>;
}
