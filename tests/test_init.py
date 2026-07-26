"""Tests for `sfa init`: directory scaffolding and config template."""
from __future__ import annotations

from pathlib import Path

import yaml

from sfa import init as init_mod
from sfa.config import CONFIG_FILENAME, SFA_DIR_NAME


EXPECTED_SUBDIRS = {"modules", "history", "snapshots", "logs", "probes"}


def test_init_creates_full_structure(tmp_path: Path) -> None:
    root = init_mod.init_project(tmp_path)
    meta = root / SFA_DIR_NAME
    assert meta.is_dir()
    assert (meta / "pipeline.yml").is_file()
    assert (meta / "pipeline.yml").read_text(encoding="utf-8").strip() == "modules: []\npipes: []"
    subdirs = {p.name for p in meta.iterdir() if p.is_dir()}
    assert EXPECTED_SUBDIRS == subdirs


def test_init_writes_config_template(tmp_path: Path) -> None:
    root = init_mod.init_project(tmp_path)
    cfg_file = root / CONFIG_FILENAME
    assert cfg_file.is_file()
    cfg = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
    assert cfg["project"]["name"] == "my-sfa-project"
    assert cfg["project"]["language"] == "python"
    assert cfg["source_dir"] == "src"
    assert cfg["default_visibility"] == "L2"
    assert cfg["validation"] == "strict"
    assert "allowed_imports" in cfg and isinstance(cfg["allowed_imports"], list)
    assert cfg["ai"]["provider"] in {"openai", "anthropic"}


def test_init_is_idempotent(tmp_path: Path) -> None:
    init_mod.init_project(tmp_path)
    cfg_before = (tmp_path / CONFIG_FILENAME).read_text(encoding="utf-8")
    init_mod.init_project(tmp_path)
    cfg_after = (tmp_path / CONFIG_FILENAME).read_text(encoding="utf-8")
    assert cfg_before == cfg_after


def test_init_force_overwrites(tmp_path: Path) -> None:
    init_mod.init_project(tmp_path)
    cfg = tmp_path / CONFIG_FILENAME
    cfg.write_text("project: {}\n", encoding="utf-8")
    init_mod.init_project(tmp_path, force=True)
    assert "my-sfa-project" in cfg.read_text(encoding="utf-8")
