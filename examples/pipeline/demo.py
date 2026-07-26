#!/usr/bin/env python3
"""SFA 示例项目一键引导脚本。

依次调用 sfa CLI 从零构建 .sfa/ 元数据、连接管道、挂载探针、运行并观测。
脚本可重复运行：每次先用 `sfa clean` 重置 .sfa/ 生成物（保留 sfa.yml），
因此无需手动删除 .sfa/。

用法：
    cd examples/pipeline
    python demo.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent


def _sfa_cmd() -> list[str]:
    """Prefer the installed `sfa` executable; fall back to `python -m sfa`."""
    sfa_exe = shutil.which("sfa")
    if sfa_exe:
        return [sfa_exe]
    return [sys.executable, "-m", "sfa"]


SFA = _sfa_cmd()


def run(*args: str, use_project: bool = True) -> None:
    cmd = SFA + list(args)
    if use_project:
        cmd += ["--project", str(PROJECT)]
    print(f"\n$ sfa {' '.join(args)}")
    print("-" * 60)
    result = subprocess.run(cmd, cwd=str(PROJECT))
    if result.returncode != 0:
        print(f"\n命令失败（退出码 {result.returncode}），中止。", file=sys.stderr)
        sys.exit(result.returncode)


def main() -> None:
    print("=" * 60)
    print("SFA 示例：数据处理流水线")
    print(f"项目目录：{PROJECT}")
    print("=" * 60)

    # --- M1: 初始化 + 重置 + 提取 ---
    # init 幂等地创建脚手架与 sfa.yml；clean 清空 .sfa/ 生成物（保留 sfa.yml），
    # 保证本脚本可重复运行而不残留旧模块/管道/探针/快照。
    run("init", "--target", str(PROJECT), use_project=False)
    run("clean", "--yes")
    run("extract")

    # --- M2: 定义模块 ---
    run("module", "add", "--name", "loader", "--entry", "load_data")
    run("module", "add", "--name", "featurizer", "--entry", "extract_features")
    run("module", "add", "--name", "scorer", "--entry", "score")
    run("module", "add", "--name", "positive", "--entry", "branch_pos")
    run("module", "add", "--name", "negative", "--entry", "branch_neg")

    # --- M2: 连接管道 ---
    run("pipe", "add", "loader", "featurizer")
    run("pipe", "add", "featurizer", "scorer")
    run("pipe", "add", "scorer", "positive")
    run("pipe", "add", "scorer", "negative")

    # --- M5: 挂载探针 ---
    run(
        "probe", "add", "assertion",
        "pipe_scorer_positive",
        "--condition", "$output.score >= 0.5",
        "--name", "score_threshold",
    )
    run(
        "probe", "add", "router",
        "pipe_scorer_positive",
        "--condition", "$output.score >= 0.8",
        "--on-true", "positive",
        "--on-false", "negative",
        "--name", "high_confidence_router",
    )

    # --- M4: 运行 + 快照 ---
    run("run", "--input", str(PROJECT / "input.json"))

    # --- M4: 观测 ---
    run("observe")
    run("observe", "scorer")

    # --- M6: 索引与可视化 ---
    run("list")
    run("graph")
    run("graph", "scorer")

    print("\n" + "=" * 60)
    print("示例运行完成。")
    print("提示：运行 `sfa observe positive` 或 `sfa graph negative` 继续探索。")
    print("=" * 60)


if __name__ == "__main__":
    main()
