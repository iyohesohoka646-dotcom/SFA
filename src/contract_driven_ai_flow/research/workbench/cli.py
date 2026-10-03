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
                result = asyncio.run(
                    dispatch(
                        "workbench." + command,
                        arguments,
                        service=service,
                        settings=settings,
                    )
                )
                if result.status != "ok":
                    raise ValueError(result.error)
                value = result.data
                if wait:
                    task_id = value["id"]
                    try:
                        value = service.workbench.jobs.wait(task_id, 3600).model_dump(
                            mode="json"
                        )
                    except KeyboardInterrupt:
                        service.workbench.jobs.cancel(task_id)
                        value = service.workbench.jobs.wait(task_id, 20).model_dump(
                            mode="json"
                        )
                    if command == "ask" and value.get("receipt", {}).get("context_id"):
                        value["context"] = service.workbench.store.get(
                            "contexts", value["receipt"]["context_id"]
                        )
                output(value)
                if wait and (
                    value["status"] in ("failed", "cancelled", "interrupted")
                    or value["calculation_status"]
                    in ("failed", "timeout", "cancelled", "interrupted")
                ):
                    raise typer.Exit(130 if value["status"] == "cancelled" else 1)
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

    @app.command("import")
    def import_source(
        path: Path,
        python: str = typer.Option("", "--python"),
        project: Path = typer.Option(Path("."), "--project", "-p"),
    ):
        """Parse source without execution; select it for subsequent plans."""

        def run():
            with ResearchService(project) as service:
                wb = service.workbench
                analysis = wb.import_source(path)
                config = wb.configurations.load()
                wb.configure(
                    config.model_copy(
                        update={
                            "script": analysis.path,
                            **({"interpreter": python} if python else {}),
                        }
                    ),
                    expected_revision=config.revision,
                )
                output(analysis)

        safe(run)

    @app.command("plan")
    def plan(
        analysis: str,
        scope: str = "compute",
        run_id: str = typer.Option("", "--run"),
        target_scope: Path | None = typer.Option(None, "--target-scope"),
        snapshots: list[str] = typer.Option([], "--snapshot"),
        instances: list[str] = typer.Option([], "--instance"),
        project: Path = typer.Option(Path("."), "--project", "-p"),
    ):
        """Freeze an explicit compute/probes/replot plan without executing it."""

        def invoke():
            selector = (
                json.loads(target_scope.read_text(encoding="utf-8-sig"))
                if target_scope
                else None
            )
            return perform(
                project,
                "plan",
                {
                    "analysis_id": analysis,
                    "scope": scope,
                    "run_id": run_id or None,
                    "target_scope": selector,
                    "snapshot_ids": snapshots,
                    "instance_ids": instances or None,
                },
            )

        safe(invoke)

    @app.command("run")
    def run(
        plan_id: str = typer.Option(..., "--plan"),
        project: Path = typer.Option(Path("."), "--project", "-p"),
    ):
        """Execute a frozen plan and wait; Ctrl+C cancels its owned job."""
        safe(perform, project, "execute", {"plan_id": plan_id}, wait=True)

    @app.command("config")
    def config(
        input_file: Path | None = typer.Option(None, "--input"),
        project: Path = typer.Option(Path("."), "--project", "-p"),
    ):
        """Read configuration, or save a JSON configuration with its revision."""
        if input_file is None:
            safe(perform, project, "configuration", {})
        else:

            def run():
                value = json.loads(input_file.read_text(encoding="utf-8-sig"))
                perform(
                    project,
                    "configure",
                    {"config": value, "expected_revision": value["revision"]},
                )

            safe(run)

    @app.command("probes")
    def probes(
        run_id: str = typer.Option("", "--run"),
        evaluate: bool = False,
        replot: bool = False,
        definition: str = typer.Option("", "--add"),
        binding: str = "*",
        budget_ms: int = 30000,
        project: Path = typer.Option(Path("."), "--project", "-p"),
    ):
        """List definitions/results, add a probe, or explicitly evaluate saved evidence."""

        def run():
            if evaluate and replot:
                raise ValueError("Choose --evaluate or --replot")
            if evaluate or replot:
                if not run_id:
                    raise ValueError("--run is required")
                return perform(
                    project,
                    "replot" if replot else "evaluate",
                    {"run_id": run_id},
                    wait=True,
                )
            if run_id:
                return perform(project, "outputs", {"run_id": run_id})
            with ResearchService(project) as service:
                wb = service.workbench
                if definition:
                    wb.catalog.resolve(definition)
                    config = wb.configurations.load()
                    output(
                        wb.configure(
                            config.model_copy(
                                update={
                                    "probes": [
                                        *config.probes,
                                        ProbeInstance(
                                            definition_id=definition,
                                            binding=binding,
                                            budget_ms=budget_ms,
                                        ),
                                    ]
                                }
                            ),
                            expected_revision=config.revision,
                        )
                    )
                else:
                    output(wb.catalog.definitions())

        safe(run)

    @app.command("tools")
    def tools(
        scan: bool = False,
        python: str = typer.Option("", "--python"),
        install: str = "",
        remove: str = "",
        disable: str = "",
        describe: str = "",
        project: Path = typer.Option(Path("."), "--project", "-p"),
    ):
        """Public catalog and explicit project-owned plotting environment management."""

        def run():
            if sum(bool(x) for x in (scan, install, remove, disable, describe)) > 1:
                raise ValueError("Choose one tool operation")
            with ResearchService(project) as service:
                manager = service.workbench.tools
                if describe:
                    output(manager.describe(describe))
                elif install:
                    output(manager.install(install))
                elif remove:
                    output(manager.remove(remove))
                elif disable:
                    manager.disable(disable)
                    output(manager.catalog())
                elif scan:
                    output(manager.scan(python or None))
                else:
                    output(manager.catalog())

        safe(run)

    @app.command("ask")
    def ask(
        analysis: str,
        question: str,
        role: str = "explain",
        object_id: str = typer.Option("", "--object"),
        run_id: str = typer.Option("", "--run"),
        provider: str = "",
        model: str = "",
        project: Path = typer.Option(Path("."), "--project", "-p"),
    ):
        """Automatic environment/tool harness; configuration shares model settings."""

        def run():
            from .configuration import ConfigurationStore

            policy = next(
                p for p in ConfigurationStore(project).load().harness if p.role == role
            )
            policy = HarnessPolicy.model_validate(
                {
                    **policy.model_dump(),
                    **({"provider_id": provider} if provider else {}),
                    **({"model": model} if model else {}),
                }
            )
            perform(
                project,
                "ask",
                {
                    "analysis_id": analysis,
                    "question": question,
                    "object_id": object_id or None,
                    "run_id": run_id or None,
                    "policy": policy.model_dump(mode="json"),
                },
                wait=True,
            )

        safe(run)

    @app.command("changes")
    def changes(
        proposal: str = "",
        action: str = "list",
        input_file: Path | None = typer.Option(None, "--input"),
        project: Path = typer.Option(Path("."), "--project", "-p"),
    ):
        """Review scoped proposals; accept/reject/rollback require explicit commands."""

        def run():
            if action == "list":
                perform(project, "changes", {})
            elif action == "propose" and input_file:
                perform(
                    project,
                    "propose",
                    json.loads(input_file.read_text(encoding="utf-8-sig")),
                )
            elif action in ("accept", "reject", "rollback", "validate") and proposal:
                perform(project, action, {"proposal_id": proposal})
            else:
                raise ValueError(
                    "Use --action list|propose|accept|reject|rollback|validate with --input or --proposal"
                )

        safe(run)

    @app.command("migrate-config")
    def migrate_config(
        apply: bool = False, project: Path = typer.Option(Path("."), "--project", "-p")
    ):
        """Preview migration; --apply backs up and preserves research.yaml."""
        safe(perform, project, "migrate", {"apply": apply})

    @app.command("resources")
    def resources(
        import_file: Path | None = typer.Option(None, "--import"),
        enable: str = "",
        disable: str = "",
        project: Path = typer.Option(Path("."), "--project", "-p"),
    ):
        """List capabilities or stage/review/enable a declarative extension."""

        def invoke():
            if sum(bool(value) for value in (import_file, enable, disable)) > 1:
                raise ValueError("Choose --import, --enable or --disable")
            if import_file:
                return perform(
                    project,
                    "resources.import",
                    {
                        "manifest": json.loads(
                            import_file.read_text(encoding="utf-8-sig")
                        )
                    },
                )
            if enable or disable:
                return perform(
                    project,
                    "resources.enable" if enable else "resources.disable",
                    {"id": enable or disable},
                )
            return perform(project, "resources", {})

        safe(invoke)

    @app.command("settings")
    def settings(
        input_file: Path | None = typer.Option(None, "--input"),
        scope: str = "project",
        reset: str = "",
        project: Path = typer.Option(Path("."), "--project", "-p"),
    ):
        """Read settings with provenance or save/reset an explicit group."""

        def invoke():
            if input_file and reset:
                raise ValueError("Choose --input or --reset")
            with ResearchService(project) as service:
                current = service.workbench.preferences.load()
            if input_file or reset:
                arguments = {
                    "scope": scope,
                    "expected_revision": current[scope + "_revision"],
                }
                if reset:
                    arguments["group"] = reset
                else:
                    arguments["values"] = json.loads(
                        input_file.read_text(encoding="utf-8-sig")
                    )
                return perform(
                    project, "settings.reset" if reset else "settings.save", arguments
                )
            return perform(project, "settings", {})

        safe(invoke)

    @app.command("scope")
    def scope(
        analysis: str,
        selector: Path | None = typer.Option(None, "--selector"),
        project: Path = typer.Option(Path("."), "--project", "-p"),
    ):
        """Expand a block/project/selection to deduplicated logical targets."""

        def invoke():
            return perform(
                project,
                "scope",
                {
                    "analysis_id": analysis,
                    "selector": (
                        json.loads(selector.read_text(encoding="utf-8-sig"))
                        if selector
                        else {}
                    ),
                },
            )

        safe(invoke)

    @app.command("bind")
    def bind(
        input_file: Path = typer.Option(..., "--input"),
        project: Path = typer.Option(Path("."), "--project", "-p"),
    ):
        """Save a probe instance, including joint input roles and a structured selector."""
        safe(
            lambda: perform(
                project,
                "bind",
                {"instance": json.loads(input_file.read_text(encoding="utf-8-sig"))},
            )
        )

    @app.command("semantics")
    def semantics(
        logical_key: str = "",
        input_file: Path | None = typer.Option(None, "--input"),
        project: Path = typer.Option(Path("."), "--project", "-p"),
    ):
        """Inspect semantics or save {semantics,shape,expected_revision}."""

        def invoke():
            if input_file:
                return perform(
                    project,
                    "semantics.save",
                    json.loads(input_file.read_text(encoding="utf-8-sig")),
                )
            if not logical_key:
                raise ValueError("Provide a logical key or --input")
            return perform(project, "semantics", {"logical_key": logical_key})

        safe(invoke)

    @app.command("derived")
    def derived(
        key: str,
        proposal: bool = False,
        retain: bool = False,
        release: bool = False,
        project: Path = typer.Option(Path("."), "--project", "-p"),
    ):
        """Inspect provenance, retain/release inputs or generate an inert code proposal."""

        def invoke():
            if sum((proposal, retain, release)) > 1:
                raise ValueError("Choose one derived-data action")
            return perform(
                project,
                (
                    "derived.proposal"
                    if proposal
                    else "derived.retention" if retain or release else "derived"
                ),
                {"id": key, **({"retained": retain} if retain or release else {})},
            )

        safe(invoke)

    @app.command("expire")
    def expire(project: Path = typer.Option(Path("."), "--project", "-p")):
        """Remove expired unretained bulk artifacts, preserving definitions and history."""
        safe(perform, project, "storage.expire", {})
