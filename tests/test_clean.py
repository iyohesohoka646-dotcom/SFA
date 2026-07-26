"""Tests for `sfa clean`: metadata reset that preserves sfa.yml."""
from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from sfa import extract as extract_mod
from sfa import init as init_mod
from sfa import module as module_mod
from sfa.cli import app
from sfa.config import CONFIG_FILENAME, SFA_DIR_NAME, SFAError

runner = CliRunner()

SAMPLE = 'def f(x: int) -> int:\n    """d"""\n    return x\n'


def test_clean_resets_metadata_keeps_config(tmp_path: Path) -> None:
    root = init_mod.init_project(tmp_path)
    cfg = root / CONFIG_FILENAME
    cfg_data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    cfg_data["project"]["name"] = "kept-name"
    cfg.write_text(
        yaml.safe_dump(cfg_data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )

    src = root / "src"
    src.mkdir()
    (src / "a.py").write_text(SAMPLE, encoding="utf-8")
    extract_mod.extract(root)
    module_mod.add_module(root, "m", "f")

    meta = root / SFA_DIR_NAME
    assert (meta / "elements.json").is_file()
    assert (meta / "modules" / "m" / "contract.json").is_file()

    init_mod.clean_project(root)

    assert (meta / "pipeline.yml").is_file()
    assert (
        (meta / "pipeline.yml").read_text(encoding="utf-8").strip()
        == "modules: []\npipes: []"
    )
    assert {p.name for p in meta.iterdir() if p.is_dir()} == {
        "modules",
        "history",
        "snapshots",
        "logs",
        "probes",
    }
    assert not (meta / "elements.json").is_file()
    assert not (meta / "modules" / "m").exists()
    cfg_after = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert cfg_after["project"]["name"] == "kept-name"


def test_clean_requires_init(tmp_path: Path) -> None:
    try:
        init_mod.clean_project(tmp_path)
    except SFAError as exc:
        assert ".sfa" in str(exc) or "init" in str(exc)
        return
    raise AssertionError("expected SFAError when .sfa/ is missing")


def test_clean_cli_yes(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--target", str(tmp_path)])
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text(SAMPLE, encoding="utf-8")
    runner.invoke(app, ["extract", "--project", str(tmp_path)])
    runner.invoke(
        app, ["module", "add", "--name", "m", "--entry", "f", "--project", str(tmp_path)]
    )

    res = runner.invoke(app, ["clean", "--yes", "--project", str(tmp_path)])
    assert res.exit_code == 0, res.stdout
    assert "已清理" in res.stdout
    pipeline = (tmp_path / ".sfa" / "pipeline.yml").read_text(encoding="utf-8").strip()
    assert pipeline == "modules: []\npipes: []"
    assert not (tmp_path / ".sfa" / "elements.json").is_file()


def test_clean_cli_cancelled(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--target", str(tmp_path)])
    res = runner.invoke(app, ["clean", "--project", str(tmp_path)], input="n\n")
    assert res.exit_code == 0
    assert "已取消" in res.stdout
