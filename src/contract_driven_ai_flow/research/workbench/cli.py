"""Batch commands share the workbench service and never detach owned jobs."""
import asyncio
import json
from pathlib import Path

import typer

from ..service import ResearchService
from ...application.commands import dispatch
from ...settings.service import ModelSettingsService
from .models import HarnessPolicy, ProbeInstance


def register(app, output):
    def perform(root, command, arguments, wait=False):
        with ResearchService(root) as service:
            settings = ModelSettingsService(root)
            try:
                result = asyncio.run(dispatch('workbench.' + command, arguments, service=service, settings=settings))
                if result.status != 'ok':
                    raise ValueError(result.error)
                value = result.data
                if wait:
                    task_id = value['id']
                    try:
                        value = service.workbench.jobs.wait(task_id, 3600).model_dump(mode='json')
                    except KeyboardInterrupt:
                        service.workbench.jobs.cancel(task_id)
                        value = service.workbench.jobs.wait(task_id, 20).model_dump(mode='json')
                    if command == 'ask' and value.get('receipt', {}).get('context_id'):
                        value['context'] = service.workbench.store.get('contexts', value['receipt']['context_id'])
                output(value)
                if wait and (value['status'] in ('failed', 'cancelled', 'interrupted') or value['calculation_status'] in ('failed', 'timeout', 'cancelled', 'interrupted')):
                    raise typer.Exit(130 if value['status'] == 'cancelled' else 1)
                return value
            finally:
                settings.close()

    def safe(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ValueError, LookupError, OSError, TimeoutError) as error:
            from ..agent.privacy import clean_text
            typer.echo(clean_text(str(error)), err=True)
            raise typer.Exit(1)

    @app.command('import')
    def import_source(path: Path, python: str = typer.Option('', '--python'), project: Path = typer.Option(Path('.'), '--project', '-p')):
        """Parse source without execution; select it for subsequent plans."""
        def run():
            with ResearchService(project) as service:
                wb = service.workbench
                analysis = wb.import_source(path)
                config = wb.configurations.load()
                wb.configure(config.model_copy(update={'script': analysis.path, **({'interpreter': python} if python else {})}), expected_revision=config.revision)
                output(analysis)
        safe(run)

    @app.command('plan')
    def plan(analysis: str, scope: str = 'compute', run_id: str = typer.Option('', '--run'), project: Path = typer.Option(Path('.'), '--project', '-p')):
        """Freeze an explicit compute/probes/replot plan without executing it."""
        safe(perform, project, 'plan', {'analysis_id': analysis, 'scope': scope, 'run_id': run_id or None})

    @app.command('run')
    def run(plan_id: str = typer.Option(..., '--plan'), project: Path = typer.Option(Path('.'), '--project', '-p')):
        """Execute a frozen plan and wait; Ctrl+C cancels its owned job."""
        safe(perform, project, 'execute', {'plan_id': plan_id}, wait=True)

    @app.command('config')
    def config(input_file: Path | None = typer.Option(None, '--input'), project: Path = typer.Option(Path('.'), '--project', '-p')):
        """Read configuration, or save a JSON configuration with its revision."""
        if input_file is None:
            safe(perform, project, 'configuration', {})
        else:
            def run():
                value = json.loads(input_file.read_text(encoding='utf-8-sig'))
                perform(project, 'configure', {'config': value, 'expected_revision': value['revision']})
            safe(run)

    @app.command('probes')
    def probes(run_id: str = typer.Option('', '--run'), evaluate: bool = False, replot: bool = False,
               definition: str = typer.Option('', '--add'), binding: str = '*', budget_ms: int = 30000, project: Path = typer.Option(Path('.'), '--project', '-p')):
        """List definitions/results, add a probe, or explicitly evaluate saved evidence."""
        def run():
            if evaluate and replot:
                raise ValueError('Choose --evaluate or --replot')
            if evaluate or replot:
                if not run_id:
                    raise ValueError('--run is required')
                return perform(project, 'replot' if replot else 'evaluate', {'run_id': run_id}, wait=True)
            if run_id:
                return perform(project, 'outputs', {'run_id': run_id})
            with ResearchService(project) as service:
                wb = service.workbench
                if definition:
                    wb.catalog.resolve(definition)
                    config = wb.configurations.load()
                    output(wb.configure(config.model_copy(update={'probes': [*config.probes, ProbeInstance(definition_id=definition, binding=binding, budget_ms=budget_ms)]}), expected_revision=config.revision))
                else:
                    output(wb.catalog.definitions())
        safe(run)

    @app.command('tools')
    def tools(scan: bool = False, python: str = typer.Option('', '--python'), install: str = '', remove: str = '', disable: str = '', project: Path = typer.Option(Path('.'), '--project', '-p')):
        """Public catalog and explicit project-owned plotting environment management."""
        def run():
            if sum(bool(x) for x in (scan, install, remove, disable)) > 1:
                raise ValueError('Choose one tool operation')
            with ResearchService(project) as service:
                manager = service.workbench.tools
                if install: output(manager.install(install))
                elif remove: output(manager.remove(remove))
                elif disable: manager.disable(disable); output(manager.catalog())
                elif scan: output(manager.scan(python or None))
                else: output(manager.catalog())
        safe(run)

    @app.command('ask')
    def ask(analysis: str, question: str, role: str = 'explain', object_id: str = typer.Option('', '--object'),
            run_id: str = typer.Option('', '--run'), provider: str = '', model: str = '', project: Path = typer.Option(Path('.'), '--project', '-p')):
        """Automatic environment/tool harness; configuration shares model settings."""
        def run():
            from .configuration import ConfigurationStore
            policy = next(p for p in ConfigurationStore(project).load().harness if p.role == role)
            policy = HarnessPolicy.model_validate({**policy.model_dump(), **({'provider_id': provider} if provider else {}), **({'model': model} if model else {})})
            perform(project, 'ask', {'analysis_id': analysis, 'question': question, 'object_id': object_id or None, 'run_id': run_id or None, 'policy': policy.model_dump(mode='json')}, wait=True)
        safe(run)

    @app.command('changes')
    def changes(proposal: str = '', action: str = 'list', input_file: Path | None = typer.Option(None, '--input'), project: Path = typer.Option(Path('.'), '--project', '-p')):
        """Review scoped proposals; accept/reject/rollback require explicit commands."""
        def run():
            if action == 'list': perform(project, 'changes', {})
            elif action == 'propose' and input_file:
                perform(project, 'propose', json.loads(input_file.read_text(encoding='utf-8-sig')))
            elif action in ('accept', 'reject', 'rollback', 'validate') and proposal:
                perform(project, action, {'proposal_id': proposal})
            else: raise ValueError('Use --action list|propose|accept|reject|rollback|validate with --input or --proposal')
        safe(run)

    @app.command('migrate-config')
    def migrate_config(apply: bool = False, project: Path = typer.Option(Path('.'), '--project', '-p')):
        """Preview migration; --apply backs up and preserves research.yaml."""
        from .configuration import ConfigurationStore
        output(safe(ConfigurationStore(project).migrate_legacy, apply=apply))
