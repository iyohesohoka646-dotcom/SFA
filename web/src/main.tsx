import React from 'react';
import ReactDOM from 'react-dom/client';
import { ReactFlowProvider } from '@xyflow/react';
import Root from './App';
import '@xyflow/react/dist/style.css';
import './style.css';
import './workspace.css';

document.documentElement.dataset.theme = localStorage.getItem('cdaf-theme') || (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><ReactFlowProvider><Root /></ReactFlowProvider></React.StrictMode>);

