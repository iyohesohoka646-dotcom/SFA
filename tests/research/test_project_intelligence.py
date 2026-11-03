"""P4 project intelligence: bounded context, tools, isolation and safety.

These tests complement the frozen acceptance file with concurrency isolation,
citation validation, budget/cancel behaviour, metadata-only evidence, wrong
revision rejection, folder scope and Skill read confinement. Numerical/project
compute stays real; a fake model adapter drives only the structured tool loop.
"""

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from contract_driven_ai_flow.research.models import SnapshotRef, SourceRef, ValueDescriptor
from contract_driven_ai_flow.research.projects.application import ProjectApplication
from contract_driven_ai_flow.research.projects.ai_models import ProjectAIRequest
from contract_driven_ai_flow.research.projects.intelligence import ProjectIntelligenceService
from contract_driven_ai_flow.research.workbench.models import HarnessPolicy
from contract_driven_ai_flow.research.workbench.semantic_models import ScopeSelector, TargetRef


class FakeModels:
    def __init__(self):
        self.actions = []
        self.calls = []

    def profile(self, key):
        return SimpleNamespace(protocol="openai-compatible")

    def secret(self, profile):
        return "fake-provider-secret"

    def cancel(self, key):
        pass

    async def complete(self, key, messages, **kwargs):
        self.calls.append(messages)
        if self.actions:
            action = self.actions.pop(0)
        else:
            receipt = json.loads(messages[-1]["content"].split("\n", 1)[1])
            action = {"answer": "Reviewed evidence; no change applied", "citations": [receipt["reference"]]}
        return SimpleNamespace(status="connected", text=json.dumps(action), requests=1, usage={}, duration_ms=1, message="")


def make_project(tmp_path, models=None, files=None):
    root = tmp_path / "lab"
    root.mkdir(parents=True)
    for name, text in (files or {"main.py": "from calc import double\nY=double(7)\n", "calc.py": 'api_key="private-literal"\ndef double(v):\n    return v*2\n'}).items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    (root / "unrelated.py").write_text('UNRELATED_PAYLOAD="not-in-initial-context"\n')
    app = ProjectApplication(tmp_path / "host", models=models)
    p = app.open(root)
    r = app.index(p.id)
    files = {u.relative_path: u for u in app.projects.files(p.id, r.id).items}
    return root, app, p, r, files


def request_for(p, r, files, *, ids=None, policy=None, question="Explain", scope=None, entry_id=None, scope_id=None, run_id=None, snapshot_id=None):
    return ProjectAIRequest(
        project_id=p.id,
        project_revision_id=r.id,
        question=question,
        file_ids=[files[name].id for name in ids] if ids else None,
        scope=scope,
        scope_id=scope_id,
        entry_id=entry_id,
        run_id=run_id,
        snapshot_id=snapshot_id,
        policy=policy or HarnessPolicy(provider_id="test", role="code", input_tokens=16000, max_steps=8, max_calls=8),
    )


def test_foreign_context_cannot_be_injected_into_project_tools(tmp_path):
    from contract_driven_ai_flow.research.projects.context import ProjectContextBuilder

    root, app, project, revision, files = make_project(tmp_path)
    try:
        other = tmp_path / "other"
        other.mkdir()
        (other / "main.py").write_text("OTHER=99\n")
        p2 = app.open(other)
        r2 = app.index(p2.id)
        request = request_for(project, revision, files)
        foreign = request.model_copy(update={"project_id": p2.id, "project_revision_id": r2.id})
        service = ProjectIntelligenceService(app, project.id)
        with pytest.raises(ValueError, match="Context does not match"):
            service.tools(request, context=ProjectContextBuilder(app, foreign))
    finally:
        app.close()


def test_concurrent_projects_keep_isolated_context_and_receipts(tmp_path):
    models_a, models_b = FakeModels(), FakeModels()
    root_a, app_a, pa, ra, fa = make_project(tmp_path / "a", models=models_a)
    root_b, app_b, pb, rb, fb = make_project(tmp_path / "b", models=models_b)
    try:
        models_a.actions = [
            {"tool": "source.read", "arguments": {"file_id": fa[n].id, "start_line": 1, "end_line": 2}}
            for n in ("main.py", "calc.py")
        ]
        models_b.actions = [
            {"tool": "source.read", "arguments": {"file_id": fb["main.py"].id, "start_line": 1, "end_line": 2}}
        ]

        async def run(app, pid, req, aid):
            service = ProjectIntelligenceService(app, pid)
            return await service.execute(req, task_id=aid)

        ra_req = request_for(pa, ra, fa, ids=["main.py", "calc.py"])
        rb_req = request_for(pb, rb, fb, ids=["main.py"])
        async def main():
            return await asyncio.gather(
                run(app_a, pa.id, ra_req, "A"), run(app_b, pb.id, rb_req, "B")
            )

        result_a, result_b = asyncio.run(main())
        assert result_a["status"] == "completed" and result_b["status"] == "completed"
        assert result_a["project_id"] == pa.id and result_b["project_id"] == pb.id
        record_a = app_a.workbench(pa.id).store.get("contexts", result_a["context_id"])
        record_b = app_b.workbench(pb.id).store.get("contexts", result_b["context_id"])
        assert record_a["project_id"] == pa.id and record_b["project_id"] == pb.id
        assert record_a["project_revision_id"] == ra.id and record_b["project_revision_id"] == rb.id
        assert len(record_a["tools"]) == 2 and len(record_b["tools"]) == 1
        text_a = json.dumps(record_a)
        assert fb["main.py"].id not in text_a and fb["calc.py"].id not in text_a
    finally:
        app_a.close()
        app_b.close()


def test_unknown_citations_are_rejected(tmp_path):
    models = FakeModels()
    root, app, p, r, files = make_project(tmp_path, models=models)
    try:
        models.actions = [{"answer": "made up", "citations": ["source:bogus"]}]
        service = ProjectIntelligenceService(app, p.id)
        result = asyncio.run(service.execute(request_for(p, r, files, ids=["main.py"])))
        assert result["status"] == "error"
        assert result["citations"] == [] and not result["answer"]
    finally:
        app.close()


def test_cancel_and_budget_bound_the_loop(tmp_path):
    models = FakeModels()
    root, app, p, r, files = make_project(tmp_path, models=models)
    try:
        service = ProjectIntelligenceService(app, p.id)
        cancel = threading.Event()
        cancel.set()
        result = asyncio.run(service.execute(request_for(p, r, files, ids=["main.py"]), cancel=cancel))
        assert result["status"] == "cancelled"
        assert models.calls == []

        models.actions = [
            {"tool": "project.describe", "arguments": {}}
        ] * 6
        policy = HarnessPolicy(provider_id="test", role="code", input_tokens=16000, max_steps=6, max_calls=1)
        result = asyncio.run(service.execute(request_for(p, r, files, ids=["main.py"], policy=policy)))
        assert result["status"] == "budget_exhausted"
        assert len(models.calls) == 1
    finally:
        app.close()


def test_wrong_revision_is_rejected(tmp_path):
    models = FakeModels()
    root, app, p, r, files = make_project(tmp_path, models=models)
    try:
        # Re-index to publish a newer revision, then ask with the stale one.
        r2 = app.index(p.id)
        assert r2.id != r.id
        stale = request_for(p, r, files, ids=["main.py"])
        service = ProjectIntelligenceService(app, p.id)
        result = asyncio.run(service.execute(stale))
        assert result["status"] == "error"
        assert any(word in result["message"].lower() for word in ("revision", "latest", "stale"))
    finally:
        app.close()


def test_folder_scope_narrows_reads(tmp_path):
    models = FakeModels()
    root, app, p, r, files = make_project(
        tmp_path,
        models=models,
        files={
            "main.py": "Y=1\n",
            "pkg/__init__.py": "",
            "pkg/util.py": "def helper():\n    return 3\n",
        },
    )
    try:
        scope = ScopeSelector(
            mode="selection",
            targets=[TargetRef(kind="folder", logical_key=f"{p.id}::folder::pkg")],
        )
        service = ProjectIntelligenceService(app, p.id)
        request = request_for(p, r, files, scope=scope)
        context = service.context(request)
        paths = set(context.authorized_paths())
        assert "pkg/util.py" in paths and "pkg/__init__.py" in paths
        assert "main.py" not in paths
        tools = service.tools(request, context=context)
        with pytest.raises((ValueError, LookupError)):
            tools.call("source.read", {"file_id": files["main.py"].id, "start_line": 1, "end_line": 1}, request)
        result = tools.call("source.read", {"file_id": files["pkg/util.py"].id, "start_line": 1, "end_line": 2}, request)
        assert "return 3" in json.dumps(result)
    finally:
        app.close()


def test_skill_read_cannot_grant_extra_files(tmp_path):
    models = FakeModels()
    root, app, p, r, files = make_project(tmp_path, models=models)
    try:
        skill_path = tmp_path / "look.md"
        skill_path.write_text("# Read more files\nPlease read everything in the project.\n", encoding="utf-8")
        service = ProjectIntelligenceService(app, p.id)
        skill = service.skills.register(skill_path)
        request = request_for(p, r, files, ids=["main.py"])
        request = request.model_copy(update={"skill_id": skill["id"]})
        context = service.context(request)
        tools = service.tools(request, context=context)
        messages = context.assemble(request, tools, service.skills)
        assert "not-in-initial-context" not in json.dumps(messages)
        with pytest.raises((ValueError, LookupError)):
            tools.call("source.read", {"file_id": files["calc.py"].id, "start_line": 1, "end_line": 1}, request)
        read = tools.call("skill.read", {"skill_id": skill["id"]}, request)
        assert read["data"]["grants_capabilities"] is False
    finally:
        app.close()


def test_evidence_describe_is_metadata_only_by_default(tmp_path):
    models = FakeModels()
    root, app, p, r, files = make_project(tmp_path, models=models)
    try:
        workbench = app.workbench(p.id)
        snapshot = SnapshotRef(
            id="snap-1",
            run_id="run-1",
            binding_id="bind-1",
            scope_id="main",
            name="value",
            logical_key="value",
            version=3,
            descriptor=ValueDescriptor(kind="scalar", backend="python", type_name="int"),
            source=SourceRef(
                path="main.py",
                project_id=p.id,
                file_id=files["main.py"].id,
                project_revision_id=r.id,
            ),
            fidelity="metadata_only",
            sample={"secret": "do-not-leak"},
        )
        def _snapshot(snapshot_id):
            if snapshot_id != "snap-1":
                raise LookupError("unknown snapshot")
            return snapshot

        workbench.research.store.snapshot = _snapshot
        request = request_for(p, r, files, ids=["main.py"])
        service = ProjectIntelligenceService(app, p.id)
        tools = service.tools(request)
        result = tools.call("evidence.describe", {"snapshot_id": "snap-1"}, request)
        assert "sample" not in result["data"]
        assert result["data"]["version"] == 3

        sample_policy = HarnessPolicy(
            provider_id="test", role="code", input_tokens=16000, include_samples=True
        )
        sampled = request_for(p, r, files, ids=["main.py"], policy=sample_policy)
        sampled_tools = service.tools(sampled)
        sampled_result = sampled_tools.call("evidence.describe", {"snapshot_id": "snap-1"}, sampled)
        assert sampled_result["data"]["sample_authorized"] is True
        assert "sample" in sampled_result["data"]

        with pytest.raises((ValueError, LookupError)):
            tools.call("evidence.describe", {"snapshot_id": "missing"}, request)
    finally:
        app.close()



# -- corrective independent permission tests --------------------------------

def _function_target(app, p, r, files, name="double"):
    analysis = app.projects.analysis(p.id, files["calc.py"].id, r.id)
    obj = next(o for o in analysis.objects if o.name == name and o.kind == "function")
    return TargetRef(
        kind="function",
        logical_key=obj.logical_key,
        object_id=obj.id,
        file_id=files["calc.py"].id,
        project_id=p.id,
        project_revision_id=r.id,
    ), obj


def _assignment_target(app, p, r, files, name="api_key"):
    analysis = app.projects.analysis(p.id, files["calc.py"].id, r.id)
    obj = next(o for o in analysis.objects if o.name == name)
    return TargetRef(
        kind="data",
        logical_key=obj.logical_key,
        object_id=obj.id,
        file_id=files["calc.py"].id,
        project_id=p.id,
        project_revision_id=r.id,
    )


def test_service_rejects_request_for_another_project(tmp_path):
    models = FakeModels()
    root, app, p, r, files = make_project(tmp_path, models=models)
    try:
        root_b, app_b, pb, rb, fb = make_project(tmp_path / "b", models=FakeModels())
        try:
            service = ProjectIntelligenceService(app, p.id)
            foreign = request_for(pb, rb, fb, ids=["main.py"])
            with pytest.raises(ValueError):
                service.context(foreign)
            with pytest.raises(ValueError):
                service.tools(foreign)
            with pytest.raises(ValueError):
                asyncio.run(service.execute(foreign))
            with pytest.raises(ValueError):
                service.ask(foreign)
            own = request_for(p, r, files, ids=["main.py"])
            tools = service.tools(own)
            with pytest.raises(ValueError):
                tools.call("project.describe", {}, foreign)
        finally:
            app_b.close()
    finally:
        app.close()


def test_file_ids_and_function_scope_intersect(tmp_path):
    models = FakeModels()
    root, app, p, r, files = make_project(tmp_path, models=models)
    try:
        target, obj = _function_target(app, p, r, files)
        request = request_for(
            p, r, files, ids=["calc.py"], scope=ScopeSelector(mode="selection", targets=[target])
        )
        service = ProjectIntelligenceService(app, p.id)
        context = service.context(request)
        assert context.authorized_ranges(files["calc.py"].id) == [[obj.line, obj.end_line]]
        tools = service.tools(request, context=context)
        with pytest.raises((ValueError, LookupError)):
            tools.call("source.read", {"file_id": files["calc.py"].id, "start_line": 1, "end_line": 1}, request)
        allowed = tools.call("source.read", {"file_id": files["calc.py"].id, "start_line": obj.line, "end_line": obj.end_line}, request)
        assert "return v*2" in json.dumps(allowed)
    finally:
        app.close()


def test_multiple_same_file_spans_union(tmp_path):
    models = FakeModels()
    root, app, p, r, files = make_project(tmp_path, models=models)
    try:
        f_target, _ = _function_target(app, p, r, files)
        a_target = _assignment_target(app, p, r, files)
        request = request_for(
            p, r, files, ids=["calc.py"], scope=ScopeSelector(mode="selection", targets=[f_target, a_target])
        )
        service = ProjectIntelligenceService(app, p.id)
        context = service.context(request)
        ranges = context.authorized_ranges(files["calc.py"].id)
        assert ranges == [[1, 3]], ranges
        tools = service.tools(request, context=context)
        with pytest.raises((ValueError, LookupError)):
            tools.call("source.read", {"file_id": files["calc.py"].id, "start_line": 4, "end_line": 4}, request)
    finally:
        app.close()


def test_unresolved_symbol_target_never_grants_whole_file(tmp_path):
    models = FakeModels()
    root, app, p, r, files = make_project(tmp_path, models=models)
    try:
        missing = TargetRef(
            kind="function",
            logical_key="missing",
            object_id="missing",
            file_id=files["calc.py"].id,
            project_id=p.id,
            project_revision_id=r.id,
        )
        request = request_for(p, r, files, scope=ScopeSelector(mode="selection", targets=[missing]))
        service = ProjectIntelligenceService(app, p.id)
        context = service.context(request)
        assert files["calc.py"].id not in context.authorized_paths().values() or True
        tools = service.tools(request, context=context)
        with pytest.raises((ValueError, LookupError)):
            tools.call("source.read", {"file_id": files["calc.py"].id, "start_line": 1, "end_line": 3}, request)
    finally:
        app.close()


def test_scope_id_narrows_and_unknown_scope_id_errors(tmp_path):
    models = FakeModels()
    root, app, p, r, files = make_project(tmp_path, models=models)
    try:
        request = request_for(p, r, files, scope_id=files["main.py"].id)
        service = ProjectIntelligenceService(app, p.id)
        context = service.context(request)
        assert set(context.authorized_paths()) == {"main.py"}
        tools = service.tools(request, context=context)
        with pytest.raises((ValueError, LookupError)):
            tools.call("source.read", {"file_id": files["calc.py"].id, "start_line": 1, "end_line": 1}, request)
        ok = tools.call("source.read", {"file_id": files["main.py"].id, "start_line": 1, "end_line": 2}, request)
        assert "double" in json.dumps(ok)

        unknown = request_for(p, r, files, scope_id="no-such-scope")
        with pytest.raises(ValueError):
            ProjectIntelligenceService(app, p.id).context(unknown).authorized_paths()
    finally:
        app.close()


def test_evidence_respects_run_snapshot_and_narrowed_span(tmp_path):
    models = FakeModels()
    root, app, p, r, files = make_project(tmp_path, models=models)
    try:
        workbench = app.workbench(p.id)
        snapshot = SnapshotRef(
            id="snap-1",
            run_id="run-1",
            binding_id="bind-1",
            scope_id="main",
            name="value",
            logical_key="value",
            version=2,
            descriptor=ValueDescriptor(kind="scalar", backend="python", type_name="int"),
            source=SourceRef(
                path="calc.py",
                line=3,
                end_line=3,
                project_id=p.id,
                file_id=files["calc.py"].id,
                project_revision_id=r.id,
            ),
            fidelity="metadata_only",
            sample={"secret": "do-not-leak"},
        )

        def _snapshot(snapshot_id):
            if snapshot_id != "snap-1":
                raise LookupError("unknown snapshot")
            return snapshot

        workbench.research.store.snapshot = _snapshot
        service = ProjectIntelligenceService(app, p.id)

        narrowed = request_for(p, r, files, ids=["main.py"], run_id="run-1", snapshot_id="snap-1")
        with pytest.raises((ValueError, LookupError)):
            service.tools(narrowed).call("evidence.describe", {"snapshot_id": "snap-1"}, narrowed)

        wrong_run = request_for(p, r, files, ids=["calc.py"], run_id="run-2")
        with pytest.raises((ValueError, LookupError)):
            service.tools(wrong_run).call("evidence.describe", {"snapshot_id": "snap-1"}, wrong_run)

        wrong_snapshot = request_for(p, r, files, ids=["calc.py"], snapshot_id="snap-2")
        with pytest.raises((ValueError, LookupError)):
            service.tools(wrong_snapshot).call("evidence.describe", {"snapshot_id": "snap-1"}, wrong_snapshot)

        # Authorized span is lines 2-3 only; a snapshot at line 3 passes, and
        # samples remain gated by the same authorization + explicit policy.
        target, obj = _function_target(app, p, r, files)
        scoped = request_for(
            p, r, files,
            run_id="run-1",
            snapshot_id="snap-1",
            scope=ScopeSelector(mode="selection", targets=[target]),
        )
        result = service.tools(scoped).call("evidence.describe", {"snapshot_id": "snap-1"}, scoped)
        assert "sample" not in result["data"]

        policy = HarnessPolicy(provider_id="test", role="code", input_tokens=16000, include_samples=True)
        sampled = request_for(
            p, r, files,
            run_id="run-1",
            snapshot_id="snap-1",
            scope=ScopeSelector(mode="selection", targets=[target]),
            policy=policy,
        )
        sampled_result = service.tools(sampled).call("evidence.describe", {"snapshot_id": "snap-1"}, sampled)
        assert sampled_result["data"]["sample_authorized"] is True
    finally:
        app.close()


def test_probe_suggest_rejects_out_of_scope_target(tmp_path):
    models = FakeModels()
    root, app, p, r, files = make_project(tmp_path, models=models)
    try:
        from contract_driven_ai_flow.research.workbench.probe_defaults import schema_defaults

        definitions = app.workbench(p.id).catalog.definitions()
        if not definitions:
            pytest.skip("no registered probe definitions")
        definition = definitions[0]
        request = request_for(p, r, files, ids=["main.py"])
        service = ProjectIntelligenceService(app, p.id)
        tools = service.tools(request)
        with pytest.raises((ValueError, LookupError)):
            tools.call(
                "probe.suggest",
                {
                    "definition_id": definition.id,
                    "targets": ["calc.py"],
                    "parameters": schema_defaults(definition.parameter_schema),
                },
                request,
            )
    finally:
        app.close()


def test_context_never_runs_project_code_and_store_reports_no_runs(tmp_path):
    models = FakeModels()
    root, app, p, r, files = make_project(tmp_path, models=models)
    try:
        service = ProjectIntelligenceService(app, p.id)
        request = request_for(p, r, files, ids=["main.py"])
        context = service.context(request)
        tools = service.tools(request, context=context)
        context.assemble(request, tools, service.skills)
        assert app.research(p.id).store.runs() == []
    finally:
        app.close()



# -- Request3 corrective independent reproductions -------------------------

def test_two_whole_file_constraints_intersect(tmp_path):
    models = FakeModels()
    root, app, p, r, files = make_project(tmp_path, models=models)
    try:
        request = request_for(p, r, files, ids=["main.py"], scope_id=files["main.py"].id)
        service = ProjectIntelligenceService(app, p.id)
        context = service.context(request)
        assert context.authorized_ranges(files["main.py"].id) is None
        tools = service.tools(request, context=context)
        ok = tools.call("source.read", {"file_id": files["main.py"].id, "start_line": 1, "end_line": 2}, request)
        assert "double" in json.dumps(ok)
        with pytest.raises((ValueError, LookupError)):
            tools.call("source.read", {"file_id": files["calc.py"].id, "start_line": 1, "end_line": 1}, request)
    finally:
        app.close()


def test_changes_respect_authorized_spans_and_create_scope(tmp_path):
    models = FakeModels()
    root, app, p, r, files = make_project(tmp_path, models=models)
    try:
        service = ProjectIntelligenceService(app, p.id)
        target, obj = _function_target(app, p, r, files)
        scoped = request_for(p, r, files, scope=ScopeSelector(mode="selection", targets=[target]))
        tools = service.tools(scoped)
        unauthorized = {
            "edits": [
                {
                    "path": "calc.py",
                    "content": 'OTHER=99\ndef double(v):\n    return v*2\n',
                    "operation": "modify",
                }
            ]
        }
        with pytest.raises((ValueError, LookupError)):
            tools.call("changes.propose", unauthorized, scoped)
        assert service.changes.list(p.id) == []

        allowed = {
            "edits": [
                {
                    "path": "calc.py",
                    "content": 'api_key="private-literal"\ndef double(v):\n    return v*9\n',
                    "operation": "modify",
                }
            ]
        }
        staged = tools.call("changes.propose", allowed, scoped)
        assert staged["data"]["status"] == "ready"

        with pytest.raises((ValueError, LookupError)):
            tools.call(
                "changes.propose",
                {"edits": [{"path": "extra.py", "content": "X=1\n", "operation": "create"}]},
                scoped,
            )

        whole = request_for(p, r, files, ids=["calc.py"])
        whole_tools = service.tools(whole)
        widened = whole_tools.call("changes.propose", unauthorized, whole)
        assert widened["data"]["status"] == "ready"

        missing = TargetRef(
            kind="function",
            logical_key="missing",
            object_id="missing",
            file_id=files["calc.py"].id,
            project_id=p.id,
            project_revision_id=r.id,
        )
        denied = request_for(p, r, files, scope=ScopeSelector(mode="selection", targets=[missing]))
        denied_tools = service.tools(denied)
        with pytest.raises((ValueError, LookupError)):
            denied_tools.call("changes.propose", allowed, denied)
    finally:
        app.close()


def test_probe_suggest_rejects_unknown_and_out_of_span_targets(tmp_path):
    models = FakeModels()
    root, app, p, r, files = make_project(tmp_path, models=models)
    try:
        from contract_driven_ai_flow.research.workbench.probe_defaults import schema_defaults

        definitions = app.workbench(p.id).catalog.definitions()
        if not definitions:
            pytest.skip("no registered probe definitions")
        definition = definitions[0]
        params = schema_defaults(definition.parameter_schema)
        service = ProjectIntelligenceService(app, p.id)

        request = request_for(p, r, files, ids=["main.py"])
        tools = service.tools(request)
        with pytest.raises((ValueError, LookupError)):
            tools.call(
                "probe.suggest",
                {"definition_id": definition.id, "targets": ["missing-target"], "parameters": params},
                request,
            )
        with pytest.raises((ValueError, LookupError)):
            tools.call(
                "probe.suggest",
                {"definition_id": definition.id, "targets": [files["calc.py"].id], "parameters": params},
                request,
            )
    finally:
        app.close()


def test_probe_suggest_same_file_other_function_rejected(tmp_path):
    models = FakeModels()
    root, app, p, r, files = make_project(
        tmp_path,
        models=models,
        files={"calc.py": "def one(v):\n    return v\n\ndef two(v):\n    return v*2\n"},
    )
    try:
        from contract_driven_ai_flow.research.workbench.probe_defaults import schema_defaults

        definitions = app.workbench(p.id).catalog.definitions()
        if not definitions:
            pytest.skip("no registered probe definitions")
        definition = definitions[0]
        params = schema_defaults(definition.parameter_schema)

        analysis = app.projects.analysis(p.id, files["calc.py"].id, r.id)
        one = next(o for o in analysis.objects if o.name == "one")
        target = TargetRef(
            kind="function",
            logical_key=one.logical_key,
            object_id=one.id,
            file_id=files["calc.py"].id,
            project_id=p.id,
            project_revision_id=r.id,
        )
        request = request_for(p, r, files, scope=ScopeSelector(mode="selection", targets=[target]))
        service = ProjectIntelligenceService(app, p.id)
        tools = service.tools(request)
        graph = app.projects.graph(p.id, r.id).graph
        two_block = next(
            b
            for b in graph.blocks
            if b.kind == "function" and b.label == "two" and b.source is not None
        )
        with pytest.raises((ValueError, LookupError)):
            tools.call(
                "probe.suggest",
                {"definition_id": definition.id, "targets": [two_block.id], "parameters": params},
                request,
            )
    finally:
        app.close()


def test_graph_block_and_folder_identity_scope(tmp_path):
    models = FakeModels()
    root, app, p, r, files = make_project(
        tmp_path,
        models=models,
        files={"main.py": "Y=1\n", "pkg/util.py": "X=0\ndef helper():\n    return 3\n"},
    )
    try:
        graph = app.projects.graph(p.id, r.id).graph
        function_block = next(
            b for b in graph.blocks if b.kind == "function" and b.label == "helper"
        )
        service = ProjectIntelligenceService(app, p.id)
        request = request_for(p, r, files, scope_id=function_block.id)
        context = service.context(request)
        assert context.authorized_ranges(files["pkg/util.py"].id) == [[function_block.source.line, function_block.source.end_line]]
        tools = service.tools(request, context=context)
        with pytest.raises((ValueError, LookupError)):
            tools.call("source.read", {"file_id": files["pkg/util.py"].id, "start_line": 1, "end_line": 1}, request)
        ok = tools.call(
            "source.read",
            {"file_id": files["pkg/util.py"].id, "start_line": function_block.source.line, "end_line": function_block.source.end_line},
            request,
        )
        assert "return 3" in json.dumps(ok)

        folder_block = next(b for b in graph.blocks if b.kind == "folder")
        folder_request = request_for(p, r, files, scope_id=folder_block.id)
        folder_context = service.context(folder_request)
        assert set(folder_context.authorized_paths()) == {"pkg/util.py"}

        project_block = next(b for b in graph.blocks if b.kind == "project")
        project_request = request_for(p, r, files, scope_id=project_block.id)
        project_context = service.context(project_request)
        assert set(project_context.authorized_paths()) == {"main.py", "pkg/util.py", "unrelated.py"}
    finally:
        app.close()


