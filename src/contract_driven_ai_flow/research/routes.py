"""Versioned scientific HTTP adapter over the shared application service.

Routes are built by a factory so the exact same handlers can be mounted for the
legacy single-project service and, per explicit ``pid``, for the P3 project
gateway. No mutable ambient project is ever consulted.
"""
from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import Field

from .models import ExperimentSpec, ProbeSpec, WireModel
from .service import ResearchService, TERMINAL


class AnalysisRequest(WireModel):
    script: str = Field(max_length=4096)
    interpreter: str = Field(default=sys.executable, max_length=4096)
    arguments: list[str] = Field(default_factory=list, max_length=256)
    mode: str = "summary"
    probes: list[ProbeSpec] | None = None
    adapters: list[str] = Field(default_factory=list, max_length=128)
    watched_names: list[str] = Field(default_factory=list, max_length=1024)
    watched_lines: list[int] = Field(default_factory=list, max_length=1024)
    instrument: str = "auto"
    capture: dict = Field(default_factory=dict)


class SliceRequest(WireModel):
    selectors: list[dict] = Field(default_factory=list, max_length=64)


class SourceRequest(WireModel):
    path: str = Field(max_length=4096)


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _research_router(app, resolve, prefix: str, *, project=None):
    """Build the research router; ``resolve(request)`` returns the service."""

    def service_for(request: Request) -> ResearchService:
        return resolve(request)

    router = APIRouter(prefix=prefix)

    @router.post('/commands/{command}')
    async def command(command: str, body: dict, request: Request):
        from ..application.commands import dispatch
        from ..application.request import await_connected
        service = service_for(request)
        return await await_connected(request, dispatch(command, body, service=service, settings=app.state.models))

    @router.get("/runs")
    def runs(request: Request, limit: int = 100):
        return service_for(request).store.runs(limit)

    @router.get('/runs/{run_id}/controls')
    def controls(run_id: str, request: Request, details: bool = False):
        service = service_for(request)
        return {'summaries': service.store.control_summaries(run_id),
            'details': service.store.control_details(run_id) if details else None}

    @router.get("/info")
    def info(request: Request):
        from .. import __version__
        service = service_for(request)
        return {"protocol_version": 1, "software_version": __version__, "root": str(service.root), "interpreter": sys.executable,
            "examples": [{"id":"analysis", "name": "标准化、协方差与 PCA", "script":str(Path(__file__).parents[1] / "templates/research-analysis/analysis.py")},
                {"id":"edge-cases", "name": "复数、高维与表格", "script":str(Path(__file__).parents[1] / "templates/research-analysis/edge_cases.py")} ]}

    @router.get("/experiment")
    def experiment(request: Request):
        service = service_for(request)
        path = service.root / "research.yaml"
        if not path.is_file():
            return None
        import yaml
        return ExperimentSpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

    @router.put("/experiment")
    def save_experiment(spec: ExperimentSpec, request: Request):
        from ..storage import atomic_write
        import yaml
        service = service_for(request)
        atomic_write(service.root / "research.yaml", yaml.safe_dump(spec.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
        return spec

    @router.post("/source-preview")
    def source_preview(body: SourceRequest, request: Request):
        from .agent.source import read_source
        from .agent.privacy import clean_text
        service = service_for(request)
        path = Path(body.path)
        if project is not None:
            root = Path(project.projects.project(request.path_params["pid"]).root).resolve()
            if not _inside(root, path):
                raise HTTPException(404, "Source is outside the project root")
        if path.suffix != ".py" or path.stat().st_size > 10 * 1024 * 1024:
            raise ValueError("Choose a Python script of at most 10 MiB")
        source = read_source(path)
        return {"path":source.path, "digest":source.digest, "code":clean_text(source.text, 10 * 1024 * 1024)}

    @router.post("/runs", status_code=202)
    async def start(body: AnalysisRequest, request: Request):
        from ..application.commands import dispatch
        if project is not None:
            raise HTTPException(400, "Project runs start from a planned, configured entry")
        service = service_for(request)
        result=await dispatch('run',body.model_dump(),service=service,settings=app.state.models)
        if result.status!='ok':raise HTTPException(400,result.error)
        return result.data

    @router.get("/runs/{run_id}")
    def run(run_id: str, request: Request):
        return service_for(request).store.run(run_id)

    @router.get("/runs/{run_id}/bootstrap")
    def bootstrap(run_id: str, request: Request):
        return service_for(request).store.bootstrap(run_id)

    @router.get("/runs/{run_id}/snapshots")
    def snapshots(run_id: str, request: Request, latest: bool = True, limit: int = 1000, after: str | None = None):
        return [snapshot.model_dump(mode="json") for snapshot in service_for(request).store.snapshots(run_id, latest=latest, limit=limit, after=after)]

    @router.get("/runs/{run_id}/operations")
    def operations(run_id: str, request: Request, limit: int = 1000):
        return [operation.model_dump(mode="json") for operation in service_for(request).store.operations(run_id, limit)]

    @router.get("/runs/{run_id}/source")
    def source(run_id: str, request: Request):
        return service_for(request).source(run_id)

    @router.get("/runs/{run_id}/history")
    def history(run_id: str, request: Request, binding: str, before: int | None = None, limit: int = 100):
        return [snapshot.model_dump(mode="json") for snapshot in service_for(request).store.history(run_id, binding, before, limit)]

    @router.get("/runs/{run_id}/export/{format}")
    def export(run_id: str, format: str, request: Request):
        from fastapi.responses import Response
        if format != "html":
            raise ValueError("Use html for the standalone research report")
        from .export import offline_report
        service = service_for(request)
        return Response(offline_report(service, run_id), media_type="text/html", headers={"Content-Disposition": f'attachment; filename="research-{run_id}.html"'})

    @router.get("/runs/{run_id}/event-page")
    def event_page(run_id: str, request: Request, after: int = 0, limit: int = 1000):
        return service_for(request).events(run_id, after, limit)

    @router.get("/runs/{run_id}/events")
    async def stream(run_id: str, request: Request, after: int = 0):
        service = service_for(request)
        service.store.run(run_id)
        try:
            cursor = int(request.headers.get("last-event-id", str(after)))
            if cursor < 0:
                raise ValueError
        except ValueError:
            raise HTTPException(400, "Invalid event continuation cursor")

        async def events():
            nonlocal cursor
            idle = 0
            while True:
                if await request.is_disconnected():
                    return
                page = await asyncio.to_thread(service.events, run_id, cursor, 256)
                for event in page:
                    cursor = event["sequence"]
                    yield f"id: {cursor}\nevent: observation\ndata: {json.dumps(event, ensure_ascii=False, allow_nan=False)}\n\n"
                if not page:
                    record = await asyncio.to_thread(service.store.run, run_id)
                    if record["status"] in TERMINAL:
                        return
                    idle += 1
                    if idle >= 200:
                        yield ": heartbeat\n\n"
                        idle = 0
                    await asyncio.sleep(0.05)
        return StreamingResponse(events(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    @router.get("/snapshots/{snapshot_id}")
    def snapshot(snapshot_id: str, request: Request):
        return service_for(request).get_snapshot(snapshot_id)

    @router.post("/snapshots/{snapshot_id}/probe-preview")
    def probe_preview(snapshot_id: str, body: ProbeSpec, request: Request):
        service = service_for(request)
        return service.pool.evaluate(body, service.store.snapshot(snapshot_id))

    @router.post("/snapshots/{snapshot_id}/slice")
    def sliced(snapshot_id: str, body: SliceRequest, request: Request):
        return service_for(request).slice(snapshot_id, body.selectors)

    @router.post("/runs/{run_id}/cancel")
    def cancel(run_id: str, request: Request):
        service = service_for(request)
        service.cancel(run_id)
        return service.store.run(run_id)

    @router.post("/runs/{run_id}/resume")
    def resume(run_id: str, request: Request):
        service = service_for(request)
        service.resume(run_id)
        return service.store.run(run_id)

    @router.get("/probe-types")
    def types(request: Request):
        return service_for(request).registry.types()

    @router.get("/runner-types")
    def runners(request: Request):
        return service_for(request).runners.types()

    return router


def attach_research_routes(app, service: ResearchService, *, prefix="/api/v1/research", projects=None):
    app.include_router(_research_router(app, lambda request: service, prefix))
    from ..settings.routes import attach_model_routes
    attach_model_routes(app, service)
    from .workbench.routes import attach_workbench_routes
    attach_workbench_routes(app, service)
    from .workbench.terminal import attach_terminal_routes
    attach_terminal_routes(app, service)

    if projects is not None:
        projects.models = getattr(app.state, "models", None) or projects.models
        app.state.projects = projects
        service.project_application = projects
        service._owns_project_application = False
        # Reuse the exact same research/workbench/terminal handlers per project.
        app.include_router(
            _research_router(
                app,
                lambda request: projects.research(request.path_params["pid"]),
                prefix + "/projects/{pid}",
                project=projects,
            )
        )
        attach_workbench_routes(
            app, service, prefix=prefix + "/projects/{pid}/workbench", project=projects
        )
        attach_terminal_routes(
            app, service, prefix=prefix + "/projects/{pid}/terminals", project=projects
        )
        from .projects.routes import attach_project_routes
        attach_project_routes(app, projects, prefix=prefix + "/projects")
        from .projects.intelligence_routes import attach_project_intelligence_routes
        attach_project_intelligence_routes(app, projects, prefix=prefix + "/projects")

    @app.exception_handler(LookupError)
    async def missing(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Scientific record is unavailable"}, status_code=404)


def create_research_app(root: Path, *, token: str, port=8765, service=None):
    from ..api import secure_app
    service = service or ResearchService(root)
    from .projects.application import ProjectApplication

    projects = ProjectApplication(root, models=None)

    @asynccontextmanager
    async def lifespan(app):
        yield
        from .projects import routes as _project_routes  # noqa: F401
        cleanup = getattr(app.state, "project_cleanup", None)
        if cleanup is not None:
            await asyncio.to_thread(cleanup)
        await asyncio.to_thread(projects.close)
        app.state.models.close()
        await asyncio.to_thread(service.close)

    app = FastAPI(title="Scientific Dataflow Inspector", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.research = service
    secure_app(app, token, port)
    attach_research_routes(app, service, projects=projects)
    # The legacy service and every project share one global computation budget.
    service._budget = projects.budget
    return app
