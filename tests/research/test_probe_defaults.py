from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from contract_driven_ai_flow.research.workbench.catalog import ProbeCatalog
from contract_driven_ai_flow.research.workbench.configuration import ConfigurationStore
from contract_driven_ai_flow.research.workbench.models import ProbeDefinition, ProbeInstance
from contract_driven_ai_flow.research.workbench.probe_defaults import (
    DEFAULT_PROBE_TASK,
    compose_probe_prompt,
    probe_parameters,
    schema_defaults,
    validate_probe_defaults,
)


def test_catalog_defaults_are_valid_and_new_bindings_are_independent():
    catalog = ProbeCatalog()
    for definition in catalog.definitions():
        parameters = probe_parameters(definition)
        Draft202012Validator(definition.parameter_schema).validate(parameters)
    definition = catalog.resolve("view.auto")
    saved = {"precision": 7, "row_labels": ["A"]}
    existing = ProbeInstance(definition_id=definition.id, parameters={"precision": 2})
    first = probe_parameters(definition, saved)
    first["row_labels"].append("B")
    assert probe_parameters(definition, saved)["row_labels"] == ["A"]
    assert existing.parameters == {"precision": 2}
    assert saved == {"precision": 7, "row_labels": ["A"]}
    assert first["show_coordinates"] is True


def test_schema_defaults_support_nested_objects_and_false_zero_null():
    schema = {"properties": {
        "enabled": {"default": False}, "count": {"default": 0}, "axis": {"default": None},
        "nested": {"type": "object", "properties": {"keys": {"default": []}}},
        "required_context": {"type": "string"},
    }}
    values = schema_defaults(schema)
    assert values == {"enabled": False, "count": 0, "axis": None, "nested": {"keys": []}}
    values["nested"]["keys"].append("x")
    assert schema_defaults(schema)["nested"]["keys"] == []


def test_probe_library_defaults_persist_separately_from_instance_parameters(tmp_path):
    store = ConfigurationStore(tmp_path)
    config = store.load()
    existing = deepcopy(config.probes)
    config.probe_defaults = {"view.auto": {"precision": 8, "show_values": True}}
    validate_probe_defaults(config.probe_defaults, ProbeCatalog().definitions())
    saved = store.save(config, expected_revision=config.revision)
    reloaded = ConfigurationStore(tmp_path).load()
    assert reloaded.probe_defaults == saved.probe_defaults
    assert reloaded.probes == existing
    new = probe_parameters(ProbeCatalog().resolve("view.auto"), reloaded.probe_defaults["view.auto"])
    assert new["precision"] == 8 and new["show_values"] is True


def test_legacy_configuration_keeps_parameters_and_has_no_authored_defaults(tmp_path):
    (tmp_path / "workbench.yaml").write_text(
        "revision: 3\nprobes:\n- id: old\n  definition_id: view.auto\n  parameters: {}\n",
        encoding="utf-8",
    )
    config = ConfigurationStore(tmp_path).load()
    assert config.probe_defaults == {} and config.probes[0].parameters == {}


@pytest.mark.parametrize("defaults,match", [
    ({"unknown.probe": {}}, "not registered"),
    ({"view.auto": {"precision": -1}}, "precision"),
    ({"view.auto": {"palette": "invalid"}}, "palette"),
    ({"view.auto": {"nested": [{"api_key": "sensitive"}]}}, "credentials"),
    ({"interpret.model": {"Authorization": "Bearer sensitive"}}, "credentials"),
])
def test_invalid_or_credential_defaults_are_rejected(defaults, match):
    with pytest.raises(ValueError, match=match):
        validate_probe_defaults(defaults, ProbeCatalog().definitions())


def test_custom_defaults_validate_against_the_live_definition():
    definition = ProbeDefinition(id="view.custom", label="Custom", capability="view", execution="builtin",
        parameter_schema={"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1}}, "additionalProperties": False})
    validate_probe_defaults({definition.id: {"limit": 3}}, [definition])
    with pytest.raises(ValueError, match="limit"):
        validate_probe_defaults({definition.id: {"limit": 0}}, [definition])


def test_structured_model_requirements_compose_into_the_actual_question():
    prompt = compose_probe_prompt({"task": "Explain covariance", "focus": "Symmetry", "constraints": "Do not invent a full matrix", "output_format": "Three bullets", "prompt": "Use Chinese"})
    assert "任务：Explain covariance" in prompt
    assert "关注重点：Symmetry" in prompt
    assert "约束：Do not invent a full matrix" in prompt
    assert "输出格式：Three bullets" in prompt
    assert "补充指令：Use Chinese" in prompt


def test_legacy_prompt_is_preserved_and_blank_requirements_use_fallback():
    legacy = "  Preserve this exact instruction\n"
    assert compose_probe_prompt({"prompt": legacy}) == legacy
    assert compose_probe_prompt({}) == DEFAULT_PROBE_TASK
    assert compose_probe_prompt({"task": " ", "focus": "", "constraints": "", "output_format": None}) == DEFAULT_PROBE_TASK
    assert compose_probe_prompt({"prompt": "Legacy task", "focus": "Evidence"}) == "任务：Legacy task\n\n关注重点：Evidence"


@pytest.mark.parametrize("selected_model", ["selected-model", ""])
def test_model_probe_sends_all_requirements_and_records_the_exact_fixture_prompt(tmp_path, selected_model):
    import json
    import threading

    import httpx

    from contract_driven_ai_flow.research.service import ResearchService
    from contract_driven_ai_flow.research.workbench.models import ExecutionPlan, ResolvedProbeCall, TaskRecord
    from contract_driven_ai_flow.research.workbench.planning import fingerprint
    from contract_driven_ai_flow.research.workbench.scopes import source_targets
    from contract_driven_ai_flow.settings.models import ProviderProfile
    from contract_driven_ai_flow.settings.service import ModelSettingsService

    calls = []
    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {
            "content": json.dumps({"answer": "Fixture interpretation", "citations": []})
        }}]})

    script = tmp_path / "analysis.py"
    script.write_text("X = 1\n", encoding="utf-8")
    settings = ModelSettingsService(tmp_path, transport=httpx.MockTransport(respond))
    settings.save(ProviderProfile(id="fixture", protocol="openai-compatible",
        base_url="https://fixture.invalid/v1", models=["selected-model"], default_model="selected-model"))
    try:
        with ResearchService(tmp_path) as research:
            workbench = research.workbench
            workbench.models = settings
            analysis = workbench.import_source(script)
            config = workbench.configurations.load()
            policy = next(item for item in config.harness if item.role == "probe")
            policy.provider_id = "other-service"
            policy.model = "other-model"
            definition = workbench.catalog.resolve("interpret.model")
            parameters = {"provider_id": "fixture", "model": selected_model, "task": "Explain the actual source",
                "focus": "X", "constraints": "No imagined execution", "output_format": "One sentence"}
            instance = ProbeInstance(definition_id=definition.id, parameters=parameters)
            config.probes = [instance]
            target = next(target for target in source_targets(analysis) if target.kind == "file")
            invocation = ResolvedProbeCall(definition=definition, instance=instance, targets=[target])
            plan = ExecutionPlan(analysis_id=analysis.id, source_digest=analysis.source_digest,
                config_digest=fingerprint(config), config=config, definitions=[definition])
            output = workbench._evaluate_call(invocation, None, plan, TaskRecord(kind="fixture"), threading.Event())
            assert output.status == "ready" and len(calls) == 1
            assert calls[0]["model"] == "selected-model"
            assert calls[0]["messages"][-1]["content"] == compose_probe_prompt(parameters)
            context = workbench.store.get("contexts", output.data["context_id"])
            assert context["calls"][0]["messages"] == calls[0]["messages"]
            assert "No imagined execution" in context["calls"][0]["messages"][-1]["content"]
    finally:
        settings.close()
