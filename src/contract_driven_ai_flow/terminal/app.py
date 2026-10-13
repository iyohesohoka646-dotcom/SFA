from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

from textual.app import App,ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal,Vertical
from textual.widgets import Header,Footer,Input,Static,DataTable,RichLog

from ..application.commands import CommandResult,HELP
from .commands import parse_command
from .views import safe_text,variable_row


def should_open_terminal(input_tty,output_tty,json_requested):
    return input_tty and output_tty and not json_requested


class ResearchTerminal(App):
    TITLE='Scientific Dataflow Inspector'
    CSS='''Screen {background: #0c1720; color: #e5eef2;} #status {height:3; padding:1; background:#11222e;} #body {height:1fr;} #variables {width:45%; border:solid #29414f;} #output {width:55%; border:solid #29414f;} #command {dock:bottom; border:solid #7be0c2;} #suggestions {height:2; color:#a7becb; padding:0 1;}'''
    BINDINGS=[Binding('ctrl+c','cancel_or_quit','取消／退出',priority=True),Binding('ctrl+q','quit_terminal','退出',priority=True)]

    def __init__(self,service_client):
        super().__init__();self.client=service_client;self.script='';self.interpreter='';self.run_id=None;self.operation_id=None;self.project_id=None;self.run_project_id=None;self._run_owner_bound=False;self._paint_timer=None;self._terminal_closing=False;self.last_result=CommandResult(status='ok');self.values={};self._commands=set();self._stream=None;self._last_interrupt=0;self._dirty=False;self._closed=False

    def compose(self)->ComposeResult:
        yield Header()
        yield Static('本地科研终端 · /help 查看命令 · 模型默认为离线规则',id='status',markup=False)
        with Horizontal(id='body'):
            yield DataTable(id='variables',cursor_type='row')
            yield RichLog(id='output',max_lines=500,wrap=True,markup=False,highlight=False)
        yield Static('/open  /run  /vars  /probe  /model  /workbench  /project  /help  /quit',id='suggestions',markup=False)
        yield Input(placeholder='/open "已有分析.py"',id='command')
        yield Footer()

    def on_mount(self):
        self.query_one('#variables',DataTable).add_columns('变量','形状','类型','版本','证据')
        self.query_one('#command',Input).focus()
        self._paint_timer=self.set_interval(.1,self.paint_values)
        self.query_one('#output',RichLog).write(HELP)

    def on_input_changed(self,event:Input.Changed):
        token=event.value.split(' ',1)[0]
        matches=[word for word in ('/open','/run','/runs','/resume','/vars','/inspect','/probe','/model','/explain','/project','/help','/quit') if word.startswith(token)]
        self.query_one('#suggestions',Static).update('  '.join(matches) if token else '/help 查看命令；Ctrl+C 取消当前任务')

    def on_input_submitted(self,event:Input.Submitted):
        text=event.value;event.input.value=''
        try:name,arguments=parse_command(text)
        except (ValueError,KeyError):self.query_one('#output',RichLog).write('命令参数无效；/help 查看格式。');return
        if name=='quit':self.action_quit_terminal();return
        if name in ('run','probe.add'):
            arguments.setdefault('script',self.script)
            if self.interpreter:arguments.setdefault('interpreter',self.interpreter)
        if name in ('vars','resume','continue','cancel'):arguments.setdefault('run_id',self.run_id)
        owner=self._run_owner() if name!='runs' else self.project_id
        if owner and name in ('vars','inspect','cancel','continue','resume','runs'):arguments.setdefault('project_id',owner)
        if name=='models.test':arguments['operation_id']=uuid.uuid4().hex
        if name in ('explain','explanation-context'):arguments.setdefault('operation_id',self.operation_id);arguments['request_id']=uuid.uuid4().hex
        self._commands={worker for worker in self._commands if worker.is_running}
        worker=self.run_worker(self.execute(name,arguments),name=name,group='commands',exit_on_error=False)
        self._commands.add(worker)

    async def execute(self,name,arguments):
        if name=='project.run':arguments={**arguments,'follow_live':True}
        result=await self.client.command(name,arguments);self.last_result=result
        project_scope=arguments.get('project_id')
        self.query_one('#output',RichLog).write(safe_text(result.model_dump(mode='json')))
        if result.status!='ok':return
        if name=='open':self.script=result.data['script'];self.interpreter=result.data['interpreter'];self.query_one('#status',Static).update('脚本：'+safe_text(self.script,256))
        if name=='inspect':self.operation_id=result.data.get('operation_id')
        if name=='project.open':self.project_id=result.data.get('id')
        elif name.startswith('project.') and result.project_id:self.project_id=result.project_id
        if name in ('run','resume'):
            self.run_project_id=project_scope;self._run_owner_bound=True
            self.run_id=result.run_id;self.values={};self._dirty=True
            if name=='resume':
                for value in result.data['snapshots']:self.values[value['binding_id']]=value
            if self._stream:self._stream.cancel()
            self._stream=self.run_worker(self.follow_run(self.run_id,result.data.get('cursor',0),project_scope),name='events',group='events',exclusive=True,exit_on_error=False)
        elif name=='vars':
            self.values={v['binding_id']:v for v in result.data};self._dirty=True
        elif name=='project.run':
            self.project_id=result.project_id
            self.run_project_id=result.project_id;self._run_owner_bound=True
            self.run_id=result.run_id;self.values={};self._dirty=True
            if self._stream:self._stream.cancel()
            if self.run_id:self._stream=self.run_worker(self.follow_run(self.run_id,0,self.project_id),name='events',group='events',exclusive=True,exit_on_error=False)
        elif name=='models.use':self.query_one('#status',Static).update('模型：'+result.data['id']+' / '+result.data['default_model'])

    async def follow_run(self,identifier,after,project_id=None):
        try:
            async for event in self.client.events(identifier,after,project_id=project_id):
                if identifier!=self.run_id or project_id!=self._run_owner():return
                if event['kind']=='value.observed':
                    value=event['payload']['snapshot'];self.values[value['binding_id']]={k:value[k] for k in ('id','name','version','binding_id','descriptor','fidelity','operation_id')};self._dirty=True
                    if len(self.values)>1000:self.values.pop(next(iter(self.values)))
                elif event['kind']=='run.finished':self.query_one('#status',Static).update('运行 '+identifier[:8]+'：'+str(event['payload'].get('status','结束')))
        except asyncio.CancelledError:raise
        except Exception:self.query_one('#output',RichLog).write('运行事件连接中断；/resume ID 可重新接入。')

    def paint_values(self):
        if self._terminal_closing or not self.is_running or not self._dirty:return
        self._dirty=False;table=self.query_one('#variables',DataTable);table.clear()
        for value in list(self.values.values())[-200:]:table.add_row(*variable_row(value),key=value['id'])
        table.border_title=f'变量 · 显示 {min(200,len(self.values))}/{len(self.values)}；/vars 搜索'

    def on_data_table_row_selected(self,event:DataTable.RowSelected):
        arguments={'snapshot_id':str(event.row_key.value)}
        if self._run_owner():arguments['project_id']=self._run_owner()
        self.run_worker(self.execute('inspect',arguments),name='inspect',group='detail',exclusive=True,exit_on_error=False)

    async def action_cancel_or_quit(self):
        now=time.monotonic()
        if now-self._last_interrupt<1.5:self.action_quit_terminal();return
        self._last_interrupt=now
        running=[worker for worker in self._commands if worker.is_running]
        for worker in running:worker.cancel()
        self._commands=set(running)
        if self.run_id:
            arguments={'run_id':self.run_id}
            if self._run_owner():arguments['project_id']=self._run_owner()
            result=await self.client.command('cancel',arguments);self.last_result=result
            self.query_one('#output',RichLog).write(safe_text(result.model_dump(mode='json')))
        elif running:self.query_one('#output',RichLog).write('当前请求已取消。再次 Ctrl+C 退出。')
        else:self.action_quit_terminal()

    def _run_owner(self):
        return self.run_project_id if self._run_owner_bound else self.project_id

    def _stop_paint(self):
        self._terminal_closing=True
        if self._paint_timer:self._paint_timer.stop()

    def action_quit_terminal(self):
        self._stop_paint();self.workers.cancel_all();self.exit()

    async def on_unmount(self):
        self._stop_paint()
        if not self._closed:self._closed=True;await self.client.close()


def run_terminal(root:Path,*,connect:str='',token_env:str='CDAF_SESSION'):
    from .client import ResearchClient,LocalResearchClient
    from ..research.service import ResearchService
    from ..settings.service import ModelSettingsService
    if connect:
        ResearchTerminal(ResearchClient(connect,'env:'+token_env)).run()
    else:
        with ResearchService(root) as service:
            settings=ModelSettingsService(root)
            try:ResearchTerminal(LocalResearchClient(service,settings)).run()
            finally:settings.close()

