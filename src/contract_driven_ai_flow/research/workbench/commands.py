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
        if command == 'tools.describe':
            return service.tools.describe(arguments['id'])
        if command == 'resources':
            return service.resources.resources()
        if command == 'resources.import':
            return service.resources.import_manifest(arguments['manifest']).model_dump(mode='json')
        if command in ('resources.enable', 'resources.disable'):
            return getattr(service.resources, command.split('.')[1])(arguments['id']).model_dump(mode='json')
        if command == 'settings':
            return service.preferences.load()
        if command == 'settings.save':
            return service.preferences.save(**arguments)
        if command == 'settings.reset':
            return service.preferences.reset(**arguments)
        if command == 'scope':
            from .semantic_models import ScopeSelector
            from .scopes import resolve_scope, source_targets
            analysis = service.analysis(arguments['analysis_id'])
            return [target.model_dump(mode='json') for target in resolve_scope(analysis.graph,
                ScopeSelector.model_validate(arguments.get('selector', {})), source_targets(analysis))]
        if command == 'bind':
            from .models import ProbeInstance
            instance = ProbeInstance.model_validate(arguments['instance'])
            service.catalog.resolve(instance.definition_id)
            config = service.configurations.load()
            probes = [probe for probe in config.probes if probe.id != instance.id] + [instance]
            return service.configure(config.model_copy(update={'probes': probes}),
                expected_revision=arguments.get('expected_revision', config.revision)).model_dump(mode='json')
        if command == 'semantics':
            value = service.semantics.get(arguments['logical_key'])
            return value.model_dump(mode='json') if value else None
        if command == 'semantics.save':
            from .data_semantics import DataSemantics
            return service.semantics.save(DataSemantics.model_validate(arguments['semantics']),
                shape=arguments.get('shape'), expected_revision=arguments.get('expected_revision')).model_dump(mode='json')
        if command == 'migrate':
            return service.configurations.migrate_v2(apply=arguments.get('apply', False)) if service.configurations.path.exists() else service.configurations.migrate_legacy(apply=arguments.get('apply', False))
        if command == 'derived':
            return service.store.get('derived', arguments['id'])
        if command == 'derived.retention':
            return service.retain_derived(arguments['id'], arguments['retained'])
        if command == 'derived.proposal':
            return service.propose_derived(arguments['id']).model_dump(mode='json')
        if command == 'storage.expire':
            return service.research.store.expire_artifacts(service.preferences.load()['values']['storage']['retention_days'])
        if command == 'ask':
            from .intelligence.harness import HarnessRequest
            return service.ask(HarnessRequest.model_validate(arguments)).model_dump(mode='json')
        if command == 'context':
            return service.store.get('contexts', arguments['context_id'])
        if command == 'changes':
            return service.store.list('proposals')
        if command == 'propose':
            return service.changes.propose(**arguments).model_dump(mode='json')
        if command in ('accept', 'reject', 'rollback', 'validate'):
            return getattr(service.changes, command)(arguments['proposal_id']).model_dump(mode='json')
        raise ValueError('Unknown workbench command')
    return await asyncio.to_thread(invoke)
