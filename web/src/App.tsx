import {lazy, Suspense} from 'react';
import ResearchWorkbench from './research/ResearchWorkbench';
const LegacyWorkspace=lazy(()=>import('./Workspace'));
export default function App(){return new URLSearchParams(location.search).has('legacy')?<Suspense fallback={<main className="loading">打开架构工作台…</main>}><LegacyWorkspace/></Suspense>:<ResearchWorkbench/>;}
