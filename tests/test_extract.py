"""Tests for `sfa extract`: tree-sitter parsing into elements.json."""
from __future__ import annotations

import json
from pathlib import Path

from sfa import extract as extract_mod
from sfa import init as init_mod
from sfa.config import SFA_DIR_NAME, SFAError

SAMPLE_PREPROCESS = '''"""Preprocessing module."""
from typing import List


def preprocess(data: List[int], scale: float = 1.0) -> dict:
    """Preprocess raw data."""
    return {"features": [x * scale for x in data]}


async def fetch(url: str) -> bytes:
    """Fetch a resource."""
    return b""
'''

SAMPLE_MODEL = '''class Pipeline:
    """A model pipeline."""

    def run(self, data: dict) -> dict:
        """Run inference."""
        return {"prediction": 0.0}

    async def stream(self, n: int = 10, *args, **kwargs) -> None:
        """Stream results."""
        pass
'''


def _make_project(tmp_path: Path) -> Path:
    root = init_mod.init_project(tmp_path)
    src = root / "src"
    src.mkdir(exist_ok=True)
    (src / "preprocess.py").write_text(SAMPLE_PREPROCESS, encoding="utf-8")
    (src / "model.py").write_text(SAMPLE_MODEL, encoding="utf-8")
    return root


def test_extract_writes_elements_json(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    doc, out = extract_mod.extract(root)
    expected = root / SFA_DIR_NAME / "elements.json"
    assert out == expected
    assert out.is_file()
    on_disk = json.loads(out.read_text(encoding="utf-8"))
    assert on_disk == doc
    assert doc["version"] == 1
    assert doc["source_dir"] == "src"
    assert "generated_at" in doc


def _by_qualified(doc: dict, qname: str) -> dict:
    for el in doc["elements"]:
        if el["qualified_name"] == qname:
            return el
    raise AssertionError(f"element {qname} not found in {doc['elements']}")


def test_extract_captures_function_with_annotations(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    doc, _ = extract_mod.extract(root)
    fn = _by_qualified(doc, "preprocess")
    assert fn["kind"] == "function"
    assert fn["file"] == "preprocess.py"
    assert fn["line_start"] >= 1 and fn["line_end"] > fn["line_start"]
    assert fn["return_annotation"] == "dict"
    assert fn["docstring"] == "Preprocess raw data."
    params = {p["name"]: p for p in fn["parameters"]}
    assert params["data"]["annotation"] == "List[int]"
    assert params["data"]["has_default"] is False
    assert params["scale"]["annotation"] == "float"
    assert params["scale"]["has_default"] is True
    assert params["scale"]["default"] == "1.0"


def test_extract_captures_async_function(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    doc, _ = extract_mod.extract(root)
    fn = _by_qualified(doc, "fetch")
    assert fn["kind"] == "async_function"
    assert fn["return_annotation"] == "bytes"
    assert fn["parameters"][0]["name"] == "url"


def test_extract_captures_class_and_methods(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    doc, _ = extract_mod.extract(root)
    cls = _by_qualified(doc, "Pipeline")
    assert cls["kind"] == "class"
    assert cls["docstring"] == "A model pipeline."
    assert cls["parent_class"] is None

    run = _by_qualified(doc, "Pipeline.run")
    assert run["kind"] == "method"
    assert run["parent_class"] == "Pipeline"
    assert run["docstring"] == "Run inference."

    stream = _by_qualified(doc, "Pipeline.stream")
    assert stream["kind"] == "method"
    names = [p["name"] for p in stream["parameters"]]
    assert names == ["n", "args", "kwargs"]


def test_extract_missing_source_dir_raises(tmp_path: Path) -> None:
    root = init_mod.init_project(tmp_path)
    # source_dir 'src' does not exist
    try:
        extract_mod.extract(root)
    except SFAError as exc:
        assert "source_dir" in str(exc) or "sfa.yml" in str(exc)
        return
    raise AssertionError("expected SFAError for missing source_dir")


def test_malformed_config_raises_clean_error(tmp_path: Path) -> None:
    root = init_mod.init_project(tmp_path)
    # 'project' should be a mapping; supply a scalar to trigger the guard
    (root / "sfa.yml").write_text("project: not-a-mapping\n", encoding="utf-8")
    try:
        extract_mod.extract(root)
    except SFAError as exc:
        msg = str(exc)
        assert "project" in msg
        assert "sfa.yml" in msg  # path included per road.md error contract
        return
    raise AssertionError("expected SFAError for malformed config")
