"""Shared Web/CLI/terminal adapter to the composed service."""
import asyncio

from .models import WorkbenchConfig


async def execute_command(command, arguments, service, settings):
    service.models = settings
    def invoke():
        if command == 'import':
            return service.import_source(arguments['path']).model_dump(mode='json')
        if command == 'configuration':
            return service.configurations.load().model_dump(mode='json')
        if command == 'configure':
            return service.configure(WorkbenchConfig.model_validate(arguments['config']), expected_revision=arguments['expected_revision']).model_dump(mode='json')
        if command == 'plan':
            return service.plan(**arguments).model_dump(mode='json')
        if command == 'execute':
            return service.execute(arguments['plan_id']).model_dump(mode='json')
        if command == 'evaluate':
            return service.execute_probes(**arguments).model_dump(mode='json')
        if command == 'replot':
            return service.replot(**arguments).model_dump(mode='json')
        if command == 'task':
            return service.task(arguments['task_id']).model_dump(mode='json')
        if command == 'cancel':
            return service.jobs.cancel(arguments['task_id']).model_dump(mode='json')
        if command == 'outputs':
            return service.outputs(**arguments)
        if command == 'relationships':
            return service.relationships(arguments['snapshot_id']).model_dump(mode='json')
        if command == 'tools':
            return service.tools.catalog()
        if command == 'tools.scan':
            return service.tools.scan(arguments.get('interpreter'))
        if command == 'ask':
            from .intelligence.harness import HarnessRequest
            return service.ask(HarnessRequest.model_validate(arguments)).model_dump(mode='json')
        if command == 'context':
            return service.store.get('contexts', arguments['context_id'])
        raise ValueError('Unknown workbench command')
    return await asyncio.to_thread(invoke)
