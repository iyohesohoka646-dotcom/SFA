import asyncio
import json
import sys
from pathlib import Path
import yaml
from typer.testing import CliRunner
from contract_driven_ai_flow.cli import app
from contract_driven_ai_flow.research.service import ResearchService
from contract_driven_ai_flow.research.workbench.models import ProbeInstance
from contract_driven_ai_flow.research.workbench.semantic_models import ScopeSelector


def manifest():
    return {
        "id": "lab",
        "label": "Laboratory checks",
        "version": "1",
        "definitions": [
            {
                "id": "lab.check",
                "label": "Threshold",
                "capability": "check",
                "execution": "program",
                "entrypoint": "lab_probe:evaluate",
                "evidence": "metadata",
                "parameter_schema": {
                    "type": "object",
                    "properties": {"minimum": {"type": "number"}},
                    "additionalProperties": False,
                },
            }
        ],
    }


def test_cli_settings_resources_and_scoped_plan_use_shared_services(tmp_path):
    cli = CliRunner()
    result = cli.invoke(
        app, ["--json", "workbench", "settings", "--project", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["sources"]["graph.dim_unrelated"] == "default"
    resource = tmp_path / "resource.json"
    resource.write_text(json.dumps(manifest()))
    result = cli.invoke(
        app,
        [
            "--json",
            "workbench",
            "resources",
            "--import",
            str(resource),
            "--project",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["status"] == "draft"


def test_v2_migration_preserves_deleted_default_and_reports_ambiguous_binding(tmp_path):
    script = tmp_path / "analysis.py"
    script.write_text("def a():\n x=1\ndef b():\n x=2\n")
    original = yaml.safe_dump(
        {
            "protocol_version": 2,
            "revision": 4,
            "script": str(script),
            "probes": [
                {"id": "old-check", "definition_id": "check.finite", "binding": "x"}
            ],
        }
    )
    path = tmp_path / "workbench.yaml"
    path.write_text(original)
    with ResearchService(tmp_path) as research:
        result = research.workbench.configurations.migrate_v2(apply=True)
        assert result["applied"] and result["pending_rebind"] == ["old-check"]
        config = research.workbench.configurations.load()
        assert config.protocol_version == 3 and all(
            p.id != "auto-view" for p in config.probes
        )
        assert not config.probes[0].enabled
        assert path.with_name("workbench.yaml.v2.bak").read_text() == original


def test_resource_update_retains_active_version_until_review_and_across_restart(
    tmp_path,
):
    (tmp_path / "lab_probe.py").write_text(
        "def evaluate(context,parameters):return {'status':'pass'}\n"
    )
    with ResearchService(tmp_path) as research:
        manager = research.workbench.resources
        manager.import_manifest(manifest())
        manager.enable("lab")
        newer = {**manifest(), "version": "2"}
        manager.import_manifest(newer)
        assert research.workbench.catalog.resolve("lab.check").resource_version == "1"
    with ResearchService(tmp_path) as research:
        assert research.workbench.catalog.resolve("lab.check").resource_version == "1"
        research.workbench.resources.enable("lab")
        assert research.workbench.catalog.resolve("lab.check").resource_version == "2"


def test_custom_program_probe_runs_in_owned_worker_and_keeps_error_result(tmp_path):
    script = tmp_path / "analysis.py"
    script.write_text("X=5\n")
    (tmp_path / "lab_probe.py").write_text(
        'def evaluate(context, parameters):\n return {"status":"pass" if len(context["snapshots"]) >= parameters["minimum"] else "fail", "message":"threshold checked"}\n'
    )
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        analysis = wb.import_source(script)
        wb.resources.import_manifest(manifest())
        wb.resources.enable("lab")
        cfg = wb.configurations.load()
        cfg.script = str(script)
        cfg.probes = [
            ProbeInstance(
                definition_id="lab.check", binding="X", parameters={"minimum": 1}
            )
        ]
        wb.configure(cfg, expected_revision=cfg.revision)
        task = wb.jobs.wait(wb.execute(wb.plan(analysis.id).id).id, 15)
        outputs = wb.outputs(run_id=task.run_id)
        assert task.status == "completed" and outputs[0]["status"] == "pass", outputs
        assert outputs[0]["data"]["program_digest"]


def test_large_harness_manifest_stays_within_default_budget(tmp_path):
    from contract_driven_ai_flow.research.workbench.intelligence.harness import (
        HarnessRequest,
    )
    from contract_driven_ai_flow.research.workbench.intelligence.context import (
        token_bound,
    )

    script = tmp_path / "analysis.py"
    script.write_text("\n".join(f"x{i}={i}" for i in range(1000)))
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        analysis = wb.import_source(script)
        harness = wb.harness
        request = HarnessRequest(
            question="Inspect the environment", analysis_id=analysis.id
        )
        context = harness.context.assemble(request, harness.tools, harness.skills)
        assert token_bound(context) < request.policy.input_tokens
        page = harness.tools.call(
            "analysis.list", {"offset": 980, "limit": 20}, request
        )
        assert len(page["result"]["objects"]) == 20 and page["result"]["total"] == 1000


def test_function_timing_probe_uses_real_invocation_summary(tmp_path):
    script = tmp_path / "analysis.py"
    script.write_text("def square(x):\n return x*x\nA=square(3)\nB=square(4)\n")
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        analysis = wb.import_source(script)
        cfg = wb.configurations.load()
        cfg.script = str(script)
        cfg.probes = [
            ProbeInstance(
                definition_id="check.timing",
                binding="square",
                parameters={"maximum_ms": 1000},
            )
        ]
        wb.configure(cfg, expected_revision=cfg.revision)
        task = wb.jobs.wait(wb.execute(wb.plan(analysis.id).id).id, 15)
        output = wb.outputs(task_id=task.id)[0]
        assert output["status"] == "pass", output
        assert output["data"]["calls"] == 2 and output["data"]["total_ms"] > 0
        assert output["data"]["timing"] == "scope-including-observation"


def test_program_source_change_invalidates_frozen_implementation(tmp_path):
    script = tmp_path / "analysis.py"
    script.write_text("X=5\n")
    program = tmp_path / "lab_probe.py"
    program.write_text(
        'def evaluate(context, parameters):\n return {"status":"pass"}\n'
    )
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        analysis = wb.import_source(script)
        wb.resources.import_manifest(manifest())
        wb.resources.enable("lab")
        cfg = wb.configurations.load()
        cfg.script = str(script)
        cfg.probes = [ProbeInstance(definition_id="lab.check", binding="X")]
        wb.configure(cfg, expected_revision=cfg.revision)
        plan = wb.plan(analysis.id)
        program.write_text(
            'def evaluate(context, parameters):\n return {"status":"fail"}\n'
        )
        task = wb.jobs.wait(wb.execute(plan.id).id, 15)
        output = wb.outputs(task_id=task.id)[0]
        assert output["status"] == "error" and "changed" in output["message"]


def test_legacy_plan_requires_replanning_instead_of_empty_success(tmp_path):
    script = tmp_path / "analysis.py"
    script.write_text("X=5\n")
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        analysis = wb.import_source(script)
        plan = wb.plan(analysis.id)
        old = plan.model_dump(mode="json")
        old["protocol_version"] = 2
        old.pop("invocations")
        wb.store.put("plans", plan.id, old)
        import pytest

        with pytest.raises(ValueError, match="plan"):
            wb.execute(plan.id)


def test_plan_freezes_preferences_and_batch_concurrency_is_bounded(
    tmp_path, monkeypatch
):
    import threading, time
    from contract_driven_ai_flow.research.workbench.models import ProbeOutput

    script = tmp_path / "analysis.py"
    script.write_text("A=1\nB=2\nC=3\nD=4\n")
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        analysis = wb.import_source(script)
        current = wb.preferences.load()
        wb.preferences.save(
            "project",
            {"probes": {"concurrency": 2}},
            expected_revision=current["project_revision"],
        )
        plan = wb.plan(analysis.id)
        assert plan.preferences["probes"]["concurrency"] == 2
        current = wb.preferences.load()
        wb.preferences.save(
            "project",
            {"probes": {"concurrency": 1}},
            expected_revision=current["project_revision"],
        )
        lock = threading.Lock()
        active = 0
        maximum = 0

        def evaluate(call, run, plan, task, cancel):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.04)
            with lock:
                active -= 1
            return ProbeOutput(
                instance_id=call.instance.id,
                definition_id=call.definition.id,
                capability=call.definition.capability,
                execution=call.definition.execution,
                status="ready",
                run_id=run,
            )

        monkeypatch.setattr(wb, "_evaluate_call", evaluate)
        task = wb.jobs.wait(wb.execute(plan.id).id, 15)
        assert task.status == "completed" and maximum == 2


def test_model_resource_proposal_is_inert_and_requires_explicit_enable(tmp_path):
    from contract_driven_ai_flow.research.workbench.intelligence.harness import (
        HarnessRequest,
    )

    script = tmp_path / "analysis.py"
    script.write_text("X=1\n")
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        analysis = wb.import_source(script)
        request = HarnessRequest(
            analysis_id=analysis.id,
            question="Draft an adapter",
            policy={"role": "parse"},
        )
        result = wb.harness.tools.call(
            "resource.propose", {"manifest": json.dumps(manifest())}, request
        )
        assert result["result"]["status"] == "draft"
        import pytest

        with pytest.raises(ValueError, match="registered"):
            wb.catalog.resolve("lab.check")


def test_historical_graph_uses_run_source_version_even_after_source_edit(tmp_path):
    script = tmp_path / "analysis.py"
    script.write_text("X=1\nY=X+1\n")
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        old = wb.import_source(script)
        task = wb.jobs.wait(wb.execute(wb.plan(old.id).id).id, 15)
        script.write_text("NEW=100\n")
        current = wb.import_source(script)
        historical = wb.run_analysis(task.run_id)
        assert historical.source_digest == old.source_digest != current.source_digest
        assert {obj.name for obj in historical.objects} == {"X", "Y"}


def test_v2_analysis_recovers_archived_graph_and_keeps_existing_identities(tmp_path):
    script = tmp_path / "analysis.py"
    script.write_text("def double(x):\n return x * 2\nX=1\nY=double(X)\n")
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        analysis = wb.import_source(script)
        legacy = analysis.model_dump(mode="json")
        legacy["protocol_version"] = 2
        legacy.pop("graph")
        identities = {}
        for i, obj in enumerate(legacy["objects"]):
            identities[obj["id"]] = obj["id"] = f"legacy-object-{i}"
            for key in ("column", "end_column", "logical_key", "block_id"):
                obj.pop(key)
        for edge in legacy["relations"]:
            edge["source"] = identities[edge["source"]]
            edge["target"] = identities[edge["target"]]
        wb.store.put("analyses", analysis.id, legacy)
        run = research.store.create_run(
            str(script), interpreter=sys.executable, source_digest=analysis.source_digest
        )
        script.write_text("NEW=100\n")
        historical = wb.run_analysis(run["id"])
        assert historical.protocol_version == 3
        assert historical.id == analysis.id
        assert historical.imported_at == analysis.imported_at
        assert {obj.id for obj in historical.objects} == set(identities.values())
        assert historical.graph.blocks and historical.graph.nodes
        assert all(obj.block_id and obj.logical_key for obj in historical.objects)
        assert all(
            node.source_object_id in identities.values()
            for node in historical.graph.nodes if node.source_object_id
        )
        assert {obj.name for obj in historical.objects} == {"double", "x", "X", "Y"}
        assert wb.analysis(analysis.id).model_dump() == historical.model_dump()
        assert wb.store.get("analysis_backups", analysis.id) == legacy


def test_custom_probe_templates_use_the_live_resource_catalog(tmp_path):
    import pytest
    from jsonschema import ValidationError

    with ResearchService(tmp_path) as research:
        wb = research.workbench
        custom = manifest()
        definition = custom["definitions"][0]
        definition.update(id="lab.view", capability="view", execution="builtin", renderer="matrix")
        definition.pop("entrypoint")
        wb.resources.import_manifest(custom)
        wb.resources.enable("lab")
        template = wb.semantics.save_template("lab-default", "实验室视图", "lab.view", {"minimum": 2})
        assert template in wb.semantics.templates()
        with pytest.raises(ValidationError):
            wb.semantics.save_template("invalid", "无效模板", "lab.view", {"minimum": "invalid"})
        wb.resources.disable("lab")
        with pytest.raises(ValueError, match="registered"):
            wb.semantics.save_template("disabled", "禁用资源", "lab.view", {})


def test_output_filters_are_applied_before_the_global_page_limit(tmp_path):
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        old = {"id": "old-result", "run_id": "old-run", "snapshot_id": "old-snapshot"}
        wb.store.put("outputs", old["id"], old)
        with wb.store.connect() as db:
            db.executemany(
                "INSERT INTO records(kind,id,payload) VALUES('outputs',?,?)",
                [(f"new-{i}", json.dumps({"id": f"new-{i}", "run_id": "new-run", "snapshot_id": "new-snapshot"})) for i in range(1000)],
            )
        assert wb.outputs(run_id="old-run") == [old]
        assert wb.outputs(snapshot_id="old-snapshot") == [old]
        assert wb.outputs(run_id="old-run", snapshot_id="new-snapshot") == []
        assert len(wb.outputs(run_id="new-run")) == 1000


def test_output_history_can_continue_with_a_stable_cursor(tmp_path):
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        with wb.store.connect() as db:
            db.executemany(
                "INSERT INTO records(kind,id,payload) VALUES('outputs',?,?)",
                [(f"result-{i}", json.dumps({"id": f"result-{i}", "run_id": "run", "snapshot_id": "snapshot"})) for i in range(1002)],
            )
        first = wb.outputs(run_id="run")
        second = wb.outputs(run_id="run", before=first[-1]["id"])
        assert len(first) == 1000 and len(second) == 2
        assert len({output["id"] for output in [*first, *second]}) == 1002
        assert wb.outputs(snapshot_id="snapshot", before=second[-1]["id"]) == []


def test_selected_existing_evidence_retargets_logical_object_in_new_compute_run(
    tmp_path,
):
    from contract_driven_ai_flow.research.workbench.bindings import snapshot_target

    script = tmp_path / "analysis.py"
    script.write_text("X=5\n")
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        analysis = wb.import_source(script)
        first = wb.jobs.wait(wb.execute(wb.plan(analysis.id).id).id, 15)
        old = research.store.snapshots(first.run_id)[0]
        selector = ScopeSelector(
            mode="selection", targets=[snapshot_target(old, analysis)]
        )
        second = wb.jobs.wait(
            wb.execute(wb.plan(analysis.id, target_scope=selector).id).id, 15
        )
        outputs = wb.outputs(task_id=second.id)
        assert second.run_id != first.run_id and outputs
        assert all(
            o["run_id"] == second.run_id and o["snapshot_id"] != old.id for o in outputs
        )


def test_unimported_historical_crlf_source_preserves_exact_archive_digest(tmp_path):
    script = tmp_path / "analysis.py"
    script.write_bytes(b"X=1\r\nY=X+1\r\n")
    with ResearchService(tmp_path) as research:
        run = research.start_analysis(script)
        research.wait(run.run_id, 15)
        script.write_text("NEW=100\n")
        historical = research.workbench.run_analysis(run.run_id)
        assert historical.source_digest == run.source_digest
        assert {o.name for o in historical.objects} == {"X", "Y"}


def test_v1_migration_resolves_current_selectors_and_retains_router_for_rebinding(
    tmp_path,
):
    script = tmp_path / "analysis.py"
    script.write_text("X=1\n")
    raw = yaml.safe_dump(
        {
            "script": str(script),
            "probes": [
                {"id": "all", "kind": "finite", "binding": "*"},
                {"id": "one", "kind": "finite", "binding": "X"},
                {"id": "router", "kind": "router", "binding": "X"},
            ],
        }
    ).encode()
    (tmp_path / "research.yaml").write_bytes(raw)
    with ResearchService(tmp_path) as research:
        result = research.workbench.configurations.migrate_legacy(apply=True)
        config = result["config"]
        assert config["protocol_version"] == 3
        assert config["probes"][0]["selector"]["mode"] == "project"
        assert config["probes"][1]["selector"]["targets"][0]["logical_key"].endswith(
            "::<module>::X"
        )
        assert not config["probes"][2]["enabled"]
        assert result["pending_rebind"] == ["router"]
        assert (tmp_path / "research.yaml.v1.bak").read_bytes() == raw


def test_large_source_projection_uses_cached_utf8_spans_not_full_text_resplits(
    tmp_path, monkeypatch
):
    import ast

    script = tmp_path / "analysis.py"
    script.write_text(
        "".join(f"对象{i} = {i}\n" for i in range(1000)), encoding="utf-8"
    )

    def expensive(*args, **kwargs):
        raise AssertionError("Each node must use cached line spans")

    monkeypatch.setattr(ast, "get_source_segment", expensive)
    from contract_driven_ai_flow.research.workbench.analysis import analyze_source

    analysis = analyze_source(script)
    assert len(analysis.objects) == 1000
    assert analysis.objects[-1].code == "对象999 = 999"


def test_new_configuration_inherits_preferences_but_authored_parameters_keep_precedence(
    tmp_path,
):
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        prefs = wb.preferences.load()
        wb.preferences.save(
            "project",
            {
                "capture": {"level": "sample"},
                "probes": {"precision": 7},
                "intelligence": {"input_tokens": 2048},
            },
            expected_revision=prefs["project_revision"],
        )
        config = wb.configurations.load()
        assert config.capture == "sample"
        assert config.probes[0].parameters["precision"] == 7
        assert all(h.input_tokens == 2048 for h in config.harness)
        config.capture = "metadata"
        wb.configure(config, expected_revision=config.revision)
        prefs = wb.preferences.load()
        wb.preferences.save(
            "project",
            {"capture": {"level": "full"}},
            expected_revision=prefs["project_revision"],
        )
        assert wb.configurations.load().capture == "metadata"


def test_program_review_executes_hashed_source_even_with_stale_bytecode(tmp_path):
    import py_compile, os

    probe = tmp_path / "lab_probe.py"
    old = "def evaluate(context,parameters): return {'status':'fail'}\n"
    new = "def evaluate(context,parameters): return {'status':'pass'}\n"
    probe.write_text(old)
    stamp = probe.stat().st_mtime
    py_compile.compile(str(probe), doraise=True)
    probe.write_text(new)
    os.utime(probe, (stamp, stamp))
    script = tmp_path / "analysis.py"
    script.write_text("X=1\n")
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        wb.resources.import_manifest(manifest())
        wb.resources.enable("lab")
        config = wb.configurations.load()
        config.script = str(script)
        config.probes = [
            ProbeInstance(id="lab", definition_id="lab.check", budget_ms=5000)
        ]
        wb.configure(config, expected_revision=config.revision)
        task = wb.jobs.wait(wb.execute(wb.plan(wb.import_source(script).id).id).id, 15)
        assert wb.outputs(task_id=task.id)[0]["status"] == "pass"


def test_resource_enable_rejects_missing_program_and_a_replaced_review(tmp_path):
    import pytest

    with ResearchService(tmp_path) as research:
        manager = research.workbench.resources
        manager.import_manifest(manifest())
        with pytest.raises(ValueError, match="entry|Program"):
            manager.enable("lab")
        (tmp_path / "lab_probe.py").write_text(
            "def evaluate(context,parameters):return {'status':'pass'}\n"
        )
        manager.import_manifest(manifest())
        reviewed = next(r for r in manager.resources() if r["id"] == "lab")[
            "review_digest"
        ]
        manager.import_manifest({**manifest(), "version": "2"})
        with pytest.raises(ValueError, match="review|changed"):
            manager.enable("lab", expected_digest=reviewed)


def test_resource_enable_checks_review_again_after_slow_introspection(
    tmp_path, monkeypatch
):
    import pytest
    from contract_driven_ai_flow.research.workbench import resources

    (tmp_path / "lab_probe.py").write_text(
        "def evaluate(context,parameters):return {'status':'pass'}\n"
    )
    with ResearchService(tmp_path) as research:
        manager = research.workbench.resources
        manager.import_manifest(manifest())
        reviewed = next(r for r in manager.resources() if r["id"] == "lab")[
            "review_digest"
        ]
        original = resources.run_process

        def change_during_validation(*args, **kwargs):
            receipt = original(*args, **kwargs)
            manager.import_manifest({**manifest(), "version": "2"})
            return receipt

        monkeypatch.setattr(resources, "run_process", change_during_validation)
        with pytest.raises(ValueError, match="changed|review"):
            manager.enable("lab", expected_digest=reviewed)
        assert (
            next(r for r in manager.resources() if r["id"] == "lab")["version"] == "2"
        )


def test_resource_enable_checks_declared_dependencies_in_project_interpreter(tmp_path):
    import pytest

    (tmp_path / "lab_probe.py").write_text(
        "def evaluate(context,parameters):return {'status':'pass'}\n"
    )
    with ResearchService(tmp_path) as research:
        manager = research.workbench.resources
        manager.import_manifest(
            {**manifest(), "dependencies": ["cdaf-nonexistent-validation-package>=1"]}
        )
        with pytest.raises(ValueError, match="dependenc|Dependency|Program"):
            manager.enable("lab")
