const hash = new URLSearchParams(location.hash.slice(1));
const session = hash.get('session');
export const projectPrefix = location.pathname.match(/^\/p\/[a-f0-9]+/)?.[0] || '';
if (session) {
  sessionStorage.setItem('cdaf-session', session);
  hash.delete('session');
  history.replaceState(null, '', location.pathname + location.search + (hash.size ? '#' + hash : ''));
}

export function headers() {
  return { Authorization: `Bearer ${sessionStorage.getItem('cdaf-session') || ''}`, 'Content-Type': 'application/json' };
}

export class ApiError extends Error {
  constructor(message: string, public status = 0) { super(message); }
}

export async function api<T = any>(path: string, method = 'GET', body?: unknown, workspace = false, signal?:AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch((workspace ? '' : projectPrefix) + '/api/v1' + path, { method, headers: headers(), body: body === undefined ? undefined : JSON.stringify(body),signal });
  } catch(error) { if(signal?.aborted)throw error;throw new ApiError('Local runtime is unavailable. Start it with cdaf studio, then retry.'); }
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiError(typeof detail.detail === 'string' ? detail.detail : JSON.stringify(detail.detail), response.status);
  }
  return response.json();
}

export async function download(format: string, runId?: string, archifyCheckout?: string) {
  const query = new URLSearchParams(runId ? { run_id: runId } : ['otel', 'archify', 'archify-json'].includes(format) ? {} : { current: 'true' });
  if (archifyCheckout) query.set('archify_checkout', archifyCheckout);
  const response = await fetch(projectPrefix + '/api/v1/export/' + format + '?' + query, { headers: headers() });
  if (!response.ok) throw new Error((await response.json()).detail);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url; link.download = 'contract-driven-ai-flow.' + format; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function runEvents(id: string, signal?:AbortSignal) {
  const events: any[] = []; let cursor = 0;
  for (;;) {
    const page = await api<any[]>(`/runs/${id}/events?after=${cursor}`,'GET',undefined,false,signal);
    events.push(...page);
    if (page.length < 10000) return events;
    cursor = page.at(-1).sequence;
  }
}

export async function streamRun(runId: string, receive: (event: any) => void, signal: AbortSignal, initialSequence = 0) {
  let cursor = initialSequence;
  let finished = false;
  while (!signal.aborted && !finished) {
    try {
      const response = await fetch(`${projectPrefix}/api/v1/runs/${runId}/events?stream=true&after=${cursor}`, { headers: { ...headers(), 'Last-Event-ID': String(cursor) }, signal });
      if (!response.ok || !response.body) throw new Error('Event stream unavailable');
      const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
      while (!signal.aborted) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const blocks = buffer.split('\n\n'); buffer = blocks.pop() || '';
        for (const block of blocks) {
          const line = block.split('\n').find(l => l.startsWith('data: '));
          if (line) { const event = JSON.parse(line.slice(6)); cursor = event.sequence; receive(event); if (event.kind === 'run.finished') finished = true; }
        }
      }
      if (!finished) {
        const run = await api(`/runs/${runId}`);
        if (!['queued', 'running', 'paused'].includes(run.status)) return;
      }
    } catch (error) { if (signal.aborted) return; }
    if (!finished) await new Promise(resolve => setTimeout(resolve, 800));
  }
}
