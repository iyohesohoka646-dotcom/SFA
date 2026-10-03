from __future__ import annotations

import asyncio
import json
import os
from urllib.parse import urlsplit

import httpx

from ..application.commands import dispatch,CommandResult
from ..research.service import TERMINAL


class LocalResearchClient:
    def __init__(self,service,settings):self.service,self.settings=service,settings

    async def command(self,name,arguments):
        return await dispatch(name,arguments,service=self.service,settings=self.settings)

    async def events(self,run_id,after=0):
        while True:
            page=await asyncio.to_thread(self.service.events,run_id,after,256)
            for event in page:
                after=event['sequence'];yield event
                if event['kind']=='run.finished':return
            if not page:
                record=await asyncio.to_thread(self.service.store.run,run_id)
                if record['status'] in TERMINAL:return
                await asyncio.sleep(.1)

    async def close(self):pass  # The caller that created the service owns its lifecycle.


class ResearchClient:
    def __init__(self,base_url:str,token_ref:str):
        url=urlsplit(base_url)
        if url.scheme!='http' or url.hostname not in ('127.0.0.1','localhost','::1') or url.username or url.password or url.query or url.fragment:
            raise ValueError('Terminal connections require a loopback HTTP URL without credentials')
        if not token_ref.startswith('env:') or not os.environ.get(token_ref[4:]):raise ValueError('Select an explicit session-token environment reference')
        self.http=httpx.AsyncClient(base_url=base_url.rstrip('/'),headers={'Authorization':'Bearer '+os.environ[token_ref[4:]]},trust_env=False,follow_redirects=False,timeout=10)

    async def command(self,name,arguments):
        # These actions have server-side execution budgets and remain cancellable.
        # A fixed ten-second read deadline would override the user's model timeout.
        timeout=httpx.Timeout(connect=10,read=None,write=10,pool=10) if name in ('models.test','explain','probe.preview') else 10
        response=await self.http.post('/api/v1/research/commands/'+name,json=arguments,timeout=timeout)
        if response.status_code!=200:return CommandResult(status='error',error='Local service rejected the command (HTTP '+str(response.status_code)+')')
        if len(response.content)>3*1024*1024:raise ValueError('Command response exceeds the terminal budget')
        return CommandResult.model_validate(response.json())

    async def events(self,run_id,after=0):
        for reconnect in range(4):
            try:
                async with self.http.stream('GET','/api/v1/research/runs/'+run_id+'/events',params={'after':after},headers={'Last-Event-ID':str(after)},timeout=None) as response:
                    if response.status_code!=200:raise ValueError('Scientific events are unavailable')
                    async for line in response.aiter_lines():
                        if len(line)>3*1024*1024:raise ValueError('Event exceeds the terminal budget')
                        if line.startswith('data: '):
                            event=json.loads(line[6:])
                            if event['sequence']>after:after=event['sequence'];yield event
                            if event['kind']=='run.finished':return
                    record=await self.http.get('/api/v1/research/runs/'+run_id)
                    if record.status_code==200 and record.json().get('status') in TERMINAL:return
                    if reconnect==3:raise ValueError('Local event stream ended before the run finished')
                await asyncio.sleep(.25*(reconnect+1))
            except httpx.TransportError:
                if reconnect==3:raise ValueError('Local event connection was interrupted') from None
                await asyncio.sleep(.25*(reconnect+1))

    async def close(self):await self.http.aclose()
