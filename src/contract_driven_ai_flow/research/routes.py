"""Versioned scientific HTTP adapter over the shared application service."""
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


def attach_research_routes(app, service: ResearchService):
    router = APIRouter(prefix="/api/v1/research")

    @router.get("/runs")
    def runs(limit: int = 100):
        return service.store.runs(limit)

    @router.get("/info")
    def info():
        return {"protocol_version": 1, "root": str(service.root), "interpreter": sys.executable,
            "examples": [{"id":"analysis", "name":"标准化、协方差与 PCA", "script":str(Path(__file__).parents[1] / "templates/research-analysis/analysis.py")},
                {"id":"edge-cases", "name":"复数、高维与表格", "script":str(Path(__file__).parents[1] / "templates/research-analysis/edge_cases.py")} ]}

    @router.get("/experiment")
    def experiment():
        path = service.root / "research.yaml"
        if not path.is_file():
            return None
        import yaml
        return ExperimentSpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

    @router.put("/experiment")
    def save_experiment(spec: ExperimentSpec):
        from ..storage import atomic_write
        import yaml
        atomic_write(service.root / "research.yaml", yaml.safe_dump(spec.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
        return spec

    @router.post("/source-preview")
    def source_preview(body: SourceRequest):
        from .agent.source import read_source
        from .agent.privacy import clean_text
        path = Path(body.path)
        if path.suffix != ".py" or path.stat().st_size > 10 * 1024 * 1024:
            raise ValueError("Choose a Python script of at most 10 MiB")
        source = read_source(path)
        return {"path":source.path, "digest":source.digest, "code":clean_text(source.text, 10 * 1024 * 1024)}

    @router.post("/runs", status_code=202)
    def start(body: AnalysisRequest):
        return asdict(service.start_analysis(Path(body.script), interpreter=Path(body.interpreter), arguments=body.arguments,
            mode=body.mode, probes=body.probes, adapters=body.adapters, watched_names=body.watched_names,
            watched_lines=body.watched_lines, instrument=body.instrument, capture=body.capture))

    @router.get("/runs/{run_id}")
    def run(run_id: str):
        return service.store.run(run_id)

    @router.get("/runs/{run_id}/bootstrap")
    def bootstrap(run_id: str):
        return service.store.bootstrap(run_id)

    @router.get("/runs/{run_id}/snapshots")
    def snapshots(run_id: str, latest: bool = True, limit: int = 1000, after: str | None = None):
        return [snapshot.model_dump(mode="json") for snapshot in service.store.snapshots(run_id, latest=latest, limit=limit, after=after)]

    @router.get("/runs/{run_id}/operations")
    def operations(run_id: str, limit: int = 1000):
        return [operation.model_dump(mode="json") for operation in service.store.operations(run_id, limit)]

    @router.get("/runs/{run_id}/source")
    def source(run_id: str):
        return service.source(run_id)

    @router.get("/runs/{run_id}/history")
    def history(run_id: str, binding: str, before: int | None = None, limit: int = 100):
        return [snapshot.model_dump(mode="json") for snapshot in service.store.history(run_id, binding, before, limit)]

    @router.get("/runs/{run_id}/export/{format}")
    def export(run_id: str, format: str):
        from fastapi.responses import Response
        if format != "html":
            raise ValueError("Use html for the standalone research report")
        from .export import offline_report
        return Response(offline_report(service, run_id), media_type="text/html", headers={"Content-Disposition": f'attachment; filename="research-{run_id}.html"'})

    @router.get("/runs/{run_id}/event-page")
    def event_page(run_id: str, after: int = 0, limit: int = 1000):
        return service.events(run_id, after, limit)

    @router.get("/runs/{run_id}/events")
    async def stream(run_id: str, request: Request, after: int = 0):
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
                    if idle >= 100:
                        yield ": heartbeat\n\n"
                        idle = 0
                    await asyncio.sleep(0.1)
        return StreamingResponse(events(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    @router.get("/snapshots/{snapshot_id}")
    def snapshot(snapshot_id: str):
        return service.get_snapshot(snapshot_id)

    @router.post("/snapshots/{snapshot_id}/probe-preview")
    def probe_preview(snapshot_id: str, body: ProbeSpec):
        return service.pool.evaluate(body, service.store.snapshot(snapshot_id))

    @router.post("/snapshots/{snapshot_id}/slice")
    def sliced(snapshot_id: str, body: SliceRequest):
        return service.slice(snapshot_id, body.selectors)

    @router.post("/runs/{run_id}/cancel")
    def cancel(run_id: str):
        service.cancel(run_id)
        return service.store.run(run_id)

    @router.post("/runs/{run_id}/resume")
    def resume(run_id: str):
        service.resume(run_id)
        return service.store.run(run_id)

    @router.get("/probe-types")
    def types():
        return service.registry.types()

    @router.get("/runner-types")
    def runners():
        return service.runners.types()

    app.include_router(router)
    from ..settings.routes import attach_model_routes
    attach_model_routes(app, service)

    @app.exception_handler(LookupError)
    async def missing(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Scientific record is unavailable"}, status_code=404)


def create_research_app(root: Path, *, token: str, port=8765, service=None):
    from ..api import secure_app
    service = service or ResearchService(root)

    @asynccontextmanager
    async def lifespan(app):
        yield
        app.state.models.close()
        await asyncio.to_thread(service.close)

    app = FastAPI(title="Scientific Dataflow Inspector", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.research = service
    secure_app(app, token, port)
    attach_research_routes(app, service)
    return app
