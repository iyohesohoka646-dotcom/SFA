import React from 'react';
import ReactDOM from 'react-dom/client';
import { ReactFlowProvider } from '@xyflow/react';
import Root from './App';
import '@xyflow/react/dist/style.css';
import './style.css';
import './workspace.css';
import {renderers} from './research/renderer-registry';
import {registerPointCloudRenderer} from './research/PointCloudView';
import {RenderBoundary} from './runtime/RenderBoundary';

registerPointCloudRenderer(renderers);

try { document.documentElement.dataset.theme = localStorage.getItem('cdaf-theme') || (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'); }
catch { document.documentElement.dataset.theme = 'light'; }
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><RenderBoundary><ReactFlowProvider><Root /></ReactFlowProvider></RenderBoundary></React.StrictMode>);

