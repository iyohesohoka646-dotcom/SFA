import { useEffect, useRef } from 'react';
import type { ReactNode } from 'react';

export function Tabs({ items, value, onChange, label, prefix }: { items: string[]; value: string; onChange: (value: any) => void; label: string; prefix: string }) {
  return <div role="tablist" aria-label={label} className="accessible-tabs">{items.map((item, index) => <button key={item} id={`${prefix}-${index}`} type="button" role="tab" aria-label={item} aria-selected={value === item} aria-controls={`${prefix}-panel`} tabIndex={value === item ? 0 : -1} className={value === item ? 'active' : ''} onClick={() => onChange(item)} onKeyDown={event => {
    const next = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? (index + 1) % items.length : event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? (index + items.length - 1) % items.length : event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : -1;
    if (next !== -1) { event.preventDefault(); onChange(items[next]); document.getElementById(`${prefix}-${next}`)?.focus(); }
  }}>{item}</button>)}</div>;
}

export function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.querySelector<HTMLElement>('button, input, select, textarea, [tabindex="0"]')?.focus();
    function keyboard(event: KeyboardEvent) {
      if (event.key === 'Escape') { event.preventDefault(); onClose(); }
      if (event.key !== 'Tab') return;
      const controls = [...(panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href],[tabindex="0"]') || [])].filter(node => node.offsetParent !== null);
      if (!controls.length) { event.preventDefault(); return; }
      const first = controls[0], last = controls.at(-1)!;
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    document.addEventListener('keydown', keyboard);
    return () => { document.removeEventListener('keydown', keyboard); previous?.focus(); };
  }, [onClose]);
  return <div className="modal-backdrop"><section className="modal" ref={panel} role="dialog" aria-modal="true" aria-label={title}>{children}</section></div>;
}

export function ConnectionHelp({ error, retry }: { error: string; retry: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  return <main className="connection-help"><h1>Connect to your local Studio</h1><p role="alert">{error}</p><p>Run <code>cdaf studio</code> or open your Studio shortcut. It starts the service and opens a fresh local session.</p><button className="primary" onClick={retry}>Retry connection</button><form onSubmit={event => {
    event.preventDefault();
    try {
      const url = new URL(input.current?.value || '');
      if (url.origin !== location.origin || !new URLSearchParams(url.hash.slice(1)).get('session')) throw new Error();
      location.href = url.href; location.reload();
    } catch { input.current?.setCustomValidity('Paste the session URL for this local server, including #session=…'); input.current?.reportValidity(); }
  }}><label className="field"><span>Session URL from the terminal</span><input ref={input} type="url" onChange={event => event.target.setCustomValidity('')} placeholder={`${location.origin}/#session=…`} required /></label><button>Open session</button></form></main>;
}
