"""P3 batch CLI: project commands over the accepted ProjectApplication.

Every command accepts ``--project`` (the project root) and an optional
``--host`` (the machine host registry; it defaults to the project root for a
standalone run). ``open`` only registers; ``index`` publishes explicitly. The
CLI never re-implements planning or execution.
"""

from __future__ import annotations

from pathlib import Path

import typer

from .application import ProjectApplication
from .commands import execute_command


def register_project_cli(app, output):
    project_app = typer.Typer(
        help="Register, index, inspect, plan and run one project through its accepted application."
    )
    app.add_typer(project_app, name="project")

    def safe(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ValueError, LookupError, OSError, TimeoutError, KeyError) as error:
            from ..agent.privacy import clean_text

            typer.echo(clean_text(str(error)), err=True)
            raise typer.Exit(1)

    def perform(application, command, arguments, wait=False):
        try:
            if command == "open":
                output(execute_command(command, arguments, application, None))
                return
            project = application.open(arguments["root"])
            arguments = {**arguments, "project_id": project.id}
            value = execute_command(command, arguments, application, None)
            if wait:
                workbench = application.workbench(arguments["project_id"])
                task_id = value["id"]
                try:
                    task = workbench.jobs.wait(task_id, 3600)
                except KeyboardInterrupt:
                    workbench.jobs.cancel(task_id)
                    task = workbench.jobs.wait(task_id, 20)
                value = task.model_dump(mode="json")
                output(value)
                if value["status"] in ("failed", "cancelled", "interrupted"):
                    raise typer.Exit(130 if value["status"] == "cancelled" else 1)
                return
            output(value)
        finally:
            application.close()

    @project_app.command("open")
    def project_open(
        path: Path = typer.Argument(..., help="Project root to register"),
        project: Path = typer.Option(Path("."), "--project", "-p"),
        host: Path | None = typer.Option(None, "--host"),
    ):
        """Register an existing project root; never indexes or executes it."""
        safe(lambda: perform(ProjectApplication(host or path), "open", {"path": str(path)}))

    @project_app.command("index")
    def project_index(
        project: Path = typer.Option(Path("."), "--project", "-p"),
        host: Path | None = typer.Option(None, "--host"),
    ):
        """Publish a new inert revision of the project's current files."""
        safe(lambda: perform(ProjectApplication(host or project), "index", {"root": project}))

    @project_app.command("info")
    def project_info(
        project: Path = typer.Option(Path("."), "--project", "-p"),
        host: Path | None = typer.Option(None, "--host"),
    ):
        """Show identity, latest revision and authored entries."""
        safe(lambda: perform(ProjectApplication(host or project), "info", {"root": project}))

    @project_app.command("graph")
    def project_graph(
        view: str = typer.Option("code", "--view"),
        scope: str = typer.Option("", "--scope"),
        revision: str = typer.Option("", "--revision"),
        project: Path = typer.Option(Path("."), "--project", "-p"),
        host: Path | None = typer.Option(None, "--host"),
    ):
        """Render the frozen project graph slice for a revision."""
        safe(
            lambda: perform(
                ProjectApplication(host or project),
                "graph",
                {
                    "root": project,
                    "view": view,
                    "scope_id": scope or None,
                    "revision_id": revision or None,
                },
            )
        )

    @project_app.command("entries")
    def project_entries(
        save: Path | None = typer.Option(None, "--save"),
        project: Path = typer.Option(Path("."), "--project", "-p"),
        host: Path | None = typer.Option(None, "--host"),
    ):
        """List entries and candidates, or save a JSON array of run configurations."""
        safe(
            lambda: perform(
                ProjectApplication(host or project),
                "entries",
                {"root": project, "save": str(save) if save else None},
            )
        )

    @project_app.command("plan")
    def project_plan(
        entry: str = typer.Option(..., "--entry"),
        revision: str = typer.Option("", "--revision"),
        scope: str = typer.Option("compute", "--scope"),
        run: str = typer.Option("", "--run"),
        targets: Path | None = typer.Option(None, "--targets"),
        instances: str = typer.Option("", "--instances"),
        project: Path = typer.Option(Path("."), "--project", "-p"),
        host: Path | None = typer.Option(None, "--host"),
    ):
        """Freeze a compute/probes/replot plan without executing it."""
        safe(
            lambda: perform(
                ProjectApplication(host or project),
                "plan",
                {
                    "root": project,
                    "configuration_id": entry,
                    "revision_id": revision or None,
                    "scope": scope,
                    "run_id": run or None,
                    "targets": str(targets) if targets else None,
                    "instances": instances or None,
                },
            )
        )

    @project_app.command("run")
    def project_run(
        plan: str = typer.Option(..., "--plan"),
        project: Path = typer.Option(Path("."), "--project", "-p"),
        host: Path | None = typer.Option(None, "--host"),
    ):
        """Execute a frozen plan and wait; Ctrl+C cancels its owned job."""
        safe(
            lambda: perform(
                ProjectApplication(host or project), "run", {"root": project, "plan_id": plan}, wait=True
            )
        )
