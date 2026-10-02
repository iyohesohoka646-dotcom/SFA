import { useState } from 'react';
import { request } from '../client';
export function CommandPane() {
  const [command, setCommand] = useState('help'), [argumentsText, setArguments] = useState('{}'), [result, setResult] = useState<unknown>(), [busy, setBusy] = useState(false);
  return <div className="wb-full-pane"><div className="wb-view-toolbar"><strong>命令台</strong><code>cdaf research tui</code></div><div className="wb-scroll wb-form"><label>服务命令<input aria-label="服务命令" value={command} onChange={e => setCommand(e.target.value)} /></label><label>JSON 参数<textarea aria-label="命令参数" value={argumentsText} onChange={e => setArguments(e.target.value)} /></label><button disabled={busy} onClick={() => { setBusy(true); void Promise.resolve().then(() => JSON.parse(argumentsText)).then(body => request('/commands/' + encodeURIComponent(command), { method: 'POST', body })).then(setResult).catch(error => setResult({ status: 'error', error: error.message })).finally(() => setBusy(false)); }}>执行命令</button><pre className="wb-json">{result === undefined ? '' : JSON.stringify(result, null, 2)}</pre></div></div>;
}
