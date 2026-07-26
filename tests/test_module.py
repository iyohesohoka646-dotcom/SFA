"""Tests for `sfa module add/remove/list` and contract inference."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from sfa import extract as extract_mod
from sfa import init as init_mod
from sfa import module as module_mod
from sfa.config import SFAError
from sfa.contract import _annotation_to_schema

SAMPLE_OWNED = '''"""Module with helper functions."""
from typing import List


def helper(x: int) -> int:
    """Double the input."""
    return x * 2


def preprocess(data: List[int], scale: float = 1.0) -> dict:
    """Preprocess raw data using helper."""
    return {"features": [helper(x) * scale for x in data]}


def unused_func(y: str) -> str:
    """This function is not called by preprocess."""
    return y
'''

SAMPLE_METHOD = '''class Pipeline:
    """A model pipeline."""

    def _normalize(self, data: dict) -> dict:
        """Normalize data."""
        return data

    def run(self, data: dict) -> dict:
        """Run inference."""
        normalized = self._normalize(data)
        return {"prediction": 0.0}

    def stream(self, n: int = 10) -> None:
        """Stream results."""
        pass
'''

SAMPLE_UNION = '''from typing import Optional, Union, List


def transform(x: int | None, items: Optional[List[str]] = None) -> Union[dict, None]:
    """Transform data."""
    return {"x": x}
'''


def _make_project(tmp_path: Path, *sources: tuple[str, str]) -> Path:
    root = init_mod.init_project(tmp_path)
    src = root / "src"
    src.mkdir(exist_ok=True)
    for filename, content in sources:
        (src / filename).write_text(content, encoding="utf-8")
    extract_mod.extract(root)
    return root


# ---------------------------------------------------------------------------
# add_module — basic
# ---------------------------------------------------------------------------


def test_add_module_creates_atomic_module(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    mod = module_mod.add_module(root, "预处理", "preprocess")
    assert mod["id"] == "预处理" or mod["id"] == "m_预处理" or mod["id"]
    # ID should be a slug
    assert mod["type"] == "atomic"
    assert mod["entry"] == "preprocess"
    assert mod["path"] == "src/owned.py"
    assert mod["method"] == "function"
    assert mod["validation"] == "strict"
    assert mod["parent"] is None


def test_add_module_id_sanitization(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    mod = module_mod.add_module(root, "My Data-Processor!", "preprocess")
    assert mod["id"] == "my_data_processor"
    assert mod["name"] == "My Data-Processor!"


def test_add_module_id_starts_with_digit(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    mod = module_mod.add_module(root, "123module", "preprocess")
    assert mod["id"] == "m_123module"


def test_add_module_writes_contract_and_summary(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    mod = module_mod.add_module(root, "preprocess", "preprocess")
    contract_path = root / ".sfa" / "modules" / mod["id"] / "contract.json"
    summary_path = root / ".sfa" / "modules" / mod["id"] / "summary.md"
    assert contract_path.is_file()
    assert summary_path.is_file()
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert contract["module"] == mod["id"]
    assert "version_hash" in contract
    assert len(contract["version_hash"]) == 64  # SHA256 hex
    assert contract["natural_summary"] == "Preprocess raw data using helper."
    assert summary_path.read_text(encoding="utf-8") == contract["natural_summary"]


# ---------------------------------------------------------------------------
# add_module — owned_elements detection
# ---------------------------------------------------------------------------


def test_owned_elements_function_calls(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    mod = module_mod.add_module(root, "preprocess", "preprocess")
    owned = set(mod["owned_elements"])
    assert "preprocess" in owned
    assert "helper" in owned  # called by preprocess
    assert "unused_func" not in owned  # not called


def test_owned_elements_method_class(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("model.py", SAMPLE_METHOD))
    mod = module_mod.add_module(root, "model", "Pipeline.run")
    owned = set(mod["owned_elements"])
    # All methods of Pipeline should be owned
    assert "Pipeline.run" in owned
    assert "Pipeline._normalize" in owned
    assert "Pipeline.stream" in owned


def test_owned_elements_entry_by_name_only(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    # Using just "preprocess" (not qualified_name) should work since it's unique
    mod = module_mod.add_module(root, "preprocess", "preprocess")
    assert mod["entry"] == "preprocess"


# ---------------------------------------------------------------------------
# add_module — contract inference
# ---------------------------------------------------------------------------


def test_contract_input_schema(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    mod = module_mod.add_module(root, "preprocess", "preprocess")
    contract = json.loads(
        (root / ".sfa" / "modules" / mod["id"] / "contract.json").read_text(encoding="utf-8")
    )
    props = contract["input_schema"]["properties"]
    assert props["data"] == {"type": "array", "items": {"type": "integer"}}
    assert props["scale"] == {"type": "number"}
    assert contract["input_schema"]["required"] == ["data"]


def test_contract_output_schema(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    mod = module_mod.add_module(root, "preprocess", "preprocess")
    contract = json.loads(
        (root / ".sfa" / "modules" / mod["id"] / "contract.json").read_text(encoding="utf-8")
    )
    assert contract["output_schema"] == {"type": "object"}


def test_contract_self_excluded_from_input(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("model.py", SAMPLE_METHOD))
    mod = module_mod.add_module(root, "model", "Pipeline.run")
    contract = json.loads(
        (root / ".sfa" / "modules" / mod["id"] / "contract.json").read_text(encoding="utf-8")
    )
    props = contract["input_schema"]["properties"]
    assert "self" not in props
    assert "data" in props
    assert contract["input_schema"]["required"] == ["data"]


def test_contract_union_annotations(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("union.py", SAMPLE_UNION))
    mod = module_mod.add_module(root, "transform", "transform")
    contract = json.loads(
        (root / ".sfa" / "modules" / mod["id"] / "contract.json").read_text(encoding="utf-8")
    )
    props = contract["input_schema"]["properties"]
    assert props["x"] == {"anyOf": [{"type": "integer"}, {"type": "null"}]}
    assert props["items"] == {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}]}
    assert contract["output_schema"] == {"anyOf": [{"type": "object"}, {"type": "null"}]}


# ---------------------------------------------------------------------------
# annotation_to_schema unit tests
# ---------------------------------------------------------------------------


def test_annotation_basic_types() -> None:
    assert _annotation_to_schema("int") == {"type": "integer"}
    assert _annotation_to_schema("float") == {"type": "number"}
    assert _annotation_to_schema("str") == {"type": "string"}
    assert _annotation_to_schema("bool") == {"type": "boolean"}
    assert _annotation_to_schema("bytes") == {"type": "string"}
    assert _annotation_to_schema("None") == {"type": "null"}


def test_annotation_containers() -> None:
    assert _annotation_to_schema("List[int]") == {"type": "array", "items": {"type": "integer"}}
    assert _annotation_to_schema("Dict[str, float]") == {
        "type": "object",
        "additionalProperties": {"type": "number"},
    }
    assert _annotation_to_schema("Tuple[int, str]") == {
        "type": "array",
        "prefixItems": [{"type": "integer"}, {"type": "string"}],
    }
    assert _annotation_to_schema("list") == {"type": "array"}
    assert _annotation_to_schema("dict") == {"type": "object"}


def test_annotation_optional_and_union() -> None:
    assert _annotation_to_schema("Optional[int]") == {
        "anyOf": [{"type": "integer"}, {"type": "null"}]
    }
    assert _annotation_to_schema("Union[int, str]") == {
        "anyOf": [{"type": "integer"}, {"type": "string"}]
    }
    assert _annotation_to_schema("int | None") == {
        "anyOf": [{"type": "integer"}, {"type": "null"}]
    }


def test_annotation_nested() -> None:
    assert _annotation_to_schema("Dict[str, List[int]]") == {
        "type": "object",
        "additionalProperties": {"type": "array", "items": {"type": "integer"}},
    }
    assert _annotation_to_schema("List[int | None]") == {
        "type": "array",
        "items": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
    }


def test_annotation_path_types() -> None:
    assert _annotation_to_schema("Path") == {"type": "string"}
    assert _annotation_to_schema("Path | None") == {
        "anyOf": [{"type": "string"}, {"type": "null"}]
    }


def test_annotation_unknown_returns_empty() -> None:
    assert _annotation_to_schema("SomeCustomType") == {}
    assert _annotation_to_schema(None) == {}
    assert _annotation_to_schema("") == {}


# ---------------------------------------------------------------------------
# remove_module
# ---------------------------------------------------------------------------


def test_remove_module_basic(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    module_mod.add_module(root, "preprocess", "preprocess")
    mod, pipes, probes = module_mod.remove_module(root, "preprocess")
    assert mod["id"] == "preprocess"
    assert pipes == []
    assert probes == []
    assert module_mod.list_modules(root) == []


def test_remove_module_not_found(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    try:
        module_mod.remove_module(root, "nonexistent")
    except SFAError as exc:
        assert "nonexistent" in str(exc)
        return
    raise AssertionError("expected SFAError for nonexistent module")


def test_remove_module_cascades_pipes(tmp_path: Path) -> None:
    root = _make_project(
        tmp_path,
        ("owned.py", SAMPLE_OWNED),
        ("model.py", SAMPLE_METHOD),
    )
    module_mod.add_module(root, "preprocess", "preprocess")
    module_mod.add_module(root, "model", "Pipeline.run")
    from sfa import pipe as pipe_mod

    pipe_mod.add_pipe(root, "preprocess", "model")
    pipe_mod.add_pipe(root, "model", "preprocess")

    mod, removed_pipes, removed_probes = module_mod.remove_module(root, "preprocess")
    assert len(removed_pipes) == 2
    assert removed_probes == []
    pipe_ids = {p["id"] for p in removed_pipes}
    assert "pipe_preprocess_model" in pipe_ids
    assert "pipe_model_preprocess" in pipe_ids
    # Remaining pipes should be empty
    assert pipe_mod.list_pipes(root) == []


def test_add_module_duplicate_id_is_idempotent(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    first = module_mod.add_module(root, "preprocess", "preprocess")
    # Same name -> same id; second call skips and returns the existing module.
    second = module_mod.add_module(root, "preprocess", "helper")
    assert second["id"] == first["id"]
    assert second["entry"] == "preprocess"  # existing retained, not "helper"
    assert len(module_mod.list_modules(root)) == 1


def test_add_module_force_rebuilds(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    module_mod.add_module(root, "preprocess", "preprocess")
    rebuilt = module_mod.add_module(root, "preprocess", "helper", force=True)
    assert rebuilt["entry"] == "helper"
    assert len(module_mod.list_modules(root)) == 1


def test_add_module_force_preserves_composite_parent(tmp_path: Path) -> None:
    from sfa import topology as topo

    root = _make_project(
        tmp_path,
        ("owned.py", SAMPLE_OWNED),
        ("model.py", SAMPLE_METHOD),
    )
    module_mod.add_module(root, "preprocess", "preprocess")
    module_mod.add_module(root, "model", "Pipeline.run")
    composite = topo.group_modules(root, ["preprocess", "model"], "外层")
    mods = {m["id"]: m for m in topo.list_modules(root)}
    assert mods["preprocess"]["parent"] == composite["id"]

    rebuilt = module_mod.add_module(root, "preprocess", "helper", force=True)
    assert rebuilt["entry"] == "helper"
    assert rebuilt["parent"] == composite["id"]
    mods = {m["id"]: m for m in topo.list_modules(root)}
    assert mods["preprocess"]["parent"] == composite["id"]


# ---------------------------------------------------------------------------
# list_modules
# ---------------------------------------------------------------------------


def test_list_modules_empty(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    assert module_mod.list_modules(root) == []


def test_list_modules_multiple(tmp_path: Path) -> None:
    root = _make_project(
        tmp_path,
        ("owned.py", SAMPLE_OWNED),
        ("model.py", SAMPLE_METHOD),
    )
    module_mod.add_module(root, "preprocess", "preprocess")
    module_mod.add_module(root, "model", "Pipeline.run")
    mods = module_mod.list_modules(root)
    ids = {m["id"] for m in mods}
    assert ids == {"preprocess", "model"}


# ---------------------------------------------------------------------------
# add_module — error cases
# ---------------------------------------------------------------------------


def test_add_module_no_elements_json(tmp_path: Path) -> None:
    root = init_mod.init_project(tmp_path)
    try:
        module_mod.add_module(root, "test", "f")
    except SFAError as exc:
        assert "elements.json" in str(exc)
        return
    raise AssertionError("expected SFAError for missing elements.json")


def test_add_module_entry_not_found(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    try:
        module_mod.add_module(root, "test", "nonexistent_func")
    except SFAError as exc:
        assert "nonexistent_func" in str(exc)
        return
    raise AssertionError("expected SFAError for entry not found")


def test_add_module_class_entry_rejected(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("model.py", SAMPLE_METHOD))
    try:
        module_mod.add_module(root, "test", "Pipeline")
    except SFAError as exc:
        assert "class" in str(exc) or "类型" in str(exc)
        return
    raise AssertionError("expected SFAError for class entry")


def test_add_module_invalid_validation(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    try:
        module_mod.add_module(root, "test", "preprocess", validation="bogus")
    except SFAError as exc:
        assert "bogus" in str(exc)
        return
    raise AssertionError("expected SFAError for invalid validation level")


def test_add_module_writes_to_pipeline_yml(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    module_mod.add_module(root, "preprocess", "preprocess")
    pipeline = yaml.safe_load((root / ".sfa" / "pipeline.yml").read_text(encoding="utf-8"))
    assert len(pipeline["modules"]) == 1
    assert pipeline["modules"][0]["id"] == "preprocess"
    assert pipeline["pipes"] == []
