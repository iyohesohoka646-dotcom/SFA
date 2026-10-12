"""Own schema-fidelity tests for the P4 project protocol export.

These read the generated JSON schemas and the TypeScript generator script only;
they do not run Node or contact a network.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "src/contract_driven_ai_flow/schemas"

REQUIRED = (
    "ResearchProject",
    "ProjectRevision",
    "SourceUnit",
    "FilePage",
    "ProjectGraphSlice",
    "RunConfiguration",
    "ProjectSection",
    "ProjectExecutionReceipt",
    "TreePage",
    "ObjectPage",
    "ReferencePage",
    "ProjectChangeSet",
    "ProjectChangePage",
    "ProjectRecoveryState",
    "ProjectAIRequest",
    "ProjectContextPreview",
    "SourceRef",
    "TargetRef",
)


def _schema(name):
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def test_legacy_project_spec_schema_is_preserved():
    project = _schema("project.json")
    assert project["title"] == "ProjectSpec"


def test_project_protocol_is_a_separate_explicit_schema():
    protocol = _schema("projects.json")
    assert protocol["title"] == "ProjectProtocol"
    definitions = protocol["$defs"]
    for name in REQUIRED:
        assert name in definitions, name
    assert "project_id" in definitions["TargetRef"]["properties"]
    assert "project_revision_id" in definitions["SourceRef"]["properties"]


def test_context_preview_is_typed_and_bounded():
    preview = _schema("projects.json")["$defs"]["ProjectContextPreview"]
    assert set(preview["properties"]) == {
        "project_id",
        "project_revision_id",
        "messages",
        "token_bound",
        "tools",
    }
    assert preview["properties"]["token_bound"]["minimum"] == 0
    assert preview["properties"]["messages"]["type"] == "array"
    assert preview["properties"]["tools"]["type"] == "array"


def test_existing_generators_and_workbench_protocol_are_preserved():
    workbench = _schema("workbench.json")
    assert workbench["title"] == "WorkbenchProtocol"
    assert "TaskRecord" in workbench["$defs"]


def test_protocol_export_carries_no_private_runtime_paths():
    text = (SCHEMAS / "projects.json").read_text(encoding="utf-8")
    for leak in ("local_runtime", "manifest_path", "runtime_manifest", "credential"):
        assert leak not in text


def test_typescript_generator_targets_the_project_protocol():
    script = (ROOT / "web/scripts/types.mjs").read_text(encoding="utf-8")
    assert "../src/contract_driven_ai_flow/schemas/projects.json" in script
    assert "src/research/projects/generated.ts" in script
    assert "recursive: true" in script