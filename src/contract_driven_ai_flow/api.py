"""Loopback-only HTTP adapter; all semantic actions use the same application services."""
from __future__ import annotations

import asyncio
import concurrent.futures
import hmac
import json
import os
import secrets
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from . import changes
from .compiler import compile_project
from .context import build_context
from .models import Model, ProbeSpec, ProjectSpec, RunEvent, canonical
from .paths import Conflict, FlowError
from .privacy import sanitize, sanitize_change, sanitize_plan, sanitize_project
from .probes import evaluate_probe
from .runtime import Runner
from .redaction_restore import restore_project
from .source import scan_candidates
from .storage import Store, now


class ArchitectureRequest(Model):
    project: ProjectSpec
    base_revision: str
    title: str = "Architecture proposal"


class ImplementationRequest(Model):
    module: str
    candidate: str
    title: str = "Implementation proposal"


class GenerateRequest(Model):
    module: str
    level: str = "L2"
    provider: str = "mock"
    model: str | None = None


class RunRequest(Model):
    input: object = {}
    base_revision: str


class ReviewRequest(Model):
    base_revision: str


class ViewRequest(Model):
    view: dict
    base_revision: str


class PreviewRequest(Model):
    probe: ProbeSpec
    input: dict = {}
    output: object = None


class CleanRequest(Model):
    runs_before: str | None = None


def secure_app(app: FastAPI, token: str, port: int):
    """Apply the same local session boundary to project and workspace routes."""
    @app.middleware("http")
    async def boundaries(request: Request, call_next):
        host = request.headers.get("host", "").split(":")[0]
        if host not in ("127.0.0.1", "localhost", "testserver"):
            return JSONResponse({"detail": "Unrecognized loopback host"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
            return JSONResponse({"detail": "Origin does not match the local Studio"}, status_code=403)
        if "/api/" in request.url.path:
            provided = request.headers.get("authorization", "").removeprefix("Bearer ")
            if not hmac.compare_digest(provided, token):
                return JSONResponse({"detail": "A valid Studio session is required; reopen with cdaf studio"}, status_code=401)
            if len(await request.body()) > 2 * 1024 * 1024:
                return JSONResponse({"detail": "Request exceeds 2 MiB"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; object-src 'none'; frame-ancestors 'none'"
        return response

    @app.exception_handler(FlowError)
    async def flow_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409 if isinstance(exc, Conflict) else 400)

    async def validation_error(request, exc):
        # Validation diagnostics must not echo credential-bearing request data.
        errors = [{key: value for key, value in item.items() if key in ("loc", "msg", "type")} for item in exc.errors()]
        return JSONResponse({"detail": errors}, status_code=422)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(ValidationError, validation_error)

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(OSError)
    async def file_error(request, exc):
        return JSONResponse({"detail": f"{type(exc).__name__}: {exc.strerror or 'Local file operation failed'}"}, status_code=400)


def create_app(root: Path, token: str | None = None, port: int = 8765, shutdown: Callable[[], None] | None = None) -> FastAPI:
    root = root.resolve()
    store = Store(root)
    token = token or secrets.token_urlsafe(32)
    runners: dict[str, Runner] = {}
    runners_lock = threading.Lock()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
    from .research.service import ResearchService
    from .research.routes import attach_research_routes
    research = ResearchService(root)

    @asynccontextmanager
    async def lifespan(app):
        store.load()
        store.recover_runs()
        yield
        with runners_lock:
            for runner in runners.values():
                runner.cancelled.set()
        executor.shutdown(wait=True, cancel_futures=True)
        await asyncio.to_thread(research.close)

    app = FastAPI(title="Contract-Driven AI Flow", version="1", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.session_token = token
    app.state.research = research
    attach_research_routes(app, research)

    secure_app(app, token, port)

    def cancel_runs():
        with runners_lock:
            for runner in runners.values():
                runner.cancelled.set()
    app.state.cancel_runs = cancel_runs

    def safe_change(change):
        return sanitize_change(change, store.load())

    @app.get("/api/v1/studio")
    def studio_status():
        return {"pid": os.getpid(), "project": str(root), "port": port, "mode": "project"}

    @app.post("/api/v1/studio/shutdown")
    def studio_shutdown():
        if shutdown is None:
            raise HTTPException(409, "This server is managed by its foreground owner")
        with runners_lock:
            for runner in runners.values():
                runner.cancelled.set()
        shutdown()
        return {"status": "stopping"}

    @app.get("/api/v1/project")
    def get_project():
        project = store.load()
        return {"project": sanitize_project(project), "revision": project.revision, "view": store.views()}

    @app.get("/api/v1/schema")
    def schema():
        return ProjectSpec.model_json_schema()

    @app.post("/api/v1/check")
    def check(project: ProjectSpec):
        project = restore_project(project, store.load())
        plan = compile_project(project)
        return sanitize_plan(plan, project)

    @app.get("/api/v1/plan")
    def plan():
        project = store.load()
        result = compile_project(project)
        return sanitize_plan(result, project)

    @app.put("/api/v1/view")
    def view(body: ViewRequest):
        return store.save_views(body.view, body.base_revision)

    @app.get("/api/v1/candidates")
    def candidates(source_dir: str = "src"):
        return scan_candidates(root, source_dir)

    @app.get("/api/v1/capabilities")
    def capabilities():
        from .operations import capabilities
        return capabilities()

    @app.get("/api/v1/providers")
    def providers():
        from .operations import providers
        return providers()

    @app.get("/api/v1/doctor")
    def doctor():
        from .operations import doctor
        return doctor(root)

    @app.post("/api/v1/clean")
    def clean(body: CleanRequest):
        return store.clean(body.runs_before)

    @app.post("/api/v1/migrate")
    def migration(body: dict):
        from .workspace import MigrationRequest
        from .migration import migrate
        value = MigrationRequest.model_validate(body)
        return migrate(Path(value.source), Path(value.destination) if value.destination else None, value.resolutions, value.apply)

    @app.post("/api/v1/shortcuts")
    def shortcuts(body: dict):
        from .workspace import ShortcutRequest
        from .shortcuts import create_shortcuts
        value = ShortcutRequest.model_validate(body)
        return create_shortcuts(Path(value.directory) if value.directory else None, project=root)

    @app.get("/api/v1/changes")
    def list_changes():
        project = store.load()
        return [sanitize_change(c, project) for c in store.changes()]

    @app.post("/api/v1/changes/architecture")
    def architecture(body: ArchitectureRequest):
        current = store.load()
        if current.revision != body.base_revision:
            raise Conflict("Architecture changed; reload before editing redacted values")
        return safe_change(changes.propose_architecture(root, restore_project(body.project, current), body.base_revision, body.title))

    @app.post("/api/v1/changes/implementation")
    def implementation(body: ImplementationRequest):
        return safe_change(changes.propose_implementation(root, body.module, body.candidate, body.title))

    @app.post("/api/v1/changes/{change_id}/accept")
    def accept(change_id: str, body: ReviewRequest):
        return safe_change(changes.accept(root, change_id, body.base_revision))

    @app.post("/api/v1/changes/{change_id}/reject")
    def reject(change_id: str):
        return safe_change(changes.reject(root, change_id))

    @app.post("/api/v1/changes/{change_id}/rollback")
    def rollback(change_id: str):
        return safe_change(changes.propose_rollback(root, change_id))

    @app.get("/api/v1/context/{module}")
    def context(module: str, level: str = "L2"):
        return build_context(root, module, level)

    @app.post("/api/v1/generate")
    def generate(body: GenerateRequest):
        from .providers import generate
        return safe_change(generate(root, body.module, body.level, body.provider, body.model))

    @app.post("/api/v1/probes/preview")
    def preview(body: PreviewRequest):
        project = store.load()
        module = next((m for m in project.modules if m.id == body.probe.module), None)
        result = evaluate_probe(body.probe, body.input, body.output, input_schema=module.contract.input if module else {}, output_schema=module.contract.output if module else {},
                                sensitive_fields=project.capture.sensitive_fields)
        return sanitize(result.model_dump(), project.capture.sensitive_fields)

    @app.get("/api/v1/runs")
    def runs():
        return store.runs()

    @app.post("/api/v1/runs", status_code=202)
    def start_run(body: RunRequest):
        project = store.load()
        if project.revision != body.base_revision:
            raise Conflict("Architecture changed; review the current version before running")
        plan = compile_project(project)
        if not plan.valid:
            raise FlowError("Compilation failed; inspect diagnostics before running")
        run_id = uuid.uuid4().hex
        runner = Runner(root)
        with runners_lock:
            if len(runners) >= 4:
                raise HTTPException(429, "At most four local runs may be queued or active")
            store.create_run(project, {}, run_id, status="queued")
            runners[run_id] = runner
            try:
                future = executor.submit(runner.run, body.input, run_id=run_id, project=project)
            except RuntimeError:
                runners.pop(run_id, None)
                store.finish(run_id, "interrupted", "unknown")
                raise FlowError("Local run executor is shutting down")
        def finished(completed):
            try:
                if completed.cancelled() or completed.exception() is not None:
                    status = "cancelled" if completed.cancelled() or runner.cancelled.is_set() else "failed"
                    store.event(RunEvent(run_id=run_id, time=now(), kind="run.error", revision=project.revision,
                                         data={"type": "InitializationError", "message": "Run initialization was cancelled or failed"}), project.capture.sensitive_fields)
                    store.event(RunEvent(run_id=run_id, time=now(), kind="run.finished", revision=project.revision,
                                         data={"status": status, "quality": "unknown"}), project.capture.sensitive_fields)
                    store.finish(run_id, status, "unknown")
            finally:
                with runners_lock:
                    runners.pop(run_id, None)
        future.add_done_callback(finished)
        return {"id": run_id, "status": "queued"}

    @app.get("/api/v1/runs/{run_id}")
    def run_detail(run_id: str):
        return store.run(run_id)

    @app.post("/api/v1/runs/{run_id}/{action}")
    def control(run_id: str, action: str):
        with runners_lock:
            store.control(run_id, action)
            if action == "cancel" and run_id in runners:
                runners[run_id].cancelled.set()
        return {"action": action, "run_id": run_id}

    @app.get("/api/v1/runs/{run_id}/events")
    async def events(run_id: str, request: Request, after: int = 0, stream: bool = False):
        if not stream:
            return store.events(run_id, after)
        try:
            after = max(after, int(request.headers.get("last-event-id", "0")))
        except ValueError:
            raise HTTPException(400, "Last-Event-ID must be an event sequence")

        async def feed():
            cursor, idle = after, 0
            while not await request.is_disconnected():
                batch = store.events(run_id, cursor, 1000)
                for event in batch:
                    cursor = event["sequence"]
                    yield f"id: {cursor}\nevent: run\ndata: {canonical(event)}\n\n"
                    if event["kind"] == "run.finished":
                        return
                if not batch:
                    idle += 1
                    if idle % 30 == 0:
                        yield ": heartbeat\n\n"
                    try:
                        if store.run(run_id)["status"] not in ("queued", "running", "paused"):
                            return
                    except FlowError:
                        if idle > 100:
                            return
                await asyncio.sleep(.1)
        return StreamingResponse(feed(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    @app.get("/api/v1/export/{format}")
    def export(format: str, run_id: str | None = None, current: bool = False, archify_checkout: str | None = None):
        from .export import render_export
        from .adapters import archify_ir, otel_payload, render_archify
        if format in ("otel", "archify-json"):
            data = otel_payload(root, run_id) if format == "otel" else archify_ir(root)
            return Response(canonical(data), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="flow.{format}.json"'})
        if format == "archify":
            if not archify_checkout:
                raise FlowError("Choose the pinned Archify checkout before exporting")
            path = root / ".cdaf/cache/exports" / (uuid.uuid4().hex + ".html")
            render_archify(root, Path(archify_checkout), path)
            return FileResponse(path, media_type="text/html", filename="flow.archify.html")
        data, media = render_export(root, format, run_id, current=current)
        return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="flow.{format}"'})

    static = Path(__file__).parent / "static"
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="studio")
    else:
        @app.get("/")
        def not_built():
            return JSONResponse({"detail": "Studio assets are missing; run npm ci and npm run build in web/"}, status_code=503)
    return app
