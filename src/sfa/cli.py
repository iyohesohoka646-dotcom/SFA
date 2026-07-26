"""SFA command-line interface (Typer).

M1 implements `init` and `extract`.  M2 implements `module`, `pipe`,
`group`, `ungroup` and `drill`.  Remaining milestone commands are
registered as placeholders so `sfa --help` shows the full intended surface.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from . import __version__
from .config import SFAError
from .view import one_line as _one_line

app = typer.Typer(
    name="sfa",
    help="Semantic Flow Architecture: design the data-flow graph, AI fills the implementation.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"sfa {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        None, "--version", callback=_version_callback, is_eager=True, help="Show version and exit."
    ),
) -> None:
    """SFA — structure-centric programming with AI as executor."""


# ---------------------------------------------------------------------------
# Implemented commands (M1)
# ---------------------------------------------------------------------------


@app.command()
def init(
    target: Path = typer.Option(
        Path("."), "--target", "-t", help="Directory to initialize (default: current dir)."
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite existing files."),
) -> None:
    """Create the .sfa/ metadata structure and sfa.yml config template."""
    from . import init as init_mod

    root = init_mod.init_project(target, force=force)
    typer.echo(f"已初始化 SFA 项目：{root}")
    typer.echo(f"  - 元数据目录：{root / '.sfa'}")
    typer.echo(f"  - 配置文件：{root / 'sfa.yml'}")
    typer.echo("下一步：编辑 sfa.yml 设置 source_dir，然后运行 `sfa extract`。")


@app.command()
def extract(
    project: Path = typer.Option(
        None, "--project", "-p", help="Project root (default: auto-detected)."
    ),
) -> None:
    """Parse source_dir with tree-sitter and write .sfa/elements.json."""
    from . import extract as extract_mod

    try:
        doc, out = extract_mod.extract(project)
    except SFAError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    typer.echo(f"已提取 {len(doc['elements'])} 个元素 -> {out}")


@app.command()
def clean(
    project: Path = typer.Option(None, "--project", "-p", help="项目根目录（默认自动检测）。"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认，直接清理。"),
) -> None:
    """清空 .sfa/ 元数据（保留 sfa.yml），使项目回到初始状态。"""
    from . import init as init_mod

    try:
        root = _resolve_root(project)
    except SFAError:
        typer.echo("未找到 SFA 项目根目录（缺少 .sfa/ 或 sfa.yml）。请先运行 `sfa init`。")
        raise typer.Exit(code=0)
    if not (yes or typer.confirm("将清空 .sfa/ 下全部生成物（保留 sfa.yml），确认？", default=False)):
        typer.echo("已取消。")
        return
    _run_m2(init_mod.clean_project, root)
    typer.echo(f"已清理 .sfa/ 元数据（保留 sfa.yml）：{root / '.sfa'}")


@app.command()
def status(
    project: Path = typer.Option(None, "--project", "-p", help="项目根目录（默认自动检测）。"),
) -> None:
    """查看项目状态概览（配置/元素/模块/管道/探针/最近运行）。"""
    from . import status as status_mod

    typer.echo(status_mod.render_status(project))


# ---------------------------------------------------------------------------
# Placeholder commands for later milestones
# ---------------------------------------------------------------------------

_PLACEHOLDER = "该命令将在里程碑 {milestone} 提供（当前尚未实现）。"


def _placeholder(milestone: str) -> None:
    typer.echo(_PLACEHOLDER.format(milestone=milestone))
    raise typer.Exit(code=0)


module_app = typer.Typer(help="管理模块（M2）。")
pipe_app = typer.Typer(help="管理管道（M2）。")
probe_app = typer.Typer(help="管理探针（M5）。")
probe_add_app = typer.Typer(help="添加探针。", no_args_is_help=True)


def _resolve_root(project: Path | None) -> Path:
    if project is not None:
        return Path(project).resolve()
    from .config import find_project_root

    return find_project_root()


def _run_m2(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except SFAError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Module commands (M2)
# ---------------------------------------------------------------------------


@module_app.command("add")
def module_add(
    name: str = typer.Option(..., "--name", "-n", help="模块显示名称。"),
    entry: str = typer.Option(..., "--entry", "-e", help="入口元素的 qualified_name（来自 elements.json）。"),
    validation: str = typer.Option(None, "--validation", help="校验级别（strict/lenient/none），默认使用项目配置。"),
    force: bool = typer.Option(False, "--force", help="若模块已存在则重建。"),
    project: Path = typer.Option(None, "--project", "-p", help="项目根目录（默认自动检测）。"),
) -> None:
    """从元素列表创建模块（已存在则跳过，--force 重建）。"""
    from . import module as module_mod
    from . import topology as topo

    root = _resolve_root(project)
    existing = None
    try:
        existing = topo.get_module(root, topo.sanitize_id(name))
    except SFAError:
        existing = None
    mod = _run_m2(module_mod.add_module, root, name, entry, validation, force=force)
    if existing is not None and not force:
        typer.echo(f"模块已存在，跳过：{mod['name']} (id={mod['id']})（使用 --force 重建）")
        return
    label = "已重建模块" if (existing is not None and force) else "已创建模块"
    typer.echo(f"{label}：{mod['name']} (id={mod['id']})")
    typer.echo(f"  - 类型：{mod['type']}")
    typer.echo(f"  - 入口：{mod['entry']}")
    typer.echo(f"  - 拥有元素：{', '.join(mod['owned_elements']) or '(无)'}")
    typer.echo(f"  - 契约：{mod['contract']}")
    typer.echo(f"  - 摘要：{mod['summary']}")


@module_app.command("remove")
def module_remove(
    module_id: str = typer.Argument(..., help="要删除的模块 ID。"),
    project: Path = typer.Option(None, "--project", "-p", help="项目根目录（默认自动检测）。"),
) -> None:
    """删除模块。"""
    from . import module as module_mod

    root = _resolve_root(project)
    mod, removed_pipes, removed_probes = _run_m2(module_mod.remove_module, root, module_id)
    typer.echo(f"已删除模块：{mod['name']} (id={mod['id']})")
    if removed_pipes:
        typer.secho(
            f"  - 连带删除管道：{', '.join(p['id'] for p in removed_pipes)}",
            fg=typer.colors.YELLOW,
        )
    if removed_probes:
        typer.secho(
            f"  - 连带删除探针：{', '.join(p['id'] for p in removed_probes)}",
            fg=typer.colors.YELLOW,
        )


@module_app.command("list")
def module_list(
    project: Path = typer.Option(None, "--project", "-p", help="项目根目录（默认自动检测）。"),
) -> None:
    """列出所有模块。"""
    from . import module as module_mod

    root = _resolve_root(project)
    modules = _run_m2(module_mod.list_modules, root)
    if not modules:
        typer.echo("（暂无模块）")
        return
    typer.echo(f"{'ID':<20} {'名称':<16} {'类型':<10} {'入口':<20} {'父模块'}")
    typer.echo("-" * 80)
    for m in modules:
        entry = m.get("entry", "-")
        parent = m.get("parent") or "-"
        typer.echo(f"{m['id']:<20} {m['name']:<16} {m['type']:<10} {entry:<20} {parent}")


# ---------------------------------------------------------------------------
# Pipe commands (M2)
# ---------------------------------------------------------------------------


@pipe_app.command("add")
def pipe_add(
    source: str = typer.Argument(..., help="源模块 ID。"),
    target: str = typer.Argument(..., help="目标模块 ID。"),
    visibility: str = typer.Option(None, "--visibility", "-v", help="可见性级别（L1-L4），默认使用项目配置。"),
    force: bool = typer.Option(False, "--force", help="若管道已存在则重建。"),
    project: Path = typer.Option(None, "--project", "-p", help="项目根目录（默认自动检测）。"),
) -> None:
    """建立模块间管道（已存在则跳过，--force 重建）。"""
    from . import pipe as pipe_mod
    from . import topology as topo

    root = _resolve_root(project)
    existing = None
    try:
        existing = topo.find_pipe_by_endpoints(root, source, target)
    except SFAError:
        existing = None
    pipe = _run_m2(pipe_mod.add_pipe, root, source, target, visibility, force=force)
    if existing is not None and not force:
        typer.echo(f"管道已存在，跳过：{pipe['id']}（使用 --force 重建）")
        return
    label = "已重建管道" if (existing is not None and force) else "已创建管道"
    typer.echo(f"{label}：{pipe['id']} ({pipe['source']} -> {pipe['target']}, 可见性={pipe['visibility']})")


@pipe_app.command("remove")
def pipe_remove(
    pipe_id: str = typer.Argument(..., help="要删除的管道 ID。"),
    project: Path = typer.Option(None, "--project", "-p", help="项目根目录（默认自动检测）。"),
) -> None:
    """删除管道。"""
    from . import pipe as pipe_mod

    root = _resolve_root(project)
    removed = _run_m2(pipe_mod.remove_pipe, root, pipe_id)
    typer.echo(f"已删除管道：{removed['id']} ({removed['source']} -> {removed['target']})")


@pipe_app.command("list")
def pipe_list(
    project: Path = typer.Option(None, "--project", "-p", help="项目根目录（默认自动检测）。"),
) -> None:
    """列出所有管道。"""
    from . import pipe as pipe_mod

    root = _resolve_root(project)
    pipes = _run_m2(pipe_mod.list_pipes, root)
    if not pipes:
        typer.echo("（暂无管道）")
        return
    typer.echo(f"{'ID':<32} {'源':<16} {'目标':<16} {'可见性':<8} {'父模块'}")
    typer.echo("-" * 88)
    for p in pipes:
        parent = p.get("parent") or "-"
        typer.echo(f"{p['id']:<32} {p['source']:<16} {p['target']:<16} {p['visibility']:<8} {parent}")


# ---------------------------------------------------------------------------
# Composite commands (M2)
# ---------------------------------------------------------------------------


@app.command()
def group(
    child_ids: list[str] = typer.Argument(..., help="要打包的子模块 ID 列表。"),
    name: str = typer.Option(..., "--name", "-n", help="复合模块显示名称。"),
    project: Path = typer.Option(None, "--project", "-p", help="项目根目录（默认自动检测）。"),
) -> None:
    """将若干模块打包为复合模块。"""
    from . import topology as topo

    root = _resolve_root(project)
    composite = _run_m2(topo.group_modules, root, child_ids, name)
    typer.echo(f"已创建复合模块：{composite['name']} (id={composite['id']})")
    typer.echo(f"  - 包含子模块：{', '.join(child_ids)}")


@app.command()
def ungroup(
    composite_id: str = typer.Argument(..., help="要拆封的复合模块 ID。"),
    project: Path = typer.Option(None, "--project", "-p", help="项目根目录（默认自动检测）。"),
) -> None:
    """拆封复合模块。"""
    from . import topology as topo

    root = _resolve_root(project)
    composite, child_ids = _run_m2(topo.ungroup_composite, root, composite_id)
    typer.echo(f"已拆封复合模块：{composite['name']} (id={composite['id']})")
    typer.echo(f"  - 提升子模块：{', '.join(child_ids) or '(无)'}")


@app.command()
def drill(
    composite_id: str = typer.Argument(..., help="要查看的复合模块 ID。"),
    project: Path = typer.Option(None, "--project", "-p", help="项目根目录（默认自动检测）。"),
) -> None:
    """进入复合模块内部视图。"""
    from . import topology as topo

    root = _resolve_root(project)
    mods, pipes = _run_m2(topo.drill_composite, root, composite_id)
    typer.echo(f"复合模块 {composite_id} 内部视图：")
    typer.echo(f"\n子模块 ({len(mods)})：")
    if mods:
        for m in mods:
            typer.echo(f"  - {m['id']:<20} {m['name']:<16} {m['type']}")
    else:
        typer.echo("  (无)")
    typer.echo(f"\n内部管道 ({len(pipes)})：")
    if pipes:
        for p in pipes:
            typer.echo(f"  - {p['id']:<32} {p['source']} -> {p['target']} (L={p['visibility']})")
    else:
        typer.echo("  (无)")


@app.command()
def generate(
    module_id: str = typer.Argument(..., help="要生成代码的模块 ID。"),
    project: Path = typer.Option(None, "--project", "-p", help="项目根目录（默认自动检测）。"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认，直接接受 diff。"),
) -> None:
    """为模块生成实现代码（M3）。"""
    from . import generate as generate_mod

    root = _resolve_root(project)
    plan = _run_m2(generate_mod.prepare_generation, root, module_id)

    if not plan["diff"].strip():
        typer.echo("生成内容与现有代码一致，无变更。")
        return

    _print_diff(plan["diff"])
    _print_warnings(plan["warnings"])

    if not (yes or typer.confirm("接受此 diff？", default=False)):
        typer.echo("已丢弃生成结果。")
        return

    history_path = _run_m2(generate_mod.apply_generation, root, plan)
    typer.echo(f"已应用 diff -> {plan['file_path']}")
    typer.echo(f"  - 历史版本：{history_path}")


@app.command()
def rollback(
    module_id: str = typer.Argument(..., help="要回滚的模块 ID。"),
    version: str = typer.Option(None, "--version", help="指定历史版本文件名（如 v20260722T...）。省略则交互选择。"),
    project: Path = typer.Option(None, "--project", "-p", help="项目根目录（默认自动检测）。"),
) -> None:
    """回滚模块代码到历史版本（M3）。"""
    from . import history as history_mod

    root = _resolve_root(project)
    versions = _run_m2(history_mod.list_versions, root, module_id)
    if not versions:
        typer.echo(f"（模块 {module_id} 无历史版本）")
        return

    if version is None:
        typer.echo(f"模块 {module_id} 的历史版本：")
        for i, v in enumerate(versions, start=1):
            typer.echo(f"  [{i}] {v['filename']}")
        choice = typer.prompt("选择要恢复的版本编号", default="1")
        try:
            idx = int(choice)
        except ValueError:
            typer.secho("无效的编号。", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        if idx < 1 or idx > len(versions):
            typer.secho("编号超出范围。", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        chosen = versions[idx - 1]["filename"]
    else:
        filenames = [v["filename"] for v in versions]
        if version not in filenames:
            typer.secho(
                f"版本 {version} 不存在。可用：{', '.join(filenames)}",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=1)
        chosen = version

    if not typer.confirm(f"将用 {chosen} 覆盖当前文件，确认恢复？", default=False):
        typer.echo("已取消。")
        return

    target = _run_m2(history_mod.restore_version, root, module_id, chosen)
    typer.echo(f"已恢复 {chosen} -> {target}")


def _print_diff(diff_text: str) -> None:
    for line in diff_text.splitlines(keepends=True):
        if line.startswith("+") and not line.startswith("+++"):
            typer.secho(line, fg=typer.colors.GREEN, nl=False)
        elif line.startswith("-") and not line.startswith("---"):
            typer.secho(line, fg=typer.colors.RED, nl=False)
        elif line.startswith("@@"):
            typer.secho(line, fg=typer.colors.CYAN, nl=False)
        else:
            typer.echo(line, nl=False)


def _print_warnings(warnings: list[str]) -> None:
    for w in warnings:
        typer.secho(f"[警告] {w}", fg=typer.colors.YELLOW, err=True)


# ---------------------------------------------------------------------------
# observe helpers (M4)
# ---------------------------------------------------------------------------


def _print_probe_result(probe_result: dict[str, Any]) -> None:
    ptype = probe_result.get("type")
    pid = probe_result.get("probe_id", "-")
    pipe = probe_result.get("pipe", "-")
    source = probe_result.get("source", "-")
    if probe_result.get("status") == "error" or probe_result.get("status") == "orphan":
        err = probe_result.get("error", "未知错误")
        typer.secho(f"  [ERR] {pid} 源→{pipe}: {err}", fg=typer.colors.RED)
        return
    if ptype == "router":
        branch = probe_result.get("branch", "-")
        target = probe_result.get("branch_target", "-")
        cond_res = probe_result.get("condition_result", "-")
        typer.echo(f"  [ROUTE] {pid} 源→{pipe}: 选中 {branch}/{target} (条件={cond_res})")
    elif ptype == "assertion":
        if probe_result.get("passed"):
            typer.echo(f"  [PASS] {pid} 源→{pipe}: {probe_result.get('condition', '')}")
        else:
            msg = probe_result.get("message", "断言失败")
            typer.secho(f"  [FAIL] {pid} 源→{pipe}: {msg}", fg=typer.colors.YELLOW)
    else:
        typer.echo(f"  [?] {pid} 源→{pipe}: {probe_result}")


def _print_run_summary(root: Path, run_id: str, manifest: dict, snap_mod) -> None:
    typer.echo(f"运行 {run_id}（{manifest['overall_status']}）")
    for rec in manifest["modules"]:
        status = rec["status"]
        marker = "OK " if status == "success" else "ERR"
        color = typer.colors.GREEN if status == "success" else typer.colors.RED
        inp = out = "-"
        try:
            snap_data = snap_mod.read_snapshot(root, run_id, rec["id"])
            inp = _one_line(snap_data.get("input"))
            out = _one_line(snap_data.get("output"))
        except SFAError:
            pass
        typer.secho(marker, fg=color, nl=False)
        typer.echo(
            f" {rec['id']:<20} 输入={inp}  输出={out}  {rec.get('duration_ms', 0)}ms"
        )
        for w in rec.get("warnings", []) or []:
            typer.secho(f"    [警告] {w}", fg=typer.colors.YELLOW)

    probes = manifest.get("probes", [])
    if probes:
        typer.echo(f"\n探针 ({len(probes)})：")
        for pr in probes:
            _print_probe_result(pr)


def _print_module_detail(
    root: Path, run_id: str, module_id: str, snap_mod, manifest: dict
) -> None:
    try:
        data = snap_mod.read_snapshot(root, run_id, module_id)
    except SFAError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    typer.echo(f"模块：{data.get('module')}")
    typer.echo(f"运行：{data.get('run_id')}")
    typer.echo(f"时间：{data.get('timestamp')}")
    typer.echo(f"耗时：{data.get('duration_ms')}ms")
    typer.echo(f"状态：{data.get('status')}")
    typer.echo(f"契约版本：{data.get('contract_version_hash')}")
    typer.echo("输入：")
    typer.echo(json.dumps(data.get("input"), ensure_ascii=False, indent=2))
    typer.echo("输出：")
    typer.echo(json.dumps(data.get("output"), ensure_ascii=False, indent=2))
    if data.get("error"):
        typer.secho("错误：", fg=typer.colors.RED)
        typer.echo(data["error"])

    module_probes = [
        pr for pr in manifest.get("probes", []) if pr.get("source") == module_id
    ]
    if module_probes:
        typer.echo(f"\n探针 ({len(module_probes)})：")
        for pr in module_probes:
            _print_probe_result(pr)


@app.command()
def run(
    project: Path = typer.Option(None, "--project", "-p", help="项目根目录（默认自动检测）。"),
    input_file: Path = typer.Option(
        None, "--input", "-i", help="初始输入 JSON 文件（根模块/未被上游覆盖参数的来源）。"
    ),
) -> None:
    """按拓扑执行管道并记录快照（M4）。"""
    from . import execute as execute_mod
    from . import snapshot as snap_mod
    from . import topology as topo_mod

    root = _resolve_root(project)
    atomics = [m for m in topo_mod.list_modules(root) if m.get("type") == "atomic"]
    if not atomics:
        typer.echo("无原子模块可执行。请先用 `sfa module add` 创建模块。")
        raise typer.Exit(code=0)

    initial_input: dict = {}
    input_file_str: str | None = None
    if input_file is not None:
        input_file_str = str(input_file)
        if not input_file.is_file():
            typer.secho(f"输入文件不存在：{input_file}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        try:
            initial_input = json.loads(input_file.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError) as exc:
            typer.secho(f"输入文件解析失败：{exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        if not isinstance(initial_input, dict):
            typer.secho("输入文件必须是 JSON 对象（{}）。", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)

    try:
        manifest = execute_mod.run(root, initial_input, input_file=input_file_str)
    except SFAError as exc:
        failed_run_id = snap_mod.read_latest(root)
        if failed_run_id:
            typer.secho(
                f"运行失败：{failed_run_id}（已记录快照与清单）",
                fg=typer.colors.RED,
                err=True,
            )
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        typer.echo("查看详情：sfa observe")
        raise typer.Exit(code=1)

    run_id = manifest["run_id"]
    total_ms = sum(r.get("duration_ms", 0) for r in manifest["modules"])
    n_ok = sum(1 for r in manifest["modules"] if r["status"] == "success")
    n_err = len(manifest["modules"]) - n_ok
    typer.echo(f"运行完成：{run_id}")
    typer.echo(f"状态：{manifest['overall_status']}")
    typer.echo(f"模块数：{len(manifest['modules'])}（成功 {n_ok}，失败 {n_err}）")
    typer.echo(f"耗时：{total_ms}ms")
    typer.echo("查看详情：sfa observe")


@app.command()
def observe(
    module_id: str = typer.Argument(
        None, help="查看指定模块的详细快照（省略则列出运行摘要）。"
    ),
    project: Path = typer.Option(None, "--project", "-p", help="项目根目录（默认自动检测）。"),
    run_id: str = typer.Option(None, "--run", help="指定运行的 run_id（默认最近一次）。"),
) -> None:
    """查看运行快照摘要（M4）。"""
    from . import snapshot as snap_mod

    root = _resolve_root(project)
    if run_id is None:
        run_id = snap_mod.read_latest(root)
    if run_id is None:
        typer.echo("（暂无运行记录）")
        raise typer.Exit(code=0)
    try:
        manifest = snap_mod.read_run_manifest(root, run_id)
    except SFAError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    if module_id is None:
        _print_run_summary(root, run_id, manifest, snap_mod)
    else:
        _print_module_detail(root, run_id, module_id, snap_mod, manifest)


@probe_add_app.command("router")
def probe_add_router(
    pipe_id: str = typer.Argument(..., help="挂载的管道 ID。"),
    condition: str = typer.Option(..., "--condition", "-c", help="条件表达式，如 $output.score > 0.8。"),
    on_true: str = typer.Option(..., "--on-true", help="条件为 true 时的目标模块 ID，必须等于该管道的 target。"),
    on_false: str = typer.Option(..., "--on-false", help="条件为 false 时的替代目标模块 ID。"),
    name: str = typer.Option(..., "--name", "-n", help="探针显示名称。"),
    project: Path = typer.Option(None, "--project", "-p", help="项目根目录（默认自动检测）。"),
) -> None:
    """为指定管道创建路由探针。"""
    from . import probe as probe_mod

    root = _resolve_root(project)
    probe = _run_m2(
        probe_mod.add_router_probe,
        root,
        name,
        pipe_id,
        condition,
        on_true,
        on_false,
    )
    typer.echo(f"已创建路由探针：{probe['id']} (pipe={probe['pipe']}, condition={probe['condition']})")
    typer.echo(f"  - on_true: {probe['on_true']}  |  on_false: {probe['on_false']}")


@probe_add_app.command("assertion")
def probe_add_assertion(
    pipe_id: str = typer.Argument(..., help="挂载的管道 ID。"),
    condition: str = typer.Option(..., "--condition", "-c", help="断言表达式，如 $output[0] <= $output[-1]。"),
    name: str = typer.Option(..., "--name", "-n", help="探针显示名称。"),
    project: Path = typer.Option(None, "--project", "-p", help="项目根目录（默认自动检测）。"),
) -> None:
    """为指定管道创建断言探针。"""
    from . import probe as probe_mod

    root = _resolve_root(project)
    probe = _run_m2(
        probe_mod.add_assertion_probe,
        root,
        name,
        pipe_id,
        condition,
    )
    typer.echo(f"已创建断言探针：{probe['id']} (pipe={probe['pipe']}, condition={probe['condition']})")


@probe_app.command("list")
def probe_list(
    project: Path = typer.Option(None, "--project", "-p", help="项目根目录（默认自动检测）。"),
) -> None:
    """列出所有探针。"""
    from . import probe as probe_mod

    root = _resolve_root(project)
    probes = _run_m2(probe_mod.list_probes, root)
    if not probes:
        typer.echo("（暂无探针）")
        return
    typer.echo(f"{'ID':<20} {'名称':<20} {'类型':<10} {'管道':<24} {'条件'}")
    typer.echo("-" * 96)
    for p in probes:
        cond = p.get("condition", "-")
        typer.echo(
            f"{p['id']:<20} {p.get('name', ''):<20} {p['type']:<10} "
            f"{p.get('pipe', ''):<24} {cond}"
        )


@probe_app.command("remove")
def probe_remove(
    probe_id: str = typer.Argument(..., help="要删除的探针 ID。"),
    project: Path = typer.Option(None, "--project", "-p", help="项目根目录（默认自动检测）。"),
) -> None:
    """删除探针。"""
    from . import probe as probe_mod

    root = _resolve_root(project)
    removed = _run_m2(probe_mod.remove_probe, root, probe_id)
    typer.echo(f"已删除探针：{removed['id']} ({removed['name']})")


@app.command(name="list")
def list_modules(
    project: Path = typer.Option(None, "--project", "-p", help="项目根目录（默认自动检测）。"),
) -> None:
    """以表格展示所有模块（M6）。"""
    from . import view as view_mod

    root = _resolve_root(project)
    output = _run_m2(view_mod.render_module_list, root)
    typer.echo(output)


@app.command()
def graph(
    module_id: str = typer.Argument(
        None, help="查看指定模块的邻域子图（省略则展示顶层完整数据流图）。"
    ),
    hops: int = typer.Option(2, "--hops", help="邻域跳数（默认 2）。"),
    project: Path = typer.Option(None, "--project", "-p", help="项目根目录（默认自动检测）。"),
) -> None:
    """以 ASCII 图展示数据流（M6）。"""
    from . import view as view_mod

    root = _resolve_root(project)
    output = _run_m2(view_mod.render_graph, root, module_id, hops)
    typer.echo(output)


app.add_typer(module_app, name="module")
app.add_typer(pipe_app, name="pipe")
probe_app.add_typer(probe_add_app, name="add")
app.add_typer(probe_app, name="probe")


if __name__ == "__main__":
    app()
