"""Persistent user project catalogue and a multi-project local application shell."""
from __future__ import annotations

import os
import sqlite3
import sys
import uuid
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from .examples import create_example
from .models import Model, ProjectSpec
from .paths import FlowError
from .storage import Store


def user_home() -> Path:
    override = os.environ.get("CDAF_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "ContractDrivenAIFlow"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/ContractDrivenAIFlow"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "contract-driven-ai-flow"


class Workspace:
    def __init__(self, root: Path | None = None):
        self.root = (root or user_home()).expanduser().resolve()
        (self.root / ".cdaf").mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / ".cdaf/workspace.sqlite3", timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _record(self, row):
        root = Path(row["path"])
        try:
            if not (root / "flow.yaml").is_file():
                raise FlowError("Project folder is unavailable")
            project = Store(root).load()
            return {"id": row["id"], "path": str(root), "name": project.name, "modules": len(project.modules), "available": True}
        except (OSError, ValueError, FlowError):
            return {"id": row["id"], "path": str(root), "name": root.name, "modules": 0, "available": False,
                    "problem": "Project folder or flow.yaml is unavailable or invalid"}

    def list(self):
        with self.connect() as db:
            rows = db.execute("SELECT id,path FROM projects ORDER BY rowid DESC").fetchall()
        return [self._record(row) for row in rows]

    def add(self, path: Path):
        path = path.expanduser().resolve()
        if not (path / "flow.yaml").is_file():
            raise FlowError(f"No flow.yaml in {path}; create a project or preview legacy migration")
        Store(path).load()
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO projects(id,path) VALUES (?,?)", (uuid.uuid4().hex, str(path)))
            row = db.execute("SELECT id,path FROM projects WHERE path=?", (str(path),)).fetchone()
        return self._record(row)

    def project(self, project_id: str) -> Store:
        with self.connect() as db:
            row = db.execute("SELECT path FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            raise FlowError("Project is not registered in this workspace")
        root = Path(row["path"])
        if not (root / "flow.yaml").is_file():
            raise FlowError(f"Project folder is unavailable: {root}; reopen the correct folder")
        return Store(root)

    def create(self, name: str, template: str = "blank", path: Path | None = None):
        if not name.strip() or len(name) > 160:
            raise FlowError("Project name must contain 1–160 characters")
        destination = (path or self.root / "projects" / uuid.uuid4().hex[:12]).expanduser().resolve()
        if destination.exists() and any(destination.iterdir()):
            raise FlowError("Choose an empty project directory; existing files are preserved")
        if template == "blank":
            Store(destination).save(ProjectSpec(name=name.strip()), None)
        else:
            create_example(destination, template)
            store = Store(destination)
            project = store.load()
            store.save(project.model_copy(update={"name": name.strip()}), project.revision)
        return self.add(destination)

    def remove(self, project_id: str):
        with self.connect() as db:
            db.execute("DELETE FROM projects WHERE id=?", (project_id,))
        return {"unlinked": project_id, "files_preserved": True}

    def bootstrap(self):
        # Serialize the first-use transaction across CLI/Studio launches.
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM projects LIMIT 1").fetchone():
                destination = self.root / "projects/data-pipeline"
                if not (destination / "flow.yaml").is_file():
                    create_example(destination)
                db.execute("INSERT INTO projects(id,path) VALUES (?,?)", (uuid.uuid4().hex, str(destination)))
        return {"home": str(self.root), "projects": self.list()}


class CreateProjectRequest(Model):
    name: str = "My project"
    template: str = "blank"
    path: str | None = None


class OpenProjectRequest(Model):
    path: str


class MigrationRequest(Model):
    source: str
    destination: str | None = None
    resolutions: dict = {}
    apply: bool = False


class ShortcutRequest(Model):
    directory: str | None = None


def create_workspace_app(root: Path, token: str, port: int = 8765, shutdown=None):
    import asyncio
    from .api import create_app, secure_app
    from .operations import capabilities, doctor

    workspace = Workspace(root)
    from .research.service import ResearchService
    from .research.routes import attach_research_routes
    research = ResearchService(root)
    children = {}
    stack = AsyncExitStack()
    lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app):
        workspace.bootstrap()
        async with stack:
            try:
                yield
            finally:
                cancel_children()
                await asyncio.to_thread(research.close)
                app.state.models.close()

    app = FastAPI(title="Contract-Driven AI Flow Workspace", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.session_token = token
    app.state.research = research
    app.state.session_token, app.state.local_port = token, port
    attach_research_routes(app, research)

    def cancel_children():
        for child in children.values():
            child.state.cancel_runs()

    @app.get("/api/v1/studio")
    def studio_status():
        return {"pid": os.getpid(), "project": str(workspace.root), "port": port, "mode": "workspace"}

    @app.post("/api/v1/studio/shutdown")
    def studio_shutdown():
        if shutdown is None:
            raise FlowError("This server is managed by its foreground owner")
        cancel_children()
        shutdown()
        return {"status": "stopping"}

    @app.get("/api/v1/workspace")
    def workspace_detail():
        return {"home": str(workspace.root), "projects": workspace.list(), "capabilities": capabilities()}

    @app.post("/api/v1/workspace/projects", status_code=201)
    def create(body: CreateProjectRequest):
        return workspace.create(body.name, body.template, Path(body.path) if body.path else None)

    @app.post("/api/v1/workspace/open")
    def open_project(body: OpenProjectRequest):
        return workspace.add(Path(body.path))

    @app.delete("/api/v1/workspace/projects/{project_id}")
    def remove(project_id: str):
        return workspace.remove(project_id)

    @app.get("/api/v1/doctor")
    def installation():
        return doctor()

    @app.get("/api/v1/capabilities")
    def features():
        return capabilities()

    @app.post("/api/v1/migrate")
    def migration(body: MigrationRequest):
        from .migration import migrate
        result = migrate(Path(body.source), Path(body.destination) if body.destination else None, body.resolutions, body.apply)
        if body.apply and not result["issues"]:
            workspace.add(Path(result["destination"]))
        return result

    @app.post("/api/v1/shortcuts")
    def shortcuts(body: ShortcutRequest):
        from .shortcuts import create_shortcuts
        return create_shortcuts(Path(body.directory) if body.directory else None, workspace=workspace.root)

    # Select a registered project without changing any process-wide active root.
    # Each child has its own runners, storage and lifespan. Tokens are shared only
    # within this authenticated loopback service.
    @app.middleware("http")
    async def projects(request, call_next):
        path = request.url.path
        if path.startswith("/p/"):
            project_id = path.split("/")[2]
            async with lock:
                try:
                    store = workspace.project(project_id)
                except FlowError as exc:
                    from fastapi.responses import JSONResponse
                    return JSONResponse({"detail": str(exc)}, status_code=404)
                if project_id not in children:
                    child = create_app(store.root, token=token, port=port)
                    await stack.enter_async_context(child.router.lifespan_context(child))
                    children[project_id] = child
                    # Keep dynamically added project routes before the static catchall.
                    app.mount("/p/" + project_id, child)
                    route = app.router.routes.pop()
                    app.router.routes.insert(0, route)
        return await call_next(request)

    secure_app(app, token, port)
    app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="workspace")
    return app
