"""Execution engine: run the data-flow pipeline and record snapshots.

The execution graph is built from ``pipeline.yml``: every *atomic* module is
a node and every pipe is a directed edge (source -> target).  Composite
modules are M2 editing units and never enter the execution layer.

Data flows by *parameter-name binding*: each upstream module's output (which
must be a dict) is merged with the initial input and unpacked into the
downstream entry function's parameters by name — the structured form of
``b(**a_output)``.  Initial input for root/uncovered parameters comes from
``sfa run --input <file.json>``.

Each module is validated against its contract (strict/lenient/none) at both
its input and output boundaries, executed in topological order, and its
input/output/duration/status persisted as a snapshot.  Execution is
fail-fast: the first failing module records an error snapshot, the run
manifest is finalised with ``overall_status=error`` and a ``ModuleRunError``
( carrying the module name, input-snapshot path and traceback) is raised.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import importlib.util
import inspect
import json
import logging
import sys
import time
import traceback
from pathlib import Path
from typing import Any
from uuid import uuid4

from . import probe as probe_mod
from . import snapshot as snap
from . import topology
from .config import SFAError, find_project_root, load_config, sfa_dir
from .contract import read_contract, validate_against_schema

_log = logging.getLogger("sfa.execute")

_SELF_PARAMS = ("self", "cls")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class ModuleRunError(SFAError):
    """A module failed during execution.

    Carries the information needed to append a record to the run manifest.
    The message always includes the module name, the input-snapshot path and
    the error stack (per the fail-fast contract).
    """

    def __init__(
        self,
        message: str,
        module_id: str,
        duration_ms: int,
        snapshot_filename: str,
    ) -> None:
        super().__init__(message)
        self.module_id = module_id
        self.duration_ms = duration_ms
        self.snapshot_filename = snapshot_filename


def run(
    root: Path,
    initial_input: dict[str, Any] | None = None,
    *,
    input_file: str | None = None,
) -> dict[str, Any]:
    """Execute the pipeline and return the run manifest dict.

    *initial_input* is merged under every module's upstream outputs (upstream
    wins on key conflicts).  *input_file* is recorded in the manifest for
    traceability only.
    """
    root = find_project_root(root)
    initial_input = dict(initial_input or {})
    cfg = load_config(root)
    source_dir = str(cfg.get("source_dir", "src"))

    atomics, pipes, by_id = _build_graph(root)
    if not atomics:
        raise SFAError(
            "无原子模块可执行。\n"
            "可操作建议：先执行 `sfa module add` 创建模块，并连接管道后重试。"
        )
    order = _topo_sort(atomics, pipes)

    run_id = uuid4().hex
    start_time = _now_iso()
    inbound_by_target = _index_inbound(pipes)
    probes_by_source, probe_results = probe_mod.load_probes_by_source(root)

    outputs: dict[str, Any] = {}
    module_records: list[dict[str, Any]] = []
    overall_status = "success"
    pending_error: ModuleRunError | None = None

    for module_id in order:
        module = by_id[module_id]
        try:
            record, output = _execute_module(
                root,
                module,
                run_id,
                inbound_by_target.get(module_id, []),
                outputs,
                initial_input,
                cfg,
                source_dir,
                probes_by_source,
                probe_results,
            )
        except ModuleRunError as mre:
            module_records.append(
                {
                    "id": mre.module_id,
                    "status": "error",
                    "duration_ms": mre.duration_ms,
                    "snapshot": mre.snapshot_filename,
                    "error": True,
                }
            )
            overall_status = "error"
            pending_error = mre
            break
        module_records.append(record)
        outputs[module_id] = output

    end_time = _now_iso()
    manifest = {
        "run_id": run_id,
        "start_time": start_time,
        "end_time": end_time,
        "overall_status": overall_status,
        "execution_order": order,
        "modules": module_records,
        "probes": probe_results,
        "input_file": input_file,
    }
    snap.write_run_manifest(root, run_id, manifest)
    snap.write_latest(root, run_id)

    if pending_error is not None:
        raise pending_error
    return manifest


# ---------------------------------------------------------------------------
# Graph construction & topological sort
# ---------------------------------------------------------------------------


def _build_graph(
    root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Return ``(atomic_modules, pipes, atomics_by_id)`` from pipeline.yml.

    Raises SFAError if any pipe references a missing or composite endpoint.
    """
    data = topology.load_pipeline(root)
    modules = data.get("modules", [])
    pipes = data.get("pipes", [])
    atomics = [m for m in modules if m.get("type") == "atomic"]
    by_id = {m["id"]: m for m in atomics}
    all_by_id = {m["id"]: m for m in modules}
    for p in pipes:
        for end in ("source", "target"):
            eid = p[end]
            if eid in by_id:
                continue
            mod = all_by_id.get(eid)
            if mod is not None and mod.get("type") == "composite":
                raise SFAError(
                    f"管道 {p['id']} 的端点 {eid} 是复合模块，不可执行。\n"
                    f"相关文件：{root / '.sfa' / 'pipeline.yml'}\n"
                    "可操作建议：复合模块不参与执行，请指定其内部的具体子模块 ID，"
                    f"或执行 `sfa pipe remove {p['id']}` 重建管道。"
                )
            raise SFAError(
                f"管道 {p['id']} 引用了不存在的模块 {eid}。\n"
                f"相关文件：{root / '.sfa' / 'pipeline.yml'}\n"
                f"可操作建议：执行 `sfa pipe remove {p['id']}` 重建管道。"
            )
    return atomics, pipes, by_id


def _topo_sort(
    atomics: list[dict[str, Any]], pipes: list[dict[str, Any]]
) -> list[str]:
    """Kahn topological sort.  Ties break by pipeline.yml declaration order.

    Raises SFAError listing the modules participating in a cycle.
    """
    ids = [m["id"] for m in atomics]
    rank = {mid: i for i, mid in enumerate(ids)}
    indeg = {mid: 0 for mid in ids}
    adj: dict[str, list[str]] = {mid: [] for mid in ids}
    for p in pipes:
        s, t = p["source"], p["target"]
        adj[s].append(t)
        indeg[t] += 1

    available = sorted((mid for mid in ids if indeg[mid] == 0), key=lambda x: rank[x])
    order: list[str] = []
    while available:
        n = available.pop(0)
        order.append(n)
        for t in adj[n]:
            indeg[t] -= 1
            if indeg[t] == 0:
                available.append(t)
        available.sort(key=lambda x: rank[x])

    if len(order) != len(ids):
        cyclic = sorted((set(ids) - set(order)), key=lambda x: rank[x])
        raise SFAError(
            f"检测到循环依赖，无法拓扑排序。参与环的模块：{', '.join(cyclic)}\n"
            f"可操作建议：检查 pipeline.yml 中的管道，移除形成环的管道（`sfa pipe remove <id>`）。"
        )
    return order


def _index_inbound(pipes: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Map each target module id to its inbound pipes (in declaration order)."""
    inbound: dict[str, list[dict[str, Any]]] = {}
    for p in pipes:
        inbound.setdefault(p["target"], []).append(p)
    return inbound


# ---------------------------------------------------------------------------
# Single-module execution
# ---------------------------------------------------------------------------


def _execute_module(
    root: Path,
    module: dict[str, Any],
    run_id: str,
    inbound_pipes: list[dict[str, Any]],
    outputs: dict[str, Any],
    initial_input: dict[str, Any],
    cfg: dict[str, Any],
    source_dir: str,
    probes_by_source: dict[str, list[dict[str, Any]]],
    probe_results: list[dict[str, Any]],
) -> tuple[dict[str, Any], Any]:
    """Execute one module: bind kwargs, validate, invoke, snapshot, probes.

    Returns ``(record, output)`` on success.  On failure writes an error
    snapshot and raises ``ModuleRunError``.
    """
    module_id = module["id"]
    try:
        contract = read_contract(root, module_id)
    except SFAError as exc:
        _write_error_snapshot(root, run_id, module_id, {}, None, str(exc), 0, None)
        raise ModuleRunError(str(exc), module_id, 0, f"{module_id}.json") from exc
    contract_hash = contract.get("version_hash")
    level = _validation_level(module, cfg)

    # Load callable and resolve its parameter shape.
    try:
        callable_obj = _load_callable(root, module, run_id, source_dir)
    except SFAError as exc:
        _write_error_snapshot(root, run_id, module_id, {}, None, str(exc), 0, contract_hash)
        raise ModuleRunError(str(exc), module_id, 0, f"{module_id}.json") from exc

    named_params, accepts_arbitrary = _resolve_params(callable_obj)

    # Bind upstream outputs + initial input to entry parameters.
    try:
        kwargs = _build_kwargs(
            inbound_pipes, outputs, initial_input, named_params, accepts_arbitrary, module_id
        )
    except SFAError as exc:
        _write_error_snapshot(root, run_id, module_id, {}, None, str(exc), 0, contract_hash)
        raise ModuleRunError(str(exc), module_id, 0, f"{module_id}.json") from exc

    warnings: list[str] = []

    # Input contract validation.
    try:
        input_errors = validate_against_schema(kwargs, contract.get("input_schema") or {}, level)
    except SFAError as exc:
        _write_error_snapshot(root, run_id, module_id, kwargs, None, str(exc), 0, contract_hash)
        raise ModuleRunError(str(exc), module_id, 0, f"{module_id}.json") from exc
    if input_errors:
        if level == "strict":
            msg = _validation_fail_message(module_id, "输入", input_errors, run_id)
            _write_error_snapshot(root, run_id, module_id, kwargs, None, msg, 0, contract_hash)
            raise ModuleRunError(msg, module_id, 0, f"{module_id}.json")
        if level == "lenient":
            wmsg = f"输入校验警告：{'; '.join(input_errors)}"
            warnings.append(wmsg)
            _log.warning("模块 %s %s", module_id, wmsg)

    # Execute.
    t0 = time.perf_counter()
    try:
        output = _invoke(callable_obj, kwargs)
    except Exception:
        duration = round((time.perf_counter() - t0) * 1000)
        tb = traceback.format_exc()
        _write_error_snapshot(root, run_id, module_id, kwargs, None, tb, duration, contract_hash)
        raise ModuleRunError(
            _exec_fail_message(module_id, run_id, tb), module_id, duration, f"{module_id}.json"
        )
    duration = round((time.perf_counter() - t0) * 1000)

    # Output contract validation.
    try:
        output_errors = validate_against_schema(
            output, contract.get("output_schema") or {}, level
        )
    except SFAError as exc:
        _write_error_snapshot(root, run_id, module_id, kwargs, output, str(exc), duration, contract_hash)
        raise ModuleRunError(str(exc), module_id, duration, f"{module_id}.json") from exc
    if output_errors:
        if level == "strict":
            msg = _validation_fail_message(module_id, "输出", output_errors, run_id)
            _write_error_snapshot(root, run_id, module_id, kwargs, output, msg, duration, contract_hash)
            raise ModuleRunError(msg, module_id, duration, f"{module_id}.json")
        if level == "lenient":
            wmsg = f"输出校验警告：{'; '.join(output_errors)}"
            warnings.append(wmsg)
            _log.warning("模块 %s %s", module_id, wmsg)

    snap_data = {
        "module": module_id,
        "run_id": run_id,
        "timestamp": _now_iso(),
        "duration_ms": duration,
        "status": "success",
        "input": kwargs,
        "output": output,
        "error": None,
        "contract_version_hash": contract_hash,
    }
    snap.write_snapshot(root, run_id, module_id, snap_data)
    record: dict[str, Any] = {
        "id": module_id,
        "status": "success",
        "duration_ms": duration,
        "snapshot": f"{module_id}.json",
    }
    if warnings:
        record["warnings"] = warnings

    # Evaluate probes attached to this module's outbound pipes.
    _eval_probes_for_source(
        module_id, output, probes_by_source, probe_results, record
    )

    return record, output


# ---------------------------------------------------------------------------
# Module loading & entry resolution
# ---------------------------------------------------------------------------


def _load_callable(
    root: Path, module: dict[str, Any], run_id: str, source_dir: str
) -> Any:
    """Import the module's source file and resolve its entry callable.

    The file is loaded under a unique synthetic name and is *not* inserted
    into ``sys.modules`` (avoids cross-run name clashes and repeated
    module-level side effects).  ``source_dir`` is temporarily prepended to
    ``sys.path`` so intra-source imports resolve.
    """
    file_path = (root / module["path"]).resolve()
    project_root = root.resolve()
    if not file_path.is_relative_to(project_root):
        raise SFAError(
            f"模块源文件路径越界：{file_path}\n"
            f"相关模块：{module['id']}\n"
            "可操作建议：检查 pipeline.yml 中模块的 path，确保其位于项目目录内。"
        )
    if not file_path.is_file():
        raise SFAError(
            f"模块源文件不存在：{file_path}\n"
            f"相关模块：{module['id']}\n"
            "可操作建议：检查 sfa.yml 的 source_dir 与模块 path，或恢复源文件。"
        )

    uniq = f"_sfa_runtime_{module['id']}_{run_id}"
    spec = importlib.util.spec_from_file_location(uniq, file_path)
    if spec is None or spec.loader is None:
        raise SFAError(
            f"无法加载模块源文件：{file_path}\n"
            f"相关模块：{module['id']}"
        )
    py_mod = importlib.util.module_from_spec(spec)

    src_abs = str((root / source_dir).resolve())
    path_added = False
    if src_abs not in sys.path:
        sys.path.insert(0, src_abs)
        path_added = True
    try:
        spec.loader.exec_module(py_mod)
    finally:
        if path_added and src_abs in sys.path:
            sys.path.remove(src_abs)

    return _resolve_entry(py_mod, module)


def _resolve_entry(py_mod: Any, module: dict[str, Any]) -> Any:
    """Resolve the entry callable from the loaded module.

    For a ``method`` entry (``Class.method``) the class is instantiated with
    no arguments and the bound method returned.  For a function entry the
    bare attribute is returned.
    """
    entry = module["entry"]
    if module.get("method") == "method":
        parts = entry.split(".")
        if len(parts) != 2:
            raise SFAError(
                f"方法入口格式异常：{entry}\n"
                f"相关模块：{module['id']}\n"
                "可操作建议：重新执行 `sfa extract` 后核对模块 entry。"
            )
        cls_name, meth_name = parts
        try:
            cls = getattr(py_mod, cls_name)
        except AttributeError:
            raise SFAError(
                f"入口类未找到：{cls_name}\n"
                f"相关模块：{module['id']}\n"
                "可操作建议：代码可能已变更，请重新执行 `sfa extract` 后核对 entry。"
            ) from None
        try:
            instance = cls()
        except TypeError as exc:
            raise SFAError(
                f"类 {cls_name} 构造需要参数；M4 仅支持无参构造。\n"
                f"相关模块：{module['id']}\n"
                "可操作建议：为类提供无参构造（或默认参数），或将入口改为模块级函数。"
            ) from exc
        try:
            return getattr(instance, meth_name)
        except AttributeError:
            raise SFAError(
                f"入口方法未找到：{entry}\n"
                f"相关模块：{module['id']}\n"
                "可操作建议：重新执行 `sfa extract` 后核对 entry。"
            ) from None

    name = entry.split(".")[-1]
    try:
        return getattr(py_mod, name)
    except AttributeError:
        raise SFAError(
            f"入口元素未找到：{entry}\n"
            f"相关模块：{module['id']}\n"
            "可操作建议：代码可能已变更，请重新执行 `sfa extract` 后核对 entry。"
        ) from None


def _resolve_params(callable_obj: Any) -> tuple[list[str], bool]:
    """Return ``(named_params, accepts_arbitrary_kwargs)`` for *callable_obj*.

    ``self``/``cls`` and ``*args`` are excluded; ``**kwargs`` sets the
    arbitrary flag so all merged keys are forwarded unfiltered.
    """
    try:
        sig = inspect.signature(callable_obj)
    except (ValueError, TypeError):
        return [], False
    named: list[str] = []
    arbitrary = False
    for pname, param in sig.parameters.items():
        if pname in _SELF_PARAMS:
            continue
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            arbitrary = True
            continue
        if param.kind == inspect.Parameter.VAR_POSITIONAL:
            continue
        named.append(pname)
    return named, arbitrary


# ---------------------------------------------------------------------------
# kwargs binding
# ---------------------------------------------------------------------------


def _build_kwargs(
    inbound_pipes: list[dict[str, Any]],
    outputs: dict[str, Any],
    initial_input: dict[str, Any],
    named_params: list[str],
    accepts_arbitrary: bool,
    module_id: str,
) -> dict[str, Any]:
    """Merge upstream outputs (dicts) with initial input and filter to params.

    Upstream outputs override initial input on key conflicts (live data
    wins).  Multiple upstreams are merged in pipe declaration order.
    """
    upstream_merged: dict[str, Any] = {}
    for pipe in inbound_pipes:
        out = outputs.get(pipe["source"])
        if not isinstance(out, dict):
            raise SFAError(
                f"上游模块 {pipe['source']} 的输出不是字典（得到 {type(out).__name__}），"
                f"无法按参数名绑定到模块 {module_id}。\n"
                "可操作建议：确保上游模块返回字典对象（键名与下游入口参数对应）。"
            )
        upstream_merged.update(out)
    merged = {**initial_input, **upstream_merged}
    if accepts_arbitrary:
        return dict(merged)
    return {k: v for k, v in merged.items() if k in named_params}


# ---------------------------------------------------------------------------
# Invocation
# ---------------------------------------------------------------------------


def _invoke(callable_obj: Any, kwargs: dict[str, Any]) -> Any:
    """Call *callable_obj* with *kwargs*, awaiting coroutines."""
    if inspect.iscoroutinefunction(callable_obj):
        return asyncio.run(callable_obj(**kwargs))
    return callable_obj(**kwargs)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validation_level(module: dict[str, Any], cfg: dict[str, Any]) -> str:
    return str(module.get("validation") or cfg.get("validation", "strict") or "strict")


def _now_iso() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _write_error_snapshot(
    root: Path,
    run_id: str,
    module_id: str,
    input_data: Any,
    output_data: Any,
    error: str,
    duration_ms: int,
    contract_hash: str | None,
) -> None:
    data = {
        "module": module_id,
        "run_id": run_id,
        "timestamp": _now_iso(),
        "duration_ms": duration_ms,
        "status": "error",
        "input": input_data,
        "output": output_data,
        "error": error,
        "contract_version_hash": contract_hash,
    }
    snap.write_snapshot(root, run_id, module_id, data)


def _validation_fail_message(
    module_id: str, direction: str, errors: list[str], run_id: str
) -> str:
    detail = "; ".join(errors[:5])
    return (
        f"模块 {module_id} 的{direction}契约校验失败（运行 {run_id}）。\n"
        f"校验错误：{detail}\n"
        f"可操作建议：检查模块代码与 contract.json 的 {direction}_schema 是否一致，"
        "或调整模块的校验级别（validation: lenient/none）。"
    )


def _exec_fail_message(module_id: str, run_id: str, tb: str) -> str:
    rel = f".sfa/snapshots/{run_id}/{module_id}.json"
    tail = "\n".join(tb.strip().splitlines()[-6:])
    return (
        f"模块 {module_id} 执行失败（运行 {run_id}）。\n"
        f"输入快照：{rel}\n"
        f"错误堆栈：\n{tail}"
    )


def _eval_probes_for_source(
    module_id: str,
    output: Any,
    probes_by_source: dict[str, list[dict[str, Any]]],
    probe_results: list[dict[str, Any]],
    record: dict[str, Any],
) -> None:
    """Evaluate probes attached to *module_id*'s outbound pipes.

    Appends result records to *probe_results* and warnings to *record*.
    Probe failures never stop the run.
    """
    probes = probes_by_source.get(module_id, [])
    if not probes:
        return

    for probe in probes:
        try:
            result = probe_mod.evaluate_probe(probe, output)
        except probe_mod.ProbeEvaluationError as exc:
            result = {
                "probe_id": probe["id"],
                "type": probe.get("type"),
                "pipe": probe.get("pipe"),
                "source": module_id,
                "condition": probe.get("condition"),
                "status": "error",
                "error": str(exc),
            }
        result["source"] = module_id
        probe_results.append(result)

        if result.get("type") == "assertion" and result.get("passed") is False:
            msg = result.get("message", "断言失败")
            record.setdefault("warnings", []).append(msg)
            _log.warning("探针 %s 断言失败：%s", probe["id"], msg)


__all__ = ["run", "ModuleRunError"]
