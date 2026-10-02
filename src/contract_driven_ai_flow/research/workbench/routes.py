from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import Field

from ..models import WireModel
from .models import WorkbenchConfig
from .semantic_models import ScopeSelector
from .data_semantics import DataSemantics
from .intelligence.harness import HarnessRequest


class ImportRequest(WireModel):
    path: str = Field(max_length=4096)


class SaveConfig(WireModel):
    config: WorkbenchConfig
    expected_revision: int = Field(ge=0)


class SaveSemantics(WireModel):
    semantics: DataSemantics
    expected_revision: int | None = None


class PlanRequest(WireModel):
    analysis_id: str
    scope: str = 'compute'
    run_id: str | None = None
    snapshot_ids: list[str] = Field(default_factory=list, max_length=512)
    instance_ids: list[str] | None = None
    target_scope: ScopeSelector | None = None


class ExecuteRequest(WireModel):
    plan_id: str


class EvidenceRequest(WireModel):
    target_scope: ScopeSelector | None = None
    run_id: str
    snapshot_ids: list[str] = Field(default_factory=list, max_length=512)
    instance_ids: list[str] | None = None


class ToolRequest(WireModel):
    interpreter: str | None = None
    disabled: bool = True


class ManualRequest(WireModel):
    instance_id: str
    analysis_id: str
    snapshot_id: str | None = None
    note: str = Field(max_length=4096)
    verdict: str = 'unknown'


class ProposalRequest(WireModel):
    analysis_id: str
    object_id: str | None = None
    relative_path: str | None = None
    candidate: str = Field(max_length=16384)


class ValidationRequest(WireModel):
    run_id: str
    output_ids: list[str] = Field(min_length=1, max_length=512)


def attach_workbench_routes(app, research):
    service = research.workbench
    service.models = app.state.models
    app.state.workbench = service
    router = APIRouter(prefix='/api/v1/research/workbench')

    @router.post('/analyses')
    def imported(body: ImportRequest):
        return service.import_source(body.path)

    @router.get('/analyses')
    def analyses():
        return service.store.list('analyses')

    @router.get('/analyses/{key}')
    def analysis(key: str):
        return service.analysis(key)

    @router.get('/analyses/{key}/source')
    def analysis_source(key: str):
        return service.analysis_source(key)

    @router.get('/configuration')
    def configuration():
        return service.configurations.load()

    @router.put('/configuration')
    def configure(body: SaveConfig):
        return service.configure(body.config, expected_revision=body.expected_revision)

    @router.post('/migration')
    def migration(apply: bool = False):
        return service.configurations.migrate_legacy(apply=apply)

    @router.get('/probe-definitions')
    def definitions():
        return service.catalog.definitions()

    @router.get('/resources')
    def resources():
        return service.resources.resources()

    @router.post('/resources')
    def import_resource(body: dict):
        return service.resources.import_manifest(body)

    @router.post('/resources/{key}/enable')
    def enable_resource(key: str):
        return service.resources.enable(key)

    @router.post('/resources/{key}/disable')
    def disable_resource(key: str):
        return service.resources.disable(key)

    @router.get('/snapshots/{key}/presenters')
    def presenters(key: str, analysis_id: str | None = None):
        return service.presenters(key, analysis_id)

    @router.get('/snapshots/{key}/semantics')
    def semantics(key: str):
        snapshot = research.store.snapshot(key)
        return service.semantics.get(snapshot.logical_key)

    @router.put('/snapshots/{key}/semantics')
    def save_semantics(key: str, body: SaveSemantics):
        snapshot = research.store.snapshot(key)
        if snapshot.logical_key != body.semantics.logical_key:
            raise ValueError('Data semantics belongs to another logical object')
        return service.semantics.save(body.semantics, shape=snapshot.descriptor.shape, expected_revision=body.expected_revision)

    @router.get('/templates')
    def templates():
        return service.semantics.templates()

    @router.post('/templates')
    def save_template(body: dict):
        return service.semantics.save_template(body['id'], body['label'], body['definition_id'], body['parameters'],
            DataSemantics.model_validate(body['semantics']) if body.get('semantics') else None)

    @router.post('/plans')
    def plan(body: PlanRequest):
        return service.plan(**body.model_dump())

    @router.get('/plans/{key}')
    def get_plan(key: str):
        return service.store.get('plans', key)

    @router.post('/execute', status_code=202)
    def execute(body: ExecuteRequest):
        return service.execute(body.plan_id)

    @router.post('/evaluate', status_code=202)
    def evaluate(body: EvidenceRequest):
        return service.execute_probes(**body.model_dump())

    @router.post('/replot', status_code=202)
    def replot(body: EvidenceRequest):
        return service.replot(**body.model_dump())

    @router.get('/tasks')
    def tasks():
        return service.jobs.list()

    @router.get('/tasks/{key}')
    def task(key: str):
        return service.task(key)

    @router.post('/tasks/{key}/cancel')
    def cancel(key: str):
        return service.jobs.cancel(key)

    @router.get('/outputs')
    def outputs(task_id: str | None = None, run_id: str | None = None, snapshot_id: str | None = None):
        return service.outputs(task_id=task_id, run_id=run_id, snapshot_id=snapshot_id)

    @router.get('/artifacts/{key}')
    def artifact(key: str):
        path, receipt = service.drawing.artifact(key)
        return FileResponse(path, media_type=receipt['mime'], headers={'Content-Security-Policy': "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:", 'X-Content-Type-Options': 'nosniff'})

    @router.get('/relationships/{snapshot_id}')
    def relationships(snapshot_id: str):
        return service.relationships(snapshot_id)

    @router.get('/tools')
    def tools():
        return service.tools.catalog()

    @router.post('/tools/scan', status_code=202)
    def scan(body: ToolRequest):
        return service.jobs.submit('tools.scan', lambda task, cancel: {'receipt': service.tools.scan(body.interpreter, cancel=cancel)})

    @router.post('/tools/{key}/install', status_code=202)
    def install(key: str):
        return service.jobs.submit('tools.install', lambda task, cancel: {'receipt': service.tools.install(key, cancel=cancel)})

    @router.post('/tools/{key}/disable')
    def disable(key: str, body: ToolRequest):
        return service.tools.disable(key, body.disabled)

    @router.post('/tools/{key}/remove', status_code=202)
    def remove(key: str):
        return service.jobs.submit('tools.remove', lambda task, cancel: {'receipt': service.tools.remove(key, cancel=cancel)})

    @router.post('/intelligence', status_code=202)
    def ask(body: HarnessRequest):
        return service.ask(body)

    @router.get('/contexts')
    def contexts():
        return [{k: v for k, v in record.items() if k not in ('calls', 'tools')} for record in service.store.list('contexts')]

    @router.get('/contexts/{key}')
    def context(key: str):
        return service.store.get('contexts', key)

    @router.get('/skills')
    def skills():
        return service.harness.skills.list()

    @router.post('/skills')
    def register_skill(body: ImportRequest):
        return service.harness.skills.register(body.path)

    @router.post('/manual-results')
    def manual_result(body: ManualRequest):
        return service.harness.manual(**body.model_dump())

    @router.get('/changes')
    def changes():
        return service.store.list('proposals')

    @router.post('/changes')
    def propose(body: ProposalRequest):
        if body.object_id:
            return service.changes.propose(body.analysis_id, body.object_id, body.candidate)
        return service.changes.propose_new(body.analysis_id, body.relative_path or 'derived_analysis.py', body.candidate)

    @router.post('/changes/{key}/validate')
    def validate(key: str):
        return service.changes.validate(key)

    @router.post('/changes/{key}/accept')
    def accept(key: str):
        return service.changes.accept(key)

    @router.post('/changes/{key}/reject')
    def reject(key: str):
        return service.changes.reject(key)

    @router.post('/changes/{key}/rollback')
    def rollback(key: str):
        return service.changes.rollback(key)

    @router.post('/changes/{key}/validation')
    def record_validation(key: str, body: ValidationRequest):
        return service.changes.record_validation(key, body.run_id, body.output_ids)

    app.include_router(router)
