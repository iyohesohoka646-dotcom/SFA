import {lazy, Suspense,useState} from 'react';
import ResearchWorkbench from './research/ResearchWorkbench';
import {ServiceControl} from './runtime/lifecycle';
const LegacyWorkspace=lazy(()=>import('./Workspace'));
const ProjectWorkbench=lazy(()=>import('./research/projects/ProjectWorkbench'));
export default function App(){const [single,setSingle]=useState(new URLSearchParams(location.search).has('single'));return <><ServiceControl/>{new URLSearchParams(location.search).has('legacy')?<Suspense fallback={<main className="loading">打开架构工作台…</main>}><LegacyWorkspace/></Suspense>:single?<><button className="project-return" onClick={()=>setSingle(false)}>打开项目工作台</button><ResearchWorkbench/></>:<Suspense fallback={<main className="loading">打开项目工作台…</main>}><ProjectWorkbench onLegacy={()=>setSingle(true)}/></Suspense>}</>;}
