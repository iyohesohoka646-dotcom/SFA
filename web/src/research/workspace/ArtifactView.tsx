import { useEffect, useRef, useState } from 'react';
import { wb } from './WorkbenchClient';

export function ArtifactView({ id }: { id: string }) {
  const [url, setUrl] = useState(''), [mime, setMime] = useState(''), [error, setError] = useState('');
  const target = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const abort = new AbortController(); let owned = '', view: { finalize: () => void } | undefined;
    setError(''); setUrl(''); setMime('');
    void wb.artifact(id, abort.signal).then(async blob => {
      if (abort.signal.aborted) return;
      setMime(blob.type);
      if (blob.type.includes('vegalite')) {
        const spec = JSON.parse(await blob.text());
        const remote = (value: unknown): boolean => !!value && typeof value === 'object' && Object.entries(value).some(([k, v]) => k === 'url' || remote(v));
        if (remote(spec)) throw new Error('绘图规范包含外部数据地址');
        const { default: embed } = await import('vega-embed');
        if (!abort.signal.aborted && target.current) view = (await embed(target.current, spec, { actions: false, renderer: 'canvas' })).view;
      } else { owned = URL.createObjectURL(blob); setUrl(owned); }
    }).catch(error => { if (!abort.signal.aborted) setError(error.message); });
    return () => { abort.abort(); view?.finalize(); if (owned) URL.revokeObjectURL(owned); };
  }, [id]);
  if (error) return <div className="wb-empty" role="alert">{error}</div>;
  return <div className="artifact-view" ref={target}>{url && (mime.startsWith('image/') ? <img src={url} alt="绘图探针产物" /> : <iframe title="交互绘图探针产物" src={url} sandbox="allow-scripts" />)}{!url && !mime && <div className="wb-empty" role="status">读取绘图产物…</div>}</div>;
}
