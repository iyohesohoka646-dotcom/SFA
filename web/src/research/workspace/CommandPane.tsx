import {useEffect,useRef,useState} from 'react';
import {Terminal} from '@xterm/xterm';
import {FitAddon} from '@xterm/addon-fit';
import {request} from '../client';
import type {TerminalSession} from './generated';
import '@xterm/xterm/css/xterm.css';

export function CommandPane(){
 const host=useRef<HTMLDivElement>(null),terminal=useRef<Terminal|null>(null),socket=useRef<WebSocket|null>(null);
 const [sessions,setSessions]=useState<TerminalSession[]>([]),[selected,setSelected]=useState(''),[profile,setProfile]=useState('shell'),[accessible,setAccessible]=useState(false),[status,setStatus]=useState('未连接'),[error,setError]=useState('');
 const key=useRef(''),interpreter=useRef<string|undefined>(undefined),profileTouched=useRef(false),selectionTouched=useRef(false);
 const create=async()=>{
  selectionTouched.current=true;setError('');try{const value=await request<TerminalSession>('/terminals',{method:'POST',body:{profile,interpreter:interpreter.current}});setSessions(s=>[...s.filter(v=>v.id!==value.id),value]);setSelected(value.id);if(key.current)localStorage.setItem(key.current,value.id);if(value.error)setError(value.error);}catch(e){setError((e as Error).message);}
 };
 useEffect(()=>{const abort=new AbortController();void Promise.all([request<{root:string}>('/info',{signal:abort.signal}),request<TerminalSession[]>('/terminals',{signal:abort.signal}),request<{interpreter:string}>('/workbench/configuration',{signal:abort.signal}),request<{values:{terminal:{profile:string}}}>('/workbench/settings',{signal:abort.signal})]).then(([info,list,config,settings])=>{if(abort.signal.aborted)return;key.current='cdaf-terminal:'+info.root;interpreter.current=config.interpreter||undefined;if(!profileTouched.current)setProfile(settings.values.terminal.profile);setSessions(s=>[...list,...s.filter(v=>!list.some(t=>t.id===v.id))]);const saved=localStorage.getItem(key.current);if(!selectionTouched.current)setSelected(list.find(s=>s.id===saved)?.id??list.filter(s=>s.status==='running').at(-1)?.id??'');}).catch(e=>{if(!abort.signal.aborted)setError(e.message);});return()=>abort.abort();},[]);
 useEffect(()=>{
  if(!selected||!host.current)return;
  const term=new Terminal({cursorBlink:true,convertEol:false,fontSize:13,fontFamily:'Consolas, monospace',scrollback:2000,screenReaderMode:false,theme:{background:'#11171b',foreground:'#d9e3e5'}});
  const fit=new FitAddon();term.loadAddon(fit);term.open(host.current);terminal.current=term;term.textarea?.setAttribute('aria-label','终端输入');
  let ended=false,frame=0,buffered='';const ws=new WebSocket((location.protocol==='https:'?'wss:':'ws:')+'//'+location.host+'/api/v1/research/terminals/'+encodeURIComponent(selected)+'/socket');socket.current=ws;
  const send=(value:unknown)=>{if(ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify(value));};
  const resize=()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(()=>{if(ended||!host.current?.clientHeight)return;fit.fit();send({type:'resize',rows:term.rows,cols:term.cols});});};
  setStatus('连接中');setError('');
  ws.onopen=()=>{send({type:'authenticate',token:sessionStorage.getItem('cdaf-session')??'',after:0});for(let i=0;i<buffered.length;i+=24000)send({type:'input',data:buffered.slice(i,i+24000)});buffered='';resize();term.focus();};
  ws.onmessage=e=>{try{const value=JSON.parse(e.data);if(value.type==='error'){setError(value.error);return;}if(value.truncated)term.writeln('\r\n[较早输出已省略]\r\n');if(value.data)term.write(value.data);setStatus(value.status==='running'?'运行中':'已结束');if(value.error)setError(value.error);setSessions(s=>s.map(item=>item.id===selected?{...item,status:value.status}:item));}catch{setError('终端响应无法读取');}};
  ws.onerror=()=>setError('终端连接失败，可重新连接');ws.onclose=()=>{if(!ended)setStatus('连接已断开');};
  const input=term.onData(data=>{if(ws.readyState===WebSocket.CONNECTING){if(buffered.length+data.length<=65536)buffered+=data;else setError('连接期间输入超出缓存，请重试');return;}for(let i=0;i<data.length;i+=24000)send({type:'input',data:data.slice(i,i+24000)});});
  term.attachCustomKeyEventHandler(e=>{if(e.type==='keydown'&&(e.ctrlKey||e.metaKey)&&e.shiftKey&&e.key.toLowerCase()==='c'){void navigator.clipboard.writeText(term.getSelection()).catch(()=>setError('复制失败，请使用浏览器复制菜单'));return false;}return true;});
  const observer=new ResizeObserver(resize);observer.observe(host.current);resize();
  return()=>{ended=true;cancelAnimationFrame(frame);observer.disconnect();input.dispose();ws.close();term.dispose();terminal.current=null;socket.current=null;};
 },[selected]);
 useEffect(()=>{if(terminal.current)terminal.current.options.screenReaderMode=accessible;},[accessible]);
 const choose=(id:string)=>{selectionTouched.current=true;setSelected(id);if(key.current)localStorage.setItem(key.current,id);};
 return <div className="wb-full-pane terminal-pane"><div className="wb-view-toolbar"><strong>终端</strong><select aria-label="终端配置" value={profile} onChange={e=>{profileTouched.current=true;setProfile(e.target.value);}}><option value="shell">系统 Shell</option><option value="python">Python</option><option value="cli">应用 CLI</option></select><button onClick={()=>void create()}>新建终端</button><select aria-label="终端会话" value={selected} onChange={e=>choose(e.target.value)}><option value="">选择会话</option>{sessions.map(s=><option key={s.id} value={s.id}>{s.profile} · {s.id.slice(0,6)} · {s.status}</option>)}</select><button disabled={!selected} onClick={()=>{setSelected('');requestAnimationFrame(()=>setSelected(selected));}}>重新连接</button><button disabled={!selected} onClick={()=>void request<TerminalSession>('/terminals/'+selected+'/end',{method:'POST'}).then(s=>{setSessions(old=>old.map(v=>v.id===s.id?s:v));setStatus('已结束');}).catch(e=>setError(e.message))}>结束会话</button><label><input type="checkbox" aria-label="无障碍输出" checked={accessible} onChange={e=>setAccessible(e.target.checked)}/>无障碍</label><small role="status">{status}</small></div>{error&&<div role="alert" className="wb-error">{error}</div>}<div ref={host} className="terminal-screen" aria-label="真实终端"/>{!selected&&<div className="terminal-empty"><button onClick={()=>void create()}>启动 {profile==='cli'?'应用 CLI':profile==='python'?'Python':'Shell'}</button></div>}</div>;
}
