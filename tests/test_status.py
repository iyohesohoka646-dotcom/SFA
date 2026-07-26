"""Tests for `sfa status`: project overview rendering."""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from sfa import extract as extract_mod
from sfa import init as init_mod
from sfa import module as module_mod
from sfa import status as status_mod
from sfa.cli import app

runner = CliRunner()

SAMPLE = 'def gen(seed: int) -> dict:\n    """g"""\n    return {"v": seed}\n'


def test_status_unextracted(tmp_path: Path) -> None:
    root = init_mod.init_project(tmp_path)
    out = status_mod.render_status(root)
    assert "sfa" in out
    assert "未提取" in out
    assert "模块：0" in out
    assert "管道：0" in out
    assert "无运行记录" in out


def test_status_with_modules(tmp_path: Path) -> None:
    root = init_mod.init_project(tmp_path)
    src = root / "src"
    src.mkdir()
    (src / "a.py").write_text(SAMPLE, encoding="utf-8")
    extract_mod.extract(root)
    module_mod.add_module(root, "gen", "gen")
    out = status_mod.render_status(root)
    assert "已提取" in out
    assert "模块：1" in out
    assert "存在" in out  # source_dir exists


def test_status_not_initialized(tmp_path: Path) -> None:
    out = status_mod.render_status(tmp_path)
    assert "未找到 SFA 项目" in out or "sfa init" in out


def test_status_cli(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--target", str(tmp_path)])
    res = runner.invoke(app, ["status", "--project", str(tmp_path)])
    assert res.exit_code == 0, res.stdout
    assert "未提取" in res.stdout
    assert "模块：0" in res.stdout


def test_status_cli_not_initialized(tmp_path: Path) -> None:
    res = runner.invoke(app, ["status", "--project", str(tmp_path)])
    assert res.exit_code == 0
    assert "未找到 SFA 项目" in res.stdout or "sfa init" in res.stdout
