import { useCallback, useEffect, useState } from 'react';
import { api, ApiError, projectPrefix } from './api';
import App from './LegacyApp';
import { ConnectionHelp, Tabs } from './components';
import { Maintenance, Installation, FeatureReference } from './tools';

const templates = [
  { id: 'blank', name: 'Blank project', detail: 'Define contracts and modules from the beginning.' },
  { id: 'data-pipeline', name: 'Data pipeline', detail: 'Four Python modules, typed bindings and quality probes.' },
  { id: 'business-flow', name: 'Business flow', detail: 'A local HTTP service and a real decision branch.' },
  { id: 'nested-composite', name: 'Nested composite', detail: 'Public ports, nested subgraphs and boundary evidence.' },
];

export default function Root() {
  const [mode, setMode] = useState<'loading' | 'workspace' | 'project' | 'error'>(projectPrefix ? 'project' : 'loading');
  const [error, setError] = useState('');
  const detect = useCallback(async () => {
    try { await api('/workspace', 'GET', undefined, true); setMode('workspace'); }
    catch (err) { if (err instanceof ApiError && err.status === 404) setMode('project'); else { setError((err as Error).message); setMode('error'); } }
  }, []);
  useEffect(() => { if (!projectPrefix) void detect(); }, [detect]);
  if (mode === 'project') return <App />;
  if (mode === 'workspace') return <Workspace />;
  if (mode === 'error') return <ConnectionHelp error={error} retry={() => void detect()} />;
  return <main className="loading"><h1>Opening Contract Flow Studio…</h1></main>;
}

function Workspace() {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState(''); const [notice, setNotice] = useState(''); const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState('Projects'); const [name, setName] = useState('My project'); const [template, setTemplate] = useState('data-pipeline');
  const [directory, setDirectory] = useState(''); const [openPath, setOpenPath] = useState(''); const [search, setSearch] = useState('');
  const refresh = useCallback(async () => setData(await api('/workspace', 'GET', undefined, true)), []);
  const act = async (fn: () => Promise<void>) => { setError(''); setBusy(true); try { await fn(); } catch (err) { setError((err as Error).message); } finally { setBusy(false); } };
  useEffect(() => { void act(refresh); }, [refresh]);
  const open = (id: string) => { location.href = `/p/${id}/?legacy=1`; };
  return <main className="workspace-home">
    <header className="workspace-header"><a className="workspace-brand" href="/">Contract Flow <span>Local Studio</span></a><div><button onClick={() => { const theme = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light'; document.documentElement.dataset.theme = theme; localStorage.setItem('cdaf-theme', theme); }} aria-label="Toggle theme">Theme</button><button disabled={busy} onClick={() => void act(refresh)}>Refresh projects</button></div></header>
    <div className="workspace-content"><h1>Your code, contracts and execution evidence.</h1><p className="workspace-intro">Open a project or begin with an executable example. All files stay on this computer.</p>
      <Tabs items={['Projects', 'Migration', 'Installation', 'Command reference']} value={tab} onChange={setTab} label="Workspace sections" prefix="workspace" />
      {error && <p className="notice error" role="alert">{error} <button onClick={() => setError('')}>Dismiss</button></p>}{notice && <p className="notice" role="status">{notice}</p>}
      <section id="workspace-panel" role="tabpanel" aria-labelledby={`workspace-${['Projects', 'Migration', 'Installation', 'Command reference'].indexOf(tab)}`}>
      {tab === 'Projects' && <div className="workspace-projects"><section className="project-index"><div className="project-index-heading"><h2>Projects</h2><input aria-label="Search projects" type="search" placeholder="Search by name or path" value={search} onChange={event => setSearch(event.target.value)} /></div>
        {!data && <p role="status">Loading your project catalogue…</p>}
        {data?.projects.filter((project: any) => (project.name + project.path).toLowerCase().includes(search.toLowerCase())).map((project: any) => <article className="project-row" key={project.id}><div><h3>{project.name}</h3><p>{project.path}</p><small>{project.available ? `${project.modules} modules` : project.problem || 'Project folder or flow.yaml is unavailable or invalid'}</small></div><div><button className="primary" disabled={!project.available || busy} onClick={() => open(project.id)}>Open project</button><button disabled={busy} onClick={() => void act(async () => { await api('/workspace/projects/' + project.id, 'DELETE', undefined, true); await refresh(); setNotice('Project unlinked. Its files remain on disk.'); })}>Unlink</button></div></article>)}
        {data?.projects.length === 0 && <p className="empty">Create a project or register an existing flow.yaml folder.</p>}
        <form className="open-project-form" onSubmit={event => { event.preventDefault(); void act(async () => { const project = await api('/workspace/open', 'POST', { path: openPath }, true); open(project.id); }); }}><h2>Open an existing folder</h2><label className="field"><span>Project folder containing flow.yaml</span><input value={openPath} onChange={event => setOpenPath(event.target.value)} placeholder="C:\\Projects\\my-project" required /></label><button disabled={busy}>Register &amp; open</button><small>Legacy .sfa projects can be previewed in Migration.</small></form>
      </section><form className="project-create-form" onSubmit={event => { event.preventDefault(); void act(async () => { const project = await api('/workspace/projects', 'POST', { name, template, path: directory || null }, true); open(project.id); }); }}><h2>Create a project</h2><label className="field"><span>Project name</span><input value={name} onChange={event => setName(event.target.value)} required maxLength={160} /></label><fieldset><legend>Starting point</legend>{templates.map(item => <label className={'template-option ' + (template === item.id ? 'selected' : '')} key={item.id}><input type="radio" name="template" value={item.id} checked={template === item.id} onChange={() => setTemplate(item.id)} /><span><strong>{item.name}</strong><small>{item.detail}</small></span></label>)}</fieldset><details><summary>Choose a storage folder</summary><label className="field"><span>Empty project directory (optional)</span><input value={directory} onChange={event => setDirectory(event.target.value)} placeholder="Use the local workspace by default" /></label></details><button className="primary" disabled={busy}>Create &amp; open project</button><p className="muted">Examples include success and failure inputs. Run them from the Runs view; opening a project does not execute code.</p></form></div>}
      {tab === 'Migration' && <Maintenance workspace onChanged={refresh} />}
      {tab === 'Installation' && <Installation workspace />}
      {tab === 'Command reference' && <FeatureReference features={data?.capabilities.features || []} />}
      </section><footer className="workspace-footer">{data?.home}<span>CLI: <code>cdaf projects list</code> · <code>cdaf studio</code></span></footer>
    </div>
  </main>;
}

