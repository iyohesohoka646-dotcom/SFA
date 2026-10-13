"""Acceptance of the public delivery path, not implementation-shaped unit tests."""
import hashlib
import json
import os
from pathlib import Path
import sys


def test_release_identity_matches_desktop_and_python_clients():
    from contract_driven_ai_flow import __version__
    import importlib.metadata

    root = Path(__file__).parents[2]
    desktop = json.loads((root / "desktop/package.json").read_text(encoding="utf-8"))
    assert __version__ == desktop["version"]
    assert importlib.metadata.version("contract-driven-ai-flow") == __version__


def test_research_delivery_includes_independent_environment_and_private_reports(tmp_path):
    from scripts.research_acceptance import verify_research_delivery

    receipt = verify_research_delivery(
        Path(sys.executable), [sys.executable, "-m", "contract_driven_ai_flow"],
        tmp_path, {**os.environ, "PYTHONUTF8": "1", "CDAF_HOME": str(tmp_path / "home")},
    )
    assert receipt["result"] == "passed"
    assert receipt["independent_interpreter"]["tool_dependencies"] is False
    assert receipt["independent_interpreter"]["value"] == 42
    assert receipt["offline_privacy"] == "passed"
    assert [case["status"] for case in receipt["cases"]] == ["completed", "completed", "failed"]
    assert [case["exit_code"] for case in receipt["cases"]] == [0, 0, 1]


def test_scientific_migration_does_not_change_any_legacy_source_file(tmp_path):
    from contract_driven_ai_flow.research.legacy import import_legacy, legacy_runs

    source = tmp_path / "original"
    snapshots = source / ".sfa/snapshots/original-id"
    snapshots.mkdir(parents=True)
    (source / "sfa.yml").write_text("project: legacy\n", encoding="utf-8")
    (source / "analysis.py").write_text("X = 42\n", encoding="utf-8")
    (snapshots / "run.json").write_text(json.dumps({"run_id": "original-id", "status": "completed"}))
    (snapshots / "load.json").write_text(json.dumps({"output": {"email": "sensitive@example.org"}}))
    def fingerprints():
        return {p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in source.rglob("*") if p.is_file()}
    before = fingerprints()
    destination = tmp_path / "scientific"
    preview = import_legacy(source, destination)
    assert not preview.applied and not destination.exists()
    import_legacy(source, destination, preview=False)
    records = legacy_runs(destination)
    assert records[0]["id"] == "original-id"
    assert records[0]["scientific_values"] == "not_captured"
    assert "sensitive@example.org" not in json.dumps(records)
    assert fingerprints() == before
