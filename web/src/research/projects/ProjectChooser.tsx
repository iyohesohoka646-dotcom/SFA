import {useEffect,useRef,useState} from 'react';
import type {ResearchProject} from './generated';

const FolderIcon=({size=20}:{size?:number})=><svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" aria-hidden="true"><path d="M3 7V5h6l2 2h10v13H3Z"/><path d="M3 10h18"/></svg>;

export function ProjectChooser({recent,recentError,folder,onFolder,onOpen,onChoose,onRecent,onLegacy,busy,nativePicker,manualRequest=0}: {
 recent:ResearchProject[];recentError:string;folder:string;onFolder:(value:string)=>void;
 onOpen:()=>void;onChoose:()=>void;onRecent:(id:string)=>void;onLegacy?:()=>void;
 busy:boolean;nativePicker:boolean;manualRequest?:number;
}){
 const [manual,setManual]=useState(false);
 const input=useRef<HTMLInputElement>(null);
 useEffect(()=>{if(manual)input.current?.focus();},[manual]);
 useEffect(()=>{if(manualRequest){setManual(true);input.current?.focus();}},[manualRequest]);
 return <main className="project-host-chooser" aria-label="Open a research project">
  <header className="project-welcome-heading"><h1>Scientific Dataflow Inspector</h1><p>Python research workspace</p></header>
  <div className="project-welcome-columns">
   <section className="project-welcome-start" aria-labelledby="project-start-heading">
    <h2 id="project-start-heading">Start</h2>
    <button className="project-welcome-action" aria-label="Open folder" disabled={busy} onClick={()=>nativePicker?onChoose():setManual(true)}><FolderIcon/><span>Open folder…</span></button>
    {onLegacy&&<button className="project-welcome-action secondary" onClick={onLegacy}><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M6 3h8l4 4v14H6Z"/><path d="M14 3v5h5M9 12h6M9 16h6"/></svg><span>Single-file workspace</span></button>}
    <details className="project-welcome-path" open={manual} onToggle={event=>setManual(event.currentTarget.open)}>
     <summary>Enter folder path</summary>
     <form onSubmit={event=>{event.preventDefault();onOpen();}}>
      <label className="project-host-field"><span>Folder path</span><input ref={input} value={folder} onChange={event=>onFolder(event.target.value)} placeholder="C:\research\my-project" autoComplete="off" spellCheck={false} required/></label>
      <button className="project-host-button project-host-open" disabled={busy||!folder.trim()} type="submit">Open project</button>
     </form>
    </details>
    {nativePicker&&<p className="project-welcome-shortcut"><kbd>Ctrl K</kbd><kbd>Ctrl O</kbd><span>Open folder</span></p>}
   </section>
   <section className="project-host-recent" aria-labelledby="project-recent-heading">
    <h2 id="project-recent-heading">Recent</h2>
    {recentError?<p role="alert" className="project-host-error-text">{recentError}</p>:recent.length===0?<div className="project-welcome-empty"><FolderIcon size={30}/><p>No recent projects</p><span>Your opened folders will appear here.</span></div>:<ul>{recent.map(item=><li key={item.id}><button disabled={busy} onClick={()=>onRecent(item.id)} title={item.root}><FolderIcon size={18}/><span className="project-recent-name"><strong>{item.name||item.id}</strong><span className="project-recent-path">{item.root}</span></span>{!item.latest_revision_id&&<em>Not indexed</em>}</button></li>)}</ul>}
   </section>
  </div>
  <footer className="project-welcome-footer">Local workspace<span>Import only · Run when you choose</span></footer>
 </main>;
}
