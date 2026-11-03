from contract_driven_ai_flow.research.workbench.models import WorkbenchConfig, ProbeTemplate, ProbeInstance
from contract_driven_ai_flow.research.workbench.catalog import ProbeCatalog
from contract_driven_ai_flow.research.workbench.configuration import ConfigurationStore
from contract_driven_ai_flow.research.service import ResearchService
from contract_driven_ai_flow.research.workbench.models import ExecutionPlan
import yaml
import pytest


def test_new_project_uses_visible_auto_template_without_implicit_checks(tmp_path):
    config = ConfigurationStore(tmp_path).load()
    assert len(config.probes) == 1
    assert config.probes[0].template_id == "auto-data"
    assert config.probe_templates[0].label == "自动数据视图"
    assert config.probe_templates[0].members[0].definition_id == config.probes[0].definition_id


def test_deleted_template_or_binding_does_not_revive_on_reload(tmp_path):
    store = ConfigurationStore(tmp_path)
    config = store.load()
    config.probes.clear()
    config.probe_templates.clear()
    store.save(config, expected_revision=config.revision)
    restored = store.load()
    assert restored.probes == []
    assert restored.probe_templates == []


def test_legacy_auto_view_keeps_identity_parameters_and_disabled_exception():
    config = WorkbenchConfig.model_validate({"probes": [{"id": "auto-view", "definition_id": "view.auto", "enabled": False,
        "parameters": {"precision": 8}, "overrides": {"X": {"enabled": False}}}]})
    assert config.probes[0].id == "auto-view"
    assert config.probes[0].template_id == "auto-data"
    assert config.probes[0].parameters == {"precision": 8}
    assert not config.probes[0].enabled
    assert not config.probes[0].overrides["X"].enabled
    assert ProbeCatalog().resolve("view.auto").renderer == "auto"


def test_template_requires_unique_members_and_configuration_unique_template_ids():
    with pytest.raises(ValueError):
        ProbeTemplate(id="x", label="Example", members=[{"id": "same", "definition_id": "view.table"}, {"id": "same", "definition_id": "view.matrix"}])
    config = WorkbenchConfig()
    raw = config.model_dump()
    raw["probe_templates"] *= 2
    with pytest.raises(ValueError):
        WorkbenchConfig.model_validate(raw)


def test_migration_accepts_built_probe_models_and_preserves_modified_checks():
    original = ProbeInstance(id="auto", definition_id="view.auto", parameters={"precision": 7})
    config = WorkbenchConfig(probes=[original, ProbeInstance(id="finite-check", definition_id="check.finite", policy="pause")])
    assert config.probes[0].template_id == "auto-data"
    assert original.template_id is None
    assert original.parameters == {"precision": 7}
    assert config.probes[1].policy == "pause"


def test_only_active_configuration_migrates_implicit_check_and_keeps_source_bytes(tmp_path):
    raw = {"probes": [{"id": "auto-view", "definition_id": "view.auto"},
        {"id": "finite-check", "definition_id": "check.finite"}]}
    path = tmp_path / "workbench.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    original = path.read_bytes()
    config = ConfigurationStore(tmp_path).load()
    assert [p.id for p in config.probes] == ["auto-view"]
    assert path.read_bytes() == original


def test_archived_plan_retains_original_checks_when_loaded():
    config = {"probes": [{"id": "auto-view", "definition_id": "view.auto"},
        {"id": "finite-check", "definition_id": "check.finite"}]}
    plan = ExecutionPlan.model_validate({"analysis_id": "archive", "source_digest": "source",
        "config_digest": "original", "config": config, "definitions": []})
    assert [p.id for p in plan.config.probes] == ["auto-view", "finite-check"]


@pytest.mark.parametrize("definition_id, parameters", [
    ("view.matrix", {"precision": -2}),
    ("interpret.model", {"api_key": "not-a-real-key"}),
    ("derive.matmul", {}),
])
def test_invalid_template_does_not_replace_saved_configuration(tmp_path, definition_id, parameters):
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        config = wb.configurations.load()
        before = config.model_dump()
        config.probe_templates.append(ProbeTemplate(id="invalid", label="Invalid", members=[
            {"id": "member", "definition_id": definition_id, "parameters": parameters}]))
        with pytest.raises((ValueError, LookupError)):
            wb.configure(config, expected_revision=config.revision)
        assert wb.configurations.load().model_dump() == before
