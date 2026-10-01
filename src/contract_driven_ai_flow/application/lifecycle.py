"""Owned backends and connection-based browser leases; unrelated processes are borrowed."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
import secrets
import threading
import time

from fastapi import Request
from pydantic import Field
from ..research.models import WireModel


class Acquire(WireModel):
    client_id:str=Field(min_length=1,max_length=128)


@dataclass(frozen=True)
class ServiceHandle:
    url: str
    pid: int
    port: int
    owned: bool


class BackendOwner:
    def __init__(self,root:Path,port:int|None=None,*,workspace=False):
        self.root,self.port,self.workspace=Path(root).resolve(),port,workspace
        self.state='stopped';self.handle=None;self._child=None;self._tree=None
        self._closed=False
        self._cancel=threading.Event();self._lock=threading.Lock()

    def start(self)->ServiceHandle|None:
        from ..studio import start
        from ..research.processes import ProcessTree
        with self._lock:
            if self._closed:return None
            if self.state=='ready':return self.handle
            self._cancel.clear();self.state='starting'
            def spawned(child):
                self._child=child;self._tree=ProcessTree(child)
            try:
                result=start(self.root,self.port,workspace=self.workspace,owned=True,cancel_event=self._cancel,process_callback=spawned)
                if self._cancel.is_set():
                    self._terminate();self.state='stopped';return None
                self.handle=ServiceHandle(result['url'],result['pid'],result['port'],not result['reused'])
                if self._tree:self._tree.include(self.handle.pid)
                self.state='ready';return self.handle
            except Exception:
                self._terminate()
                if self._cancel.is_set():self.state='stopped';return None
                self.state='error';raise

    def _terminate(self):
        if self._tree:
            self._tree.terminate();self._tree.close();self._tree=None
        if self._child:
            self._child.wait(timeout=5);self._child=None

    def stop(self,*,cancel_owned:bool=True)->None:
        from ..studio import read_state,request
        self._closed=True
        self._cancel.set()
        with self._lock:
            self.state='stopping'
            if self.handle and self.handle.owned and self._child:
                state=read_state(self.root)
                if state and state['pid']==self.handle.pid:
                    try:request(state,'POST')
                    except (OSError,ValueError):pass
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    current=read_state(self.root)
                    if not current or current['pid']!=self.handle.pid:break
                    time.sleep(.05)
                try:self._child.wait(timeout=5)
                except Exception:self._terminate()
            self._terminate();self.handle=None;self.state='stopped'


@dataclass
class Lease:
    id:str
    client_id:str
    deadline:float
    connections:int=0
    had_connection:bool=False
    disconnected_at:float=0


class ClientLease:
    def __init__(self,shutdown,*,clock=time.monotonic):
        self.shutdown,self.clock=shutdown,clock;self.leases={};self.closing=False
        self._startup=clock()+120;self._idle=None

    def acquire(self,client_id:str)->Lease:
        if self.closing:raise ValueError('The local service is stopping')
        if not client_id or len(client_id)>128 or len(self.leases)>=128:raise ValueError('Browser lease limit reached')
        lease=Lease(secrets.token_hex(16),client_id,self.clock()+120)
        self.leases[lease.id]=lease;self._idle=None;return lease

    def release(self,lease_id:str)->None:
        self.leases.pop(lease_id,None)
        if not self.leases:self._idle=self.clock()

    def renew(self,lease_id:str)->None:
        self.leases[lease_id].deadline=self.clock()+120

    def connected(self,lease_id:str,active:bool)->None:
        lease=self.leases.get(lease_id)
        if not lease:return
        lease.connections=max(0,lease.connections+(1 if active else -1))
        if active:lease.had_connection=True;self._idle=None
        elif not lease.connections:
            lease.disconnected_at=self.clock();lease.deadline=self.clock()+120

    def sweep(self)->None:
        if self.closing:return
        now=self.clock()
        for key,lease in list(self.leases.items()):
            if not lease.connections and now>=lease.deadline:self.leases.pop(key)
        if any(lease.connections for lease in self.leases.values()):return
        if self.leases:return
        due=self._idle+3 if self._idle is not None else self._startup
        if now>=due:self.closing=True;self.shutdown()


def attach_lifecycle(app,shutdown,*,owned:bool):
    from fastapi import HTTPException
    from fastapi.responses import StreamingResponse
    leases=ClientLease(shutdown);app.state.leases=leases

    @app.get('/api/v1/lifecycle')
    def status():return {'owned':owned,'grace_seconds':3,'abandoned_seconds':120,'state':'stopping' if leases.closing else 'ready'}

    @app.post('/api/v1/lifecycle/leases')
    def acquire(body:Acquire):
        if not owned:return {'id':None,'owned':False}
        lease=leases.acquire(body.client_id);return {'id':lease.id,'owned':True}

    @app.delete('/api/v1/lifecycle/leases/{identifier}')
    def release(identifier:str):leases.release(identifier);return {'released':True}

    @app.get('/api/v1/lifecycle/leases/{identifier}/events')
    async def connection(identifier:str,request:Request):
        if identifier not in leases.leases:raise HTTPException(404,'Browser lease is unavailable')
        async def events():
            leases.connected(identifier,True)
            try:
                while identifier in leases.leases and not leases.closing and not await request.is_disconnected():
                    yield 'data: {"connected":true}\n\n'
                    await asyncio.sleep(.5)
            finally:leases.connected(identifier,False)
        return StreamingResponse(events(),media_type='text/event-stream')

    original=app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(application):
        async with original(application):
            async def monitor():
                while not leases.closing:
                    if owned:leases.sweep()
                    await asyncio.sleep(.25)
            task=asyncio.create_task(monitor())
            try:yield
            finally:
                leases.closing=True;task.cancel()
                try:await task
                except asyncio.CancelledError:pass
    app.router.lifespan_context=lifespan
    # Keep API routes before legacy static catch-all mounts.
    app.router.routes.sort(key=lambda route: getattr(route,'path','')=='/')
