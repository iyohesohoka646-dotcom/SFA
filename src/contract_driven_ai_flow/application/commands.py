from __future__ import annotations

import asyncio
import sys
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from ..research.models import WireModel, ProbeSpec, ExperimentSpec

HELP = '/open "analysis.py" [--python "python.exe"] | /run [-- arguments] | /runs | /resume ID | /vars [search] | /inspect SNAPSHOT | /probe list|add|preview | /model [ID MODEL]|search|test|configure | /explain [OPERATION] [--provider ID --model ID --sample --context] | /workbench import|plan|execute|evaluate|replot|tools|ask|changes JSON | /help | /quit'


class CommandResult(WireModel):
    status: Literal['ok', 'error', 'cancelled']
    data: object = None
    error: str = ''
    run_id: str | None = None


async def dispatch(command: str, arguments: dict, *, service, settings) -> CommandResult:
    """No terminal or HTTP state participates in scientific command semantics."""
    run_id = arguments.get('run_id')
    try:
        if command == 'help':
            data = {'help': HELP}
        elif command == 'quit':
            data = {'quit': True}
        elif command.startswith('workbench.'):
            from ..research.workbench.commands import execute_command
            data = await execute_command(command.removeprefix('workbench.'), arguments, service.workbench, settings)
        elif command == 'open':
            from ..research.agent.source import read_source
            from ..research.agent.privacy import clean_text
            path = Path(arguments['script'])
            if path.suffix != '.py' or path.stat().st_size > 10*1024*1024:
                raise ValueError('Choose a Python script of at most 10 MiB')
            source = await asyncio.to_thread(read_source, path)
            data = {'script': source.path, 'source_digest': source.digest, 'code': clean_text(source.text, 16384),
                    'interpreter': arguments.get('interpreter') or sys.executable}
        elif command == 'run':
            def configured_options():
                import yaml
                path = service.root/'research.yaml'
                if not path.is_file():return {}
                definition = ExperimentSpec.model_validate(yaml.safe_load(path.read_text(encoding='utf-8')))
                configured_script = Path(definition.script)
                if not configured_script.is_absolute():configured_script = service.root/configured_script
                if configured_script.resolve() != Path(arguments['script']).resolve():return {}
                return {**({'interpreter':definition.interpreter} if definition.interpreter else {}),
                    'arguments':definition.arguments,'mode':definition.capture.get('level','summary'),
                    'capture':definition.capture,'adapters':definition.adapters,
                    'probes':[p.model_dump(mode='json') for p in definition.probes]}
            options = await asyncio.to_thread(configured_options)
            options.update({key: value for key,value in arguments.items() if key in
                ('interpreter','arguments','mode','probes','adapters','watched_names','watched_lines','instrument','capture','runner')}
            )
            launch = asyncio.create_task(asyncio.to_thread(service.start_analysis, Path(arguments['script']), **options))
            try:
                handle = await asyncio.shield(launch)
            except asyncio.CancelledError:
                # A cancelled to_thread await does not stop the launching thread.
                handle = await launch
                await asyncio.to_thread(service.cancel, handle.run_id)
                raise
            run_id, data = handle.run_id, asdict(handle)
        elif command == 'runs':
            data = await asyncio.to_thread(service.store.runs, min(100,int(arguments.get('limit',100))))
        elif command == 'resume':
            data = await asyncio.to_thread(service.store.bootstrap, run_id)
        elif command == 'vars':
            values = await asyncio.to_thread(service.store.snapshots,run_id,latest=True,limit=1000)
            query = str(arguments.get('search','')).casefold()
            data = [{'id':s.id,'binding_id':s.binding_id,'name':s.name,'version':s.version,
                     'descriptor':s.descriptor.model_dump(mode='json'),'fidelity':s.fidelity,'operation_id':s.operation_id}
                    for s in values if query in (s.name+' '+s.descriptor.backend+' '+s.descriptor.kind).casefold()]
        elif command == 'inspect':
            data = await asyncio.to_thread(service.get_snapshot,arguments['snapshot_id'])
        elif command in ('cancel','continue'):
            await asyncio.to_thread(service.cancel if command=='cancel' else service.resume,run_id)
            data = await asyncio.to_thread(service.store.run,run_id)
        elif command == 'probe.list':
            data = service.registry.types()
        elif command == 'probe.preview':
            value = await asyncio.to_thread(service.store.snapshot,arguments['snapshot_id'])
            probe = ProbeSpec(id='terminal-preview',kind=arguments['kind'],parameters=arguments.get('parameters',{}))
            data = (await asyncio.to_thread(service.pool.evaluate,probe,value)).model_dump(mode='json')
        elif command == 'probe.add':
            import yaml
            from ..storage import atomic_write
            path = service.root/'research.yaml'
            def save_probe():
                definition = ExperimentSpec.model_validate(yaml.safe_load(path.read_text(encoding='utf-8'))) if path.is_file() else ExperimentSpec(script=arguments['script'],interpreter=arguments.get('interpreter') or sys.executable)
                probe = ProbeSpec(id='terminal-'+uuid.uuid4().hex[:8],kind=arguments['kind'],binding=arguments.get('binding','*'),policy=arguments.get('policy','continue'))
                definition.probes.append(probe)
                atomic_write(path,yaml.safe_dump(definition.model_dump(mode='json'),allow_unicode=True,sort_keys=False))
                return {'probe':probe.model_dump(mode='json'),'applies':'next run'}
            data = await asyncio.to_thread(save_probe)
        elif command == 'models.list':
            data = [p.model_dump(mode='json') for p in await asyncio.to_thread(settings.list)]
        elif command == 'models.search':
            query=str(arguments.get('search','')).casefold()
            profiles=await asyncio.to_thread(settings.list)
            data=[{'profile_id':p.id,'model':model} for p in profiles
                  for model in sorted(set([*p.models,*([p.default_model] if p.default_model else [])]))
                  if query in (p.id+' '+model).casefold()][:500]
        elif command == 'models.configure':
            from ..settings.models import ProviderProfile
            data = (await asyncio.to_thread(settings.save,ProviderProfile.model_validate(arguments['profile']))).model_dump(mode='json')
        elif command == 'models.use':
            profile = settings.profile(arguments['profile_id'])
            if profile.id=='offline':
                if arguments['model']!='rules':raise ValueError('The offline profile supports rules')
                data={**profile.model_dump(mode='json'),'configured':True}
            else:
                data = (await asyncio.to_thread(settings.save,profile.model_copy(update={'default_model':arguments['model']}))).model_dump(mode='json')
        elif command == 'models.test':
            result = await settings.test(arguments['profile_id'],inference=bool(arguments.get('inference',False)),operation_id=arguments.get('operation_id'))
            return CommandResult(status='cancelled' if result.status=='cancelled' else 'error' if result.status=='error' else 'ok',data=result.model_dump(mode='json'),error=result.message if result.status=='error' else '')
        elif command in ('explain','explanation-context'):
            from ..settings.explanations import ExplanationService
            explanations=ExplanationService(service,settings)
            if command=='explanation-context':
                data=await asyncio.to_thread(explanations.context,arguments['operation_id'],include_sample=bool(arguments.get('include_sample',False)))
            else:
                provider=arguments.get('provider_id','offline')
                model=arguments.get('model') or settings.profile(provider).default_model
                data=(await explanations.explain(arguments['operation_id'],provider_id=provider,model=model,
                    include_sample=bool(arguments.get('include_sample',False)),operation_token=arguments.get('request_id'))).model_dump(mode='json')
        else:
            raise ValueError('Unknown command')
        return CommandResult(status='ok',data=data,run_id=run_id)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        # Never expose validation input, provider bodies, credentials or live values.
        return CommandResult(status='error',error='Command failed ('+type(error).__name__+'); check the command fields and selected record.',run_id=run_id)
