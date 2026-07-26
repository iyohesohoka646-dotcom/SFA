"""Smoke tests for the CLI surface (init/extract/module/pipe run, M4+ placeholders exit 0)."""
from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from sfa.cli import app

runner = CliRunner()


def _make_offline_project(tmp_path: Path) -> Path:
    runner.invoke(app, ["init", "--target", str(tmp_path)])
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text('def f(x: int) -> int:\n    """d"""\n    return x\n', encoding="utf-8")
    runner.invoke(app, ["extract", "--project", str(tmp_path)])
    runner.invoke(app, ["module", "add", "--name", "mod_a", "--entry", "f", "--project", str(tmp_path)])
    # Force mock provider for offline generate tests.
    cfg_path = tmp_path / "sfa.yml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    cfg.setdefault("ai", {})
    cfg["ai"]["provider"] = "mock"
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return tmp_path


def test_version() -> None:
    res = runner.invoke(app, ["--version"])
    assert res.exit_code == 0
    assert "sfa" in res.stdout


def test_init_command(tmp_path: Path) -> None:
    res = runner.invoke(app, ["init", "--target", str(tmp_path)])
    assert res.exit_code == 0
    assert (tmp_path / ".sfa").is_dir()
    assert (tmp_path / "sfa.yml").is_file()


def test_extract_command(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--target", str(tmp_path)])
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text('def f(x: int) -> int:\n    """d"""\n    return x\n', encoding="utf-8")
    res = runner.invoke(app, ["extract", "--project", str(tmp_path)])
    assert res.exit_code == 0, res.stdout
    doc = json.loads((tmp_path / ".sfa" / "elements.json").read_text(encoding="utf-8"))
    assert any(el["name"] == "f" for el in doc["elements"])


def test_m2_module_add_via_cli(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--target", str(tmp_path)])
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text('def f(x: int) -> int:\n    """d"""\n    return x\n', encoding="utf-8")
    runner.invoke(app, ["extract", "--project", str(tmp_path)])
    res = runner.invoke(app, ["module", "add", "--name", "my module", "--entry", "f", "--project", str(tmp_path)])
    assert res.exit_code == 0, res.stdout
    assert "my_module" in res.stdout


def test_m2_pipe_add_via_cli(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--target", str(tmp_path)])
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text('def f(x: int) -> int:\n    """d"""\n    return x\n', encoding="utf-8")
    (src / "b.py").write_text('def g(y: str) -> bool:\n    """e"""\n    return True\n', encoding="utf-8")
    runner.invoke(app, ["extract", "--project", str(tmp_path)])
    runner.invoke(app, ["module", "add", "--name", "mod_a", "--entry", "f", "--project", str(tmp_path)])
    runner.invoke(app, ["module", "add", "--name", "mod_b", "--entry", "g", "--project", str(tmp_path)])
    res = runner.invoke(app, ["pipe", "add", "mod_a", "mod_b", "--project", str(tmp_path)])
    assert res.exit_code == 0, res.stdout
    assert "pipe_mod_a_mod_b" in res.stdout


def test_list_graph_empty_project(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--target", str(tmp_path)])
    for cmd in ["list", "graph"]:
        res = runner.invoke(app, [cmd, "--project", str(tmp_path)])
        assert res.exit_code == 0, f"{cmd} failed: {res.stdout}"
        assert "暂无模块" in res.stdout


def test_probe_add_help_no_args_succeeds(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--target", str(tmp_path)])
    res = runner.invoke(app, ["probe", "add"])
    # Typer prints help on missing subcommand (exit code 2); we just verify it
    # shows the real subcommands and is not a placeholder.
    assert "router" in res.stdout and "assertion" in res.stdout
    assert "尚未实现" not in res.stdout and "未实现" not in res.stdout


def test_generate_via_cli(tmp_path: Path) -> None:
    root = _make_offline_project(tmp_path)
    res = runner.invoke(app, ["generate", "mod_a", "--yes", "--project", str(root)])
    assert res.exit_code == 0, res.stdout
    assert "已应用" in res.stdout or "无变更" in res.stdout
    # History version should now exist.
    history_dir = root / ".sfa" / "history" / "mod_a"
    assert history_dir.is_dir()
    assert any(history_dir.iterdir())
    # The entry function body should have changed.
    content = (root / "src" / "a.py").read_text(encoding="utf-8")
    assert "NotImplementedError" in content


def test_rollback_via_cli(tmp_path: Path) -> None:
    root = _make_offline_project(tmp_path)
    original = (root / "src" / "a.py").read_text(encoding="utf-8")
    runner.invoke(app, ["generate", "mod_a", "--yes", "--project", str(root)])

    # Rollback interactively: select version 1 and confirm.
    res = runner.invoke(app, ["rollback", "mod_a", "--project", str(root)], input="1\ny\n")
    assert res.exit_code == 0, res.stdout
    assert "已恢复" in res.stdout
    restored = (root / "src" / "a.py").read_text(encoding="utf-8")
    assert restored == original


def test_generate_nonexistent_module(tmp_path: Path) -> None:
    root = _make_offline_project(tmp_path)
    res = runner.invoke(app, ["generate", "nope", "--project", str(root)])
    assert res.exit_code != 0


def test_rollback_no_history(tmp_path: Path) -> None:
    root = _make_offline_project(tmp_path)
    res = runner.invoke(app, ["rollback", "mod_a", "--project", str(root)])
    assert res.exit_code == 0
    assert "无历史版本" in res.stdout


# ---------------------------------------------------------------------------
# run / observe (M4)
# ---------------------------------------------------------------------------

GEN_SRC = 'def gen(seed: int) -> dict:\n    """gen."""\n    return {"features": [seed, seed * 2]}\n'
INFER_SRC = 'def infer(features: list) -> dict:\n    """infer."""\n    return {"prediction": sum(features)}\n'
INFER_RAISE_SRC = 'def infer(features: list) -> dict:\n    """infer."""\n    raise ValueError("boom")\n'


def _make_runnable_project(tmp_path: Path, infer_src: str = INFER_SRC) -> Path:
    runner.invoke(app, ["init", "--target", str(tmp_path)])
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text(GEN_SRC, encoding="utf-8")
    (src / "b.py").write_text(infer_src, encoding="utf-8")
    runner.invoke(app, ["extract", "--project", str(tmp_path)])
    runner.invoke(app, ["module", "add", "--name", "gen", "--entry", "gen", "--project", str(tmp_path)])
    runner.invoke(app, ["module", "add", "--name", "infer", "--entry", "infer", "--project", str(tmp_path)])
    runner.invoke(app, ["pipe", "add", "gen", "infer", "--project", str(tmp_path)])
    return tmp_path


def test_run_success(tmp_path: Path) -> None:
    root = _make_runnable_project(tmp_path)
    inp = root / "input.json"
    inp.write_text(json.dumps({"seed": 5}), encoding="utf-8")
    res = runner.invoke(app, ["run", "--input", str(inp), "--project", str(root)])
    assert res.exit_code == 0, res.stdout
    assert "success" in res.stdout
    assert "模块数：2" in res.stdout
    # snapshots + manifest written
    runs = (root / ".sfa" / "snapshots").iterdir()
    run_dirs = [p for p in runs if p.is_dir()]
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "run.json").is_file()
    assert (run_dirs[0] / "gen.json").is_file()
    assert (run_dirs[0] / "infer.json").is_file()


def test_run_no_input_strict_validation_fails(tmp_path: Path) -> None:
    root = _make_runnable_project(tmp_path)
    # gen requires 'seed' (no default); no --input => input contract fails (strict).
    res = runner.invoke(app, ["run", "--project", str(root)])
    assert res.exit_code == 1, res.stdout


def test_run_no_atomic_modules(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--target", str(tmp_path)])
    res = runner.invoke(app, ["run", "--project", str(tmp_path)])
    assert res.exit_code == 0
    assert "无原子模块" in res.stdout


def test_run_input_file_missing(tmp_path: Path) -> None:
    root = _make_runnable_project(tmp_path)
    res = runner.invoke(app, ["run", "--input", "nope.json", "--project", str(root)])
    assert res.exit_code == 1


def test_observe_no_runs(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--target", str(tmp_path)])
    res = runner.invoke(app, ["observe", "--project", str(tmp_path)])
    assert res.exit_code == 0
    assert "暂无运行记录" in res.stdout


def test_observe_summary_after_run(tmp_path: Path) -> None:
    root = _make_runnable_project(tmp_path)
    inp = root / "input.json"
    inp.write_text(json.dumps({"seed": 5}), encoding="utf-8")
    runner.invoke(app, ["run", "--input", str(inp), "--project", str(root)])
    res = runner.invoke(app, ["observe", "--project", str(root)])
    assert res.exit_code == 0, res.stdout
    assert "gen" in res.stdout
    assert "infer" in res.stdout
    assert "OK" in res.stdout


def test_observe_module_detail(tmp_path: Path) -> None:
    root = _make_runnable_project(tmp_path)
    inp = root / "input.json"
    inp.write_text(json.dumps({"seed": 5}), encoding="utf-8")
    runner.invoke(app, ["run", "--input", str(inp), "--project", str(root)])
    res = runner.invoke(app, ["observe", "infer", "--project", str(root)])
    assert res.exit_code == 0, res.stdout
    assert "prediction" in res.stdout
    assert "15" in res.stdout


def test_observe_unknown_module(tmp_path: Path) -> None:
    root = _make_runnable_project(tmp_path)
    inp = root / "input.json"
    inp.write_text(json.dumps({"seed": 5}), encoding="utf-8")
    runner.invoke(app, ["run", "--input", str(inp), "--project", str(root)])
    res = runner.invoke(app, ["observe", "nope", "--project", str(root)])
    assert res.exit_code == 1


def test_run_fail_fast(tmp_path: Path) -> None:
    root = _make_runnable_project(tmp_path, infer_src=INFER_RAISE_SRC)
    inp = root / "input.json"
    inp.write_text(json.dumps({"seed": 5}), encoding="utf-8")
    res = runner.invoke(app, ["run", "--input", str(inp), "--project", str(root)])
    assert res.exit_code == 1, res.stdout
    # Fail-fast: error snapshot + manifest recorded on disk.
    latest = (root / ".sfa" / "snapshots" / ".latest").read_text(encoding="utf-8").strip()
    manifest = json.loads((root / ".sfa" / "snapshots" / latest / "run.json").read_text(encoding="utf-8"))
    assert manifest["overall_status"] == "error"
    infer_rec = next(r for r in manifest["modules"] if r["id"] == "infer")
    assert infer_rec["status"] == "error"
    gen_rec = next(r for r in manifest["modules"] if r["id"] == "gen")
    assert gen_rec["status"] == "success"
    infer_snap = json.loads((root / ".sfa" / "snapshots" / latest / "infer.json").read_text(encoding="utf-8"))
    assert infer_snap["status"] == "error"
    assert "boom" in infer_snap["error"]
    # observe should show ERR for infer.
    res2 = runner.invoke(app, ["observe", "--project", str(root)])
    assert "ERR" in res2.stdout


# ---------------------------------------------------------------------------
# list / graph (M6)
# ---------------------------------------------------------------------------

GEN3_SRC = 'def gen(seed: int) -> dict:\n    """gen."""\n    return {"x": seed}\n'
MID3_SRC = 'def mid(x: int) -> dict:\n    """mid."""\n    return {"y": x + 1}\n'
TAIL3_SRC = 'def tail(y: int) -> dict:\n    """tail."""\n    return {"z": y * 2}\n'


def _make_three_module_project(tmp_path: Path, mid_src: str = MID3_SRC) -> Path:
    runner.invoke(app, ["init", "--target", str(tmp_path)])
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text(GEN3_SRC, encoding="utf-8")
    (src / "b.py").write_text(mid_src, encoding="utf-8")
    (src / "c.py").write_text(TAIL3_SRC, encoding="utf-8")
    runner.invoke(app, ["extract", "--project", str(tmp_path)])
    runner.invoke(app, ["module", "add", "--name", "gen", "--entry", "gen", "--project", str(tmp_path)])
    runner.invoke(app, ["module", "add", "--name", "mid", "--entry", "mid", "--project", str(tmp_path)])
    runner.invoke(app, ["module", "add", "--name", "tail", "--entry", "tail", "--project", str(tmp_path)])
    runner.invoke(app, ["pipe", "add", "gen", "mid", "--project", str(tmp_path)])
    runner.invoke(app, ["pipe", "add", "mid", "tail", "--project", str(tmp_path)])
    return tmp_path


def test_list_no_run(tmp_path: Path) -> None:
    root = _make_runnable_project(tmp_path)
    res = runner.invoke(app, ["list", "--project", str(root)])
    assert res.exit_code == 0, res.stdout
    assert "gen" in res.stdout and "infer" in res.stdout
    assert "Atomic" in res.stdout
    # No run yet -> status dashes.
    assert "--" in res.stdout


def test_list_after_run(tmp_path: Path) -> None:
    root = _make_runnable_project(tmp_path)
    inp = root / "input.json"
    inp.write_text(json.dumps({"seed": 5}), encoding="utf-8")
    runner.invoke(app, ["run", "--input", str(inp), "--project", str(root)])
    res = runner.invoke(app, ["list", "--project", str(root)])
    assert res.exit_code == 0, res.stdout
    assert "OK" in res.stdout
    # I/O values from the run should appear.
    assert "prediction" in res.stdout


def test_list_after_fail(tmp_path: Path) -> None:
    root = _make_runnable_project(tmp_path, infer_src=INFER_RAISE_SRC)
    inp = root / "input.json"
    inp.write_text(json.dumps({"seed": 5}), encoding="utf-8")
    runner.invoke(app, ["run", "--input", str(inp), "--project", str(root)])
    res = runner.invoke(app, ["list", "--project", str(root)])
    assert res.exit_code == 0, res.stdout
    assert "OK" in res.stdout  # gen succeeded
    assert "ERR" in res.stdout  # infer failed


def test_list_not_reached_module(tmp_path: Path) -> None:
    MID_RAISE = 'def mid(x: int) -> dict:\n    """mid."""\n    raise ValueError("boom")\n'
    root = _make_three_module_project(tmp_path, mid_src=MID_RAISE)
    inp = root / "input.json"
    inp.write_text(json.dumps({"seed": 5}), encoding="utf-8")
    runner.invoke(app, ["run", "--input", str(inp), "--project", str(root)])
    res = runner.invoke(app, ["list", "--project", str(root)])
    assert res.exit_code == 0, res.stdout
    assert "OK" in res.stdout  # gen
    assert "ERR" in res.stdout  # mid
    # tail never ran -> dashes.
    assert "tail" in res.stdout


def test_list_with_composite(tmp_path: Path) -> None:
    root = _make_runnable_project(tmp_path)
    runner.invoke(app, ["group", "infer", "--name", "boxed", "--project", str(root)])
    res = runner.invoke(app, ["list", "--project", str(root)])
    assert res.exit_code == 0, res.stdout
    assert "Composite" in res.stdout
    assert "boxed" in res.stdout


def test_graph_single_module(tmp_path: Path) -> None:
    root = _make_runnable_project(tmp_path)
    res = runner.invoke(app, ["graph", "--project", str(root)])
    assert res.exit_code == 0, res.stdout
    assert "gen" in res.stdout and "infer" in res.stdout
    assert "-->" in res.stdout


def test_graph_neighborhood(tmp_path: Path) -> None:
    root = _make_three_module_project(tmp_path)
    res = runner.invoke(app, ["graph", "mid", "--project", str(root)])
    assert res.exit_code == 0, res.stdout
    assert "上游" in res.stdout
    assert "下游" in res.stdout
    assert "gen" in res.stdout  # upstream
    assert "tail" in res.stdout  # downstream


def test_graph_neighborhood_two_hops(tmp_path: Path) -> None:
    root = _make_three_module_project(tmp_path)
    # From gen, 2 hops downstream reaches tail via mid.
    res = runner.invoke(app, ["graph", "gen", "--hops", "2", "--project", str(root)])
    assert res.exit_code == 0, res.stdout
    assert "tail" in res.stdout
    assert "2 跳" in res.stdout
    # The full chain through the intermediate must be rendered.
    assert "[mid] --> [tail]" in res.stdout


def test_graph_nonexistent_module(tmp_path: Path) -> None:
    root = _make_runnable_project(tmp_path)
    res = runner.invoke(app, ["graph", "nope", "--project", str(root)])
    assert res.exit_code != 0


def test_graph_fold_to_index(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--target", str(tmp_path)])
    src = tmp_path / "src"
    src.mkdir()
    # Create 16 modules to exceed the default fold threshold (15).
    for i in range(16):
        (src / f"m{i}.py").write_text(
            f"def f{i}() -> dict:\n    \"\"\"m{i}.\"\"\"\n    return {{\"v\": {i}}}\n",
            encoding="utf-8",
        )
    runner.invoke(app, ["extract", "--project", str(tmp_path)])
    for i in range(16):
        runner.invoke(app, ["module", "add", "--name", f"mod{i}", "--entry", f"f{i}", "--project", str(tmp_path)])
    res = runner.invoke(app, ["graph", "--project", str(tmp_path)])
    assert res.exit_code == 0, res.stdout
    assert "折叠" in res.stdout or "索引" in res.stdout


def test_graph_composite_internal(tmp_path: Path) -> None:
    root = _make_runnable_project(tmp_path)
    runner.invoke(app, ["group", "infer", "--name", "boxed", "--project", str(root)])
    res = runner.invoke(app, ["graph", "boxed", "--project", str(root)])
    assert res.exit_code == 0, res.stdout
    assert "内部结构" in res.stdout
    assert "infer" in res.stdout


def test_list_graph_help(tmp_path: Path) -> None:
    for cmd in ["list", "graph"]:
        res = runner.invoke(app, [cmd, "--help"])
        assert res.exit_code == 0
        assert "--project" in res.stdout
