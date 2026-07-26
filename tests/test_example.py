"""End-to-end integration test for the examples/pipeline demo.

Runs the bootstrap script (demo.py) in a clean temp copy and asserts a
successful run with snapshot artifacts. This is the M6 acceptance gate.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

EXAMPLE_DIR = Path(__file__).resolve().parent.parent / "examples" / "pipeline"


def _copy_example(dst: Path) -> None:
    shutil.copytree(
        EXAMPLE_DIR,
        dst,
        ignore=shutil.ignore_patterns(".sfa", "__pycache__", "*.pyc"),
    )


def test_example_demo_end_to_end(tmp_path: Path) -> None:
    if not EXAMPLE_DIR.is_dir():
        raise AssertionError(f"示例目录不存在：{EXAMPLE_DIR}")

    project = tmp_path / "pipeline"
    _copy_example(project)

    result = subprocess.run(
        [sys.executable, str(project / "demo.py")],
        cwd=str(project),
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        raise AssertionError(
            f"demo.py 失败（退出码 {result.returncode}）\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    snapshots_dir = project / ".sfa" / "snapshots"
    run_dirs = [p for p in snapshots_dir.iterdir() if p.is_dir() and not p.name.startswith(".")]
    assert len(run_dirs) == 1, f"期望 1 个运行目录，得到 {len(run_dirs)}"

    run_dir = run_dirs[0]
    assert (run_dir / "run.json").is_file()
    for module in ("loader", "featurizer", "scorer", "positive", "negative"):
        assert (run_dir / f"{module}.json").is_file(), f"缺少快照：{module}.json"

    # The run should have succeeded.
    import json

    manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert manifest["overall_status"] == "success"
    assert len(manifest["modules"]) == 5


def test_example_demo_is_reproducible(tmp_path: Path) -> None:
    """The demo must run successfully twice in the same project copy."""
    if not EXAMPLE_DIR.is_dir():
        raise AssertionError(f"示例目录不存在：{EXAMPLE_DIR}")

    project = tmp_path / "pipeline"
    _copy_example(project)

    def _run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(project / "demo.py")],
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=120,
        )

    first = _run()
    assert first.returncode == 0, (
        f"第一次运行失败\nstdout:\n{first.stdout}\nstderr:\n{first.stderr}"
    )
    second = _run()
    assert second.returncode == 0, (
        f"第二次运行失败\nstdout:\n{second.stdout}\nstderr:\n{second.stderr}"
    )

    import json

    snapshots_dir = project / ".sfa" / "snapshots"
    run_dirs = [
        p for p in snapshots_dir.iterdir() if p.is_dir() and not p.name.startswith(".")
    ]
    assert run_dirs, "期望至少一个运行目录"
    latest = max(run_dirs, key=lambda p: p.stat().st_mtime)
    manifest = json.loads((latest / "run.json").read_text(encoding="utf-8"))
    assert manifest["overall_status"] == "success"
    assert len(manifest["modules"]) == 5
