from __future__ import annotations

import json
import secrets
import sys
from pathlib import Path
from typing import Annotated

import typer

from . import __version__
from .compiler import compile_project
from .models import ProjectSpec
from .paths import FlowError, project_root
from .privacy import sanitize_change, sanitize_plan
from .storage import Store

app = typer.Typer(name="cdaf", help="Contract-Driven AI Flow · Design, review, execute and inspect.\n\nStart: cdaf studio   |   Example: cdaf demo   |   Diagnose: cdaf doctor", no_args_is_help=True, pretty_exceptions_enable=False, context_settings={"help_option_names": ["-h", "--help"]})
projects_app = typer.Typer(help="Create, register and list projects in the local workspace.")
app.add_typer(projects_app, name="projects")
research_app = typer.Typer(help="Observe existing scientific Python analyses and inspect their data evidence.")
app.add_typer(research_app, name="research")
models_app = typer.Typer(help="Configure shared model profiles and explicit credential references.")
app.add_typer(models_app, name="models")


@models_app.command("list")
def models_list(project: Path = typer.Option(Path("."), "--project", "-p")):
    from .settings.service import ModelSettingsService
    output([profile.model_dump(mode="json") for profile in ModelSettingsService(project).list()])


@models_app.command("configure")
def models_configure(identifier: str, protocol: str = "openai-compatible", base_url: str = "", model: str = "",
                     credential_env: str = "", prompt_key: bool = False, timeout: float = 60,
                     project: Path = typer.Option(Path("."), "--project", "-p")):
    from .settings.models import ProviderProfile
    from .settings.service import ModelSettingsService
    if credential_env and prompt_key:
        raise typer.BadParameter("Choose a credential environment reference or an OS-vault prompt")
    profile = guard(ProviderProfile, id=identifier, protocol=protocol, base_url=base_url, default_model=model,
                    timeout_seconds=timeout, credential_ref="env:"+credential_env if credential_env else None)
    secret = __import__('getpass').getpass("Model credential (stored in the OS vault): ") if prompt_key else None
    output(guard(ModelSettingsService(project).save, profile, secret=secret))


@models_app.command("test")
def models_test(identifier: str, inference: bool = False, model: str = "",
                project: Path = typer.Option(Path("."), "--project", "-p")):
    import asyncio
    from .settings.service import ModelSettingsService
    service = ModelSettingsService(project)
    try:
        result = asyncio.run(service.test(identifier, inference=inference, model=model or None))
        output(result)
        if result.status == "error":
            raise typer.Exit(1)
        if result.status == "cancelled":
            raise typer.Exit(130)
    except KeyboardInterrupt:
        service.close()
        raise typer.Exit(130)


def output(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    import click
    context = click.get_current_context(silent=True)
    options = context.find_root().obj if context else {}
    options = options or {}
    human = options.get("format") == "human" or options.get("format", "auto") == "auto" and sys.stdout.isatty()
    if human:
        from rich.console import Console
        from rich.pretty import Pretty
        from rich.table import Table
        console = Console(no_color=options.get("no_color") or bool(__import__('os').environ.get("NO_COLOR")))
        if isinstance(value, list) and value and all(isinstance(row, dict) for row in value):
            columns = list(dict.fromkeys(key for row in value for key in row))[:8]
            table = Table(*columns, show_lines=False)
            for row in value:
                table.add_row(*(str(row.get(key, "")) for key in columns))
            console.print(table)
        else:
            console.print(Pretty(value))
    else:
        typer.echo(json.dumps(value, ensure_ascii=False, indent=2))


def read_json(path: Path):
    try:
        return json.loads(sys.stdin.read() if str(path) == "-" else path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise FlowError(f"Invalid JSON in {path}: line {exc.lineno}, column {exc.colno}") from exc


def guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (FlowError, ValueError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context, version: bool = typer.Option(False, "--version", help="Print version"),
         json_output: bool = typer.Option(False, "--json", help="Stable JSON output, also used automatically when piped"),
         human: bool = typer.Option(False, "--human", help="Readable terminal output even when redirected"),
         no_color: bool = typer.Option(False, "--no-color", help="Disable terminal colors")):
    if json_output and human:
        raise typer.BadParameter("Choose one of --json or --human")
    ctx.obj = {"format": "json" if json_output else "human" if human else "auto", "no_color": no_color}
    if version:
        typer.echo(__version__)
        raise typer.Exit()


@app.command()
def init(target: Path = typer.Option(Path("."), "--target", "-t")):
    """Create a contract-first project without overwriting existing definitions."""
    if (target / "flow.yaml").exists():
        raise typer.BadParameter("flow.yaml already exists")
    guard(Store(target).save, ProjectSpec(), None)
    typer.echo(f"Created {target.resolve() / 'flow.yaml'}; use cdaf studio to design modules")


@app.command()
def check(project: Path = typer.Option(None, "--project", "-p")):
    """Validate references, ports, schemas, hierarchy, cycles and probe expressions."""
    root = guard(project_root, project)
    plan = compile_project(guard(Store(root).load))
    output({"valid": plan.valid, "revision": plan.revision, "diagnostics": [d.model_dump() for d in plan.diagnostics]})
    if not plan.valid:
        raise typer.Exit(1)


@app.command()
def plan(project: Path = typer.Option(None, "--project", "-p")):
    """Inspect the flattened execution plan without running project code."""
    spec = guard(Store(guard(project_root, project)).load)
    output(sanitize_plan(compile_project(spec), spec))


@app.command()
def run(input: Path = typer.Option(None, "--input", "-i"), project: Path = typer.Option(None, "--project", "-p")):
    """Execute a new run; input is a UTF-8 JSON file. Quality failures exit 2."""
    from .runtime import Runner
    root = guard(project_root, project)
    value = guard(read_json, input) if input else {}
    result = guard(Runner(root).run, value)
    output({k: result[k] for k in ("id", "status", "quality", "revision")})
    if result["status"] != "completed":
        raise typer.Exit(1)
    if result["quality"] != "passed":
        raise typer.Exit(2)


@app.command()
def demo(target: Path = typer.Option(Path("cdaf-demo"), "--target", "-t"), example: str = "data-pipeline", serve: bool = typer.Option(False, "--serve")):
    """Create and run success/failure fixtures with no API key; optionally open Studio."""
    from .examples import create_example, definition
    from .runtime import Runner
    root = guard(create_example, target, example)
    _, _, success, failure = definition(example)
    records = []
    for label, value in (("success", success), ("failure", failure)):
        result = guard(Runner(root).run, value)
        records.append({"case": label, "id": result["id"], "execution": result["status"], "quality": result["quality"]})
    from .export import export_project
    exported = guard(export_project, root, "html", root / "flow/demo.html")
    output({"project": str(root), "runs": records, "graph": str(exported), "studio": f"cdaf studio --project \"{root}\""})
    if any(r["execution"] != "completed" or r["quality"] != ("passed" if r["case"] == "success" else "failed") for r in records):
        typer.echo("Demo acceptance failed; inspect recorded worker/contract errors", err=True)
        raise typer.Exit(1)
    if serve:
        studio(project=root, background=True)


@app.command()
def studio(
    project: Annotated[Path | None, typer.Option("--project", "-p")] = None,
    port: Annotated[int | None, typer.Option(min=1024, max=65535, help="Default: first free port in 8765–8785")] = None,
    open_browser: Annotated[bool, typer.Option("--open/--no-open")] = True,
    background: Annotated[bool, typer.Option("--background/--foreground", help="Default: independent background service")] = True,
    stop: Annotated[bool, typer.Option(help="Gracefully stop this project's managed Studio")] = False,
    workspace: Annotated[bool, typer.Option(help="Open the project workspace even inside an existing project")] = False,
    home: Annotated[Path | None, typer.Option(help="Workspace data directory; also configurable with CDAF_HOME")] = None,
    status: Annotated[bool, typer.Option(help="Inspect the managed service without starting it")] = False,
):
    """Serve the local Web UI; --background persists after the launcher exits."""
    from .studio import active, public_state, read_state, serve, start, stop as stop_studio
    from .workspace import user_home
    if project is not None and (workspace or home is not None):
        raise typer.BadParameter("Choose --project or --workspace/--home")
    if project is not None:
        root = guard(project_root, project)
    elif workspace or home is not None:
        workspace = True
        root = (home or user_home()).resolve()
    else:
        try:
            root = project_root()
        except FlowError:
            root, workspace = user_home(), True
    if status:
        record = read_state(root)
        output(public_state(root, record, reused=True) if active(root, record) else {"running": False, "project": str(root)})
        return
    if stop:
        output(guard(stop_studio, root))
        return
    if background:
        result = guard(start, root, port, workspace=workspace)
        output(result)
        if open_browser:
            import webbrowser
            webbrowser.open(result["url"])
        return
    if workspace:
        from .workspace import Workspace
        Workspace(root).bootstrap()
    port = port or 8765
    token = secrets.token_urlsafe(32)
    url = f"http://127.0.0.1:{port}/#session={token}"
    typer.echo(f"Studio: {url}")
    if open_browser:
        import threading
        import webbrowser
        threading.Timer(1, lambda: webbrowser.open(url)).start()
    serve(root, port, token=token, workspace=workspace)


@app.command()
def context(module: str, project: Path = typer.Option(None, "--project", "-p"), level: str = "L2"):
    """Show exactly which symbols, contracts and sanitized fixtures a model sees."""
    from .context import build_context
    output(guard(build_context, guard(project_root, project), module, level))


@app.command()
def generate(module: str, project: Path = typer.Option(None, "--project", "-p"), level: str = "L2", provider: str = "mock", model: str = typer.Option(None), candidate: Path = typer.Option(None)):
    """Create a reviewed implementation proposal; a candidate file works offline."""
    from .changes import propose_implementation
    from .providers import generate as generate_candidate
    root = guard(project_root, project)
    if candidate:
        result = guard(propose_implementation, root, module, candidate.read_text(encoding="utf-8"))
    else:
        result = guard(generate_candidate, root, module, level, provider, model)
    output(sanitize_change(result, Store(root).load()))
    if result.status == "invalid":
        raise typer.Exit(1)


@app.command()
def review(change: str = typer.Argument(None), project: Path = typer.Option(None, "--project", "-p"), accept: bool = False, reject: bool = False, rollback: bool = False):
    """Inspect proposals; --accept explicitly applies the displayed stored candidate."""
    from . import changes
    if sum((accept, reject, rollback)) > 1:
        raise typer.BadParameter("Choose one of --accept, --reject or --rollback")
    if not change and any((accept, reject, rollback)):
        raise typer.BadParameter("Specify the proposal ID to review")
    root = guard(project_root, project)
    store = Store(root)
    if not change:
        output([sanitize_change(c, store.load()) for c in store.changes()])
    elif accept:
        output(sanitize_change(guard(changes.accept, root, change, store.load().revision), store.load()))
    elif reject:
        output(sanitize_change(guard(changes.reject, root, change), store.load()))
    elif rollback:
        output(sanitize_change(guard(changes.propose_rollback, root, change), store.load()))
    else:
        output(sanitize_change(guard(store.change, change), store.load()))


@app.command()
def propose(spec: Path, project: Path = typer.Option(None, "--project", "-p"), title: str = "Architecture proposal"):
    """Submit architecture JSON from a person or an external AI agent for review."""
    from .changes import propose_architecture
    root = guard(project_root, project)
    proposed = guard(ProjectSpec.model_validate, guard(read_json, spec))
    output(sanitize_change(guard(propose_architecture, root, proposed, Store(root).load().revision, title), Store(root).load()))


@app.command()
def scan(project: Path = typer.Option(None, "--project", "-p"), source_dir: str = "src"):
    """List source candidates with file-qualified identities; does not change topology."""
    from .source import scan_candidates
    output(guard(scan_candidates, guard(project_root, project), source_dir))


@app.command()
def probe(expression: str, sample: Path, input_boundary: bool = False, kind: str = "assertion", pointer: str = "", policy: str = "continue"):
    """Preflight a probe against a local JSON sample without running a module."""
    from .models import CapturePolicy, ProbeSpec
    from .probes import evaluate_probe
    value = guard(read_json, sample)
    spec = guard(ProbeSpec, id="preview", module="preview", expression=expression, kind=kind, pointer=pointer, policy=policy, boundary="input" if input_boundary else "output")
    result = evaluate_probe(spec, value if input_boundary else {}, {} if input_boundary else value, sensitive_fields=CapturePolicy().sensitive_fields)
    output(result)
    if result.status != "pass":
        raise typer.Exit(2)


@app.command()
def export(format: str = "html", output_path: Path = typer.Option(Path("flow-export.html"), "--output", "-o"), project: Path = typer.Option(None, "--project", "-p"), run_id: str = typer.Option(None, "--run"), archify_checkout: Path = typer.Option(None), current: bool = typer.Option(False, help="Export the current reviewed architecture without historical events")):
    """Export HTML/SVG/PNG/Mermaid/JSON, OTLP traces or optional pinned Archify views."""
    from .export import export_project
    root = guard(project_root, project)
    if current and format in ("otel", "archify-json", "archify"):
        raise typer.BadParameter("--current is supported by html/svg/png/mermaid/json exports")
    if format in ("otel", "archify-json"):
        from .adapters import archify_ir, otel_payload
        from .models import canonical
        from .storage import atomic_write
        data = guard(otel_payload, root, run_id) if format == "otel" else guard(archify_ir, root)
        guard(atomic_write, output_path, canonical(data))
        typer.echo(output_path.resolve())
    elif format == "archify":
        from .adapters import render_archify
        if archify_checkout is None:
            raise typer.BadParameter("--archify-checkout is required for the optional renderer")
        typer.echo(guard(render_archify, root, archify_checkout, output_path))
    else:
        typer.echo(guard(export_project, root, format, output_path, run_id, current=current))


@app.command()
def migrate(source: Path, destination: Path = typer.Option(None, "--destination"), resolutions: Path = typer.Option(None), apply: bool = False):
    """Preview legacy migration; --apply writes only to a separate empty destination."""
    from .migration import migrate as migrate_legacy
    result = guard(migrate_legacy, source, destination, guard(read_json, resolutions) if resolutions else {}, apply)
    output(result)
    if result["issues"]:
        raise typer.Exit(1)


@app.command()
def clean(project: Path = typer.Option(None, "--project", "-p"), runs_before: str = typer.Option(None)):
    """Clear cache; optionally prune completed runs before an ISO timestamp. Preserve definitions."""
    output(guard(Store(guard(project_root, project)).clean, runs_before))


@projects_app.command("list")
def projects_list():
    """List registered directories; missing directories have available=false."""
    from .workspace import Workspace
    output(Workspace().bootstrap()["projects"])


@projects_app.command("create")
def projects_create(name: str = "My project", template: str = "blank", target: Path = typer.Option(None, "--target", "-t")):
    """Create a blank or runnable example project and register it."""
    from .workspace import Workspace
    output(guard(Workspace().create, name, template, target))


@projects_app.command("add")
def projects_add(path: Path):
    """Register an existing flow.yaml directory without changing its architecture."""
    from .workspace import Workspace
    output(guard(Workspace().add, path))


@projects_app.command("remove")
def projects_remove(project_id: str):
    """Unlink a project from the catalogue; all files remain on disk."""
    from .workspace import Workspace
    output(Workspace().remove(project_id))


@app.command()
def doctor(project: Path = typer.Option(None, "--project", "-p")):
    """Diagnose the installation, optional providers and selected project."""
    from .operations import doctor
    result = guard(doctor, guard(project_root, project) if project else None)
    output(result)
    if not result["healthy"]:
        raise typer.Exit(1)


@app.command()
def capabilities():
    """Show the shared Web/CLI feature catalogue and extension boundaries."""
    from .operations import capabilities
    output(capabilities())


@app.command()
def shortcut(directory: Path = typer.Option(None), project: Path = typer.Option(None, "--project", "-p"), home: Path = typer.Option(None)):
    """Create Desktop launch/stop shortcuts for this installed Python environment."""
    from .shortcuts import create_shortcuts
    output(guard(create_shortcuts, directory, project=guard(project_root, project) if project else None, workspace=home))


@app.command()
def runs(run_id: str = typer.Argument(None), project: Path = typer.Option(None, "--project", "-p"), events: bool = False, after: int = 0, action: str = typer.Option(None)):
    """List runs or inspect one; --events pages evidence, --action pause|resume|cancel."""
    store = Store(guard(project_root, project))
    store.recover_runs()
    if action:
        if not run_id or events:
            raise typer.BadParameter("Specify one run ID and an action without --events")
        record = guard(store.run, run_id)
        if record["status"] not in ("queued", "running", "paused"):
            raise typer.BadParameter("Run has finished; create a new run to execute again")
        guard(store.control, run_id, action)
        output({"run_id": run_id, "action": action})
    elif run_id:
        output(guard(store.events, run_id, after) if events else guard(store.run, run_id))
    elif events:
        raise typer.BadParameter("Specify a run ID for --events")
    else:
        output(store.runs())


@app.command()
def view(project: Path = typer.Option(None, "--project", "-p"), input: Path = typer.Option(None, "--input", "-i"), base_revision: str = typer.Option(None)):
    """Inspect view preferences or save JSON with a view base revision."""
    store = Store(guard(project_root, project))
    if input:
        if not base_revision:
            raise typer.BadParameter("--base-revision is required when saving a view")
        output(guard(store.save_views, guard(read_json, input), base_revision))
    else:
        output(store.views())


@app.command()
def observe(script: Path, python: Path = typer.Option(None, "--python", help="Scientific Python interpreter"),
            project: Path = typer.Option(None, "--project", "-p"), capture: str = "summary",
            argument: list[str] = typer.Option(None, "--arg", help="Repeat for script arguments"),
            probe_file: Path = typer.Option(None, "--probes"), instrument: str = "auto",
            adapter: list[str] = typer.Option(None, "--adapter", help="Explicitly enable an installed scientific adapter")):
    """Run existing analysis code and record bounded native data observations."""
    from .research.models import ProbeSpec
    from .research.service import ResearchService
    try:
        probes = [ProbeSpec.model_validate(p) for p in read_json(probe_file)] if probe_file else None
        with ResearchService(project or script.resolve().parent) as service:
            handle = service.start_analysis(script, interpreter=python, arguments=argument or [], mode=capture, probes=probes, instrument=instrument, adapters=adapter or [])
            try:
                record = service.wait(handle.run_id)
            except KeyboardInterrupt:
                service.cancel(handle.run_id)
                record = service.wait(handle.run_id, timeout=5)
            output(record)
            if record["status"] != "completed":
                raise typer.Exit(130 if record["status"] == "cancelled" else 1)
    except (ValueError, OSError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2)


@research_app.command("runs")
def research_runs(project: Path = typer.Option(Path("."), "--project", "-p")):
    """List recorded analyses without rerunning their code."""
    from .research.store import ExperimentStore
    output(ExperimentStore(project).runs())


@research_app.command("inspect")
def research_inspect(snapshot: str, project: Path = typer.Option(Path("."), "--project", "-p")):
    """Inspect one immutable observed value by snapshot ID."""
    from .research.store import ExperimentStore
    try:
        output(ExperimentStore(project).snapshot(snapshot))
    except LookupError:
        typer.echo("Scientific snapshot is unavailable", err=True)
        raise typer.Exit(2)


@research_app.command("export")
def research_export(run_id: str, output_path: Path = typer.Option(Path("research-evidence.json"), "--output", "-o"),
                    project: Path = typer.Option(Path("."), "--project", "-p")):
    """Export sanitised machine-readable evidence; no analysis is executed."""
    from .research.service import ResearchService
    from .storage import atomic_write
    with ResearchService(project) as service:
        payload = {"schema_version": 1, "run": service.store.run(run_id), "snapshots": [],
            "events": [], "source": service.source(run_id)}
        snapshot_cursor = None
        while snapshots := service.store.snapshots(run_id, latest=False, limit=1000, after=snapshot_cursor):
            payload["snapshots"].extend(s.model_dump(mode="json") for s in snapshots)
            snapshot_cursor = snapshots[-1].id
        cursor = 0
        while page := service.events(run_id, cursor, 1000):
            payload["events"].extend(page)
            cursor = page[-1]["sequence"]
        atomic_write(output_path, json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2))
    output({"path": str(output_path.resolve()), "run_id": run_id})


@research_app.command("migrate")
def research_migrate(source: Path, destination: Path, apply: bool = False):
    """Preview legacy evidence import; --apply writes a separate destination."""
    from dataclasses import asdict
    from .research.legacy import import_legacy
    output(asdict(import_legacy(source, destination, preview=not apply)))
