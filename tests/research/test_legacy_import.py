import json

import pytest


def legacy_source(path):
    from contract_driven_ai_flow.examples import create_example
    from contract_driven_ai_flow.storage import Store
    from contract_driven_ai_flow.runtime import Runner

    create_example(path)
    store = Store(path)
    runner = Runner(path)
    result = runner.run({"values": [1, 2, 3]})
    return result["id"]


def test_legacy_import_preserves_source_and_ids(tmp_path):
    from contract_driven_ai_flow.research.legacy import import_legacy, legacy_runs

    source, destination = tmp_path / "old", tmp_path / "new"
    run_id = legacy_source(source)
    original = (source / "flow.yaml").read_bytes()
    preview = import_legacy(source, destination)
    assert preview.applied is False and not destination.exists()
    assert run_id in preview.original_ids
    applied = import_legacy(source, destination, preview=False)
    assert applied.applied
    assert (source / "flow.yaml").read_bytes() == original
    records = legacy_runs(destination)
    assert records[0]["id"] == run_id and records[0]["format"] == "legacy-port-flow"
    assert records[0]["scientific_values"] == "not_captured"


def test_legacy_import_never_overwrites_existing_destination(tmp_path):
    from contract_driven_ai_flow.research.legacy import import_legacy

    source, destination = tmp_path / "old", tmp_path / "new"
    legacy_source(source)
    destination.mkdir()
    marker = destination / "analysis.py"
    marker.write_text("my code", encoding="utf-8")
    with pytest.raises((ValueError, FileExistsError)):
        import_legacy(source, destination, preview=False)
    assert marker.read_text() == "my code"


def test_original_sfa_snapshots_keep_original_ids_and_json_semantics(tmp_path):
    from contract_driven_ai_flow.research.legacy import import_legacy, legacy_runs

    source, destination = tmp_path / "sfa", tmp_path / "scientific"
    snapshots = source / ".sfa/snapshots/original-run-1"
    snapshots.mkdir(parents=True)
    (source / "sfa.yml").write_text("project: Original SFA\n")
    manifest = {"run_id": "original-run-1", "status": "completed", "execution_order": ["load"]}
    (snapshots / "run.json").write_text(json.dumps(manifest))
    (snapshots / "load.json").write_text(json.dumps({"input": {}, "output": {"value": 5}, "status": "completed"}))
    preview = import_legacy(source, destination)
    assert preview.original_ids == ["original-run-1"] and not destination.exists()
    import_legacy(source, destination, preview=False)
    record = legacy_runs(destination)[0]
    assert record["id"] == "original-run-1" and record["format"] == "legacy-sfa-json"
    assert record["manifest"] == manifest
    assert record["snapshots"]["load"]["output"] == {"value": 5}
    assert record["scientific_values"] == "not_captured"
    assert (snapshots / "load.json").is_file()
