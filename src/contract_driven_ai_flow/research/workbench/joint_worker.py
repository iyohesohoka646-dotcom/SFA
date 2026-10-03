"""Standalone numerical worker. Inputs are authorized immutable artifact paths.

Loads only the standard-library observation SDK into the selected interpreter;
server/UI dependencies are unnecessary in a scientific environment.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


class Diagnostic(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def decode(value):
    if isinstance(value, dict):
        if value.get("type") == "nonfinite":
            return float(value["value"])
        if value.get("type") == "complex":
            return complex(decode(value["real"]), decode(value["imag"]))
        if value.get("type") == "datetime":
            return value["value"]
        raise Diagnostic(
            "coordinate_metadata_missing", "坐标或单元格包含不可恢复的类型"
        )
    if isinstance(value, str) and "[REDACTED" in value:
        raise Diagnostic("redacted_input", "脱敏后的数据不能产生全量结论")
    return value


def read_input(spec):
    path = Path(spec["path"])
    with path.open("rb") as stream:
        hasher = hashlib.sha256()
        while chunk := stream.read(1024 * 1024):
            hasher.update(chunk)
    if hasher.hexdigest() != spec["sha256"]:
        raise Diagnostic("artifact_changed", "产物内容在计划后发生变化")
    if path.suffix == ".npy":
        import numpy as np

        data = np.load(path, allow_pickle=False, mmap_mode="r")
        if data.dtype.kind not in "biufc":
            raise Diagnostic("numeric_type_required", "此运算要求数值输入")
        if list(data.shape) != spec.get("shape"):
            raise Diagnostic("shape_mismatch", "产物形状与证据记录不一致")
        return data
    if path.suffix == ".arrow":
        import pandas as pd
        import pyarrow as pa
        import pyarrow.ipc as ipc

        with pa.memory_map(str(path), "r") as stream:
            table = ipc.open_file(stream).read_all()
            metadata = table.schema.metadata or {}
            if b"cdaf.coordinates" not in metadata:
                raise Diagnostic(
                    "coordinate_metadata_missing", "历史表格缺少完整坐标，需要重新采集"
                )
            coordinates = json.loads(metadata[b"cdaf.coordinates"])
            columns = [decode(value) for value in coordinates.get("columns", [])]
            index = [decode(value) for value in coordinates.get("index", [])]
            if len(columns) != table.num_columns or len(index) != table.num_rows:
                raise Diagnostic(
                    "coordinate_metadata_missing", "完整坐标长度与表格不一致"
                )
            values = {
                i: [decode(json.loads(cell)) for cell in table.column(i).to_pylist()]
                for i in range(table.num_columns)
            }
        data = pd.DataFrame(values)
        data.columns, data.index = columns, index
        return data
    raise Diagnostic("unsupported_artifact", "未注册完整输入编码")


def output_budget(shape, dtype, maximum):
    if math.prod(shape) * dtype.itemsize + 4096 > maximum:
        raise Diagnostic("result_budget_exceeded", "派生结果超过采集预算")


def check_coordinates(operator, inputs, parameters):
    for spec in inputs.values():
        axes = spec.get("semantics", {}).get("axes", [])
        shape = spec.get("shape") or []
        if len(axes) > len(shape) or any(
            (axis.get("coordinates") and len(axis["coordinates"]) != shape[i])
            or (axis.get("labels") and len(axis["labels"]) != shape[i])
            for i, axis in enumerate(axes)
        ):
            raise Diagnostic(
                "coordinate_shape_mismatch",
                "坐标或标签长度与此数据版本的形状不符；请重新定义",
            )
        if (
            operator != "join"
            and spec.get("semantics", {}).get("mappings", {}).get("coordinate_gaps")
            and parameters.get("alignment") != "positional"
        ):
            raise Diagnostic(
                "coordinate_metadata_missing",
                "派生输入的坐标来源不完整；请补充定义或明确选择按位置计算",
            )
    if (
        operator == "join"
        or len(inputs) < 2
        or parameters.get("alignment") == "positional"
    ):
        return
    left, right = inputs["left"], inputs["right"]
    axes_a, axes_b = left.get("semantics", {}).get("axes", []), right.get(
        "semantics", {}
    ).get("axes", [])

    def coordinates(axes, index):
        return (
            (axes[index].get("coordinates") or axes[index].get("labels"))
            if 0 <= index < len(axes)
            else None
        )

    shape_a, shape_b = left.get("shape") or [], right.get("shape") or []
    ndim = max(len(shape_a), len(shape_b))
    pairs = (
        [(1, 0)]
        if operator == "matmul"
        else [
            (i - (ndim - len(shape_a)), i - (ndim - len(shape_b))) for i in range(ndim)
        ]
    )
    for a, b in pairs:
        if (
            operator == "elementwise"
            and parameters.get("broadcast")
            and (
                a < 0
                or b < 0
                or shape_a[a] != shape_b[b]
                and (shape_a[a] == 1 or shape_b[b] == 1)
            )
        ):
            continue
        ca, cb = coordinates(axes_a, a), coordinates(axes_b, b)
        if bool(ca) != bool(cb):
            raise Diagnostic(
                "coordinate_metadata_missing",
                "一个输入缺少对应坐标；补充定义或明确选择按位置计算",
            )
        if ca and ca != cb:
            raise Diagnostic(
                "coordinate_mismatch",
                "输入坐标顺序不同；请对齐坐标或明确选择按位置计算",
            )


def result_semantics(operator, inputs, parameters, result):
    """Propagate surviving axes, retaining explicit gaps and parent provenance."""
    import copy

    axes_by_role = {
        role: spec.get("semantics", {}).get("axes", []) for role, spec in inputs.items()
    }
    shape = list(result.shape)
    axes, sources, gaps = [], {}, []
    had_coordinates = any(
        axis.get("coordinates") or axis.get("labels")
        for group in axes_by_role.values()
        for axis in group
    )

    def append_axis(role, index, output_index):
        group = axes_by_role[role]
        axis = copy.deepcopy(group[index]) if index < len(group) else {}
        axis["origin"] = "program"
        axes.append(axis)
        sources[str(output_index)] = {"input_role": role, "axis": index}
        if had_coordinates and not axis.get("coordinates") and not axis.get("labels"):
            gaps.append(output_index)

    if operator == "elementwise":
        for i, length in enumerate(shape):
            candidates = [
                (role, i - (len(shape) - len(spec.get("shape") or [])))
                for role, spec in inputs.items()
            ]
            candidates = [
                (role, index)
                for role, index in candidates
                if index >= 0 and inputs[role]["shape"][index] == length
            ]
            role, index = next(
                (
                    (role, index)
                    for role, index in candidates
                    if index < len(axes_by_role[role])
                    and (
                        axes_by_role[role][index].get("coordinates")
                        or axes_by_role[role][index].get("labels")
                    )
                ),
                candidates[0],
            )
            append_axis(role, index, i)
    elif operator == "matmul":
        append_axis("left", 0, 0)
        append_axis("right", 1, 1)
    elif operator == "aggregate":
        ndim = len(inputs["input"].get("shape") or [])
        axis = parameters.get("axis")
        if axis is not None:
            reduced = axis % ndim
            for index in range(ndim):
                if index != reduced:
                    append_axis("input", index, len(axes))
    elif operator == "join":
        from contract_driven_ai_flow.research.agent.privacy import cell

        axes = [
            {
                "coordinates": [cell(v) for v in result.index.tolist()],
                "origin": "program",
            },
            {
                "coordinates": [cell(v) for v in result.columns.tolist()],
                "origin": "program",
            },
        ]
    inherited_gaps = any(
        spec.get("semantics", {}).get("mappings", {}).get("coordinate_gaps")
        for spec in inputs.values()
    )
    if inherited_gaps and shape and parameters.get("alignment") == "positional":
        gaps = sorted(
            set(gaps)
            | {
                i
                for i, axis in enumerate(axes)
                if not axis.get("coordinates") and not axis.get("labels")
            }
        )
    return {
        "protocol_version": 3,
        "logical_key": "",
        "kind": (
            "table"
            if operator == "join"
            else "matrix" if len(shape) >= 2 else "series" if shape else "generic"
        ),
        "axes": axes,
        "origin": "program",
        "accepted": True,
        "mappings": {
            "coordinate_sources": sources,
            "coordinate_gaps": gaps,
            "alignment": parameters.get("alignment", "coordinates"),
        },
    }


def calculate(key, values, parameters, maximum):
    import numpy as np

    if key == "join":
        import pandas as pd

        left, right = values["left"], values["right"]
        if not isinstance(left, pd.DataFrame) or not isinstance(right, pd.DataFrame):
            raise Diagnostic("table_type_required", "连接需要两个表格")
        keys = parameters.get("keys")
        if (
            not isinstance(keys, list)
            or not keys
            or not all(isinstance(key, str) for key in keys)
        ):
            raise Diagnostic("join_keys_required", "请明确选择连接键")
        if any(key not in left.columns or key not in right.columns for key in keys):
            raise Diagnostic("join_key_missing", "连接键不属于两个输入表格")
        if left[keys].isna().any().any() or right[keys].isna().any().any():
            if parameters.get("missing", "error") == "error":
                raise Diagnostic("missing_values", "连接键包含缺失值，请指定处理策略")
        how = parameters.get("how", "inner")
        if how not in ("inner", "left", "right", "outer"):
            raise Diagnostic("invalid_join_mode", "连接方式无效")
        validate = parameters.get("cardinality", "one_to_one")
        if validate not in ("one_to_one", "one_to_many", "many_to_one", "many_to_many"):
            raise Diagnostic("join_cardinality", "请选择连接基数约束")
        counts_a = left.groupby(keys, dropna=False).size()
        counts_b = right.groupby(keys, dropna=False).size()
        pairs = sum(
            int(count) * int(counts_b.get(index, 0))
            for index, count in counts_a.items()
        )
        rows = (
            pairs
            + (len(left) if how in ("left", "outer") else 0)
            + (len(right) if how in ("right", "outer") else 0)
        )
        if rows * (left.shape[1] + right.shape[1]) * 64 + 4096 > maximum:
            raise Diagnostic("result_budget_exceeded", "连接结果超过预算，请缩小范围")
        try:
            return pd.merge(left, right, on=keys, how=how, validate=validate), {}
        except pd.errors.MergeError as error:
            raise Diagnostic("join_cardinality", "输入不符合指定连接基数") from error
    arrays = {}
    for role, data in values.items():
        if not isinstance(data, np.ndarray) or data.dtype.kind not in "biufc":
            raise Diagnostic("numeric_type_required", "此运算要求数值数组")
        missing = parameters.get("missing", "error")
        if missing not in ("error", "propagate", "pairwise"):
            raise Diagnostic("missing_policy_invalid", "缺失值策略无效")
        if missing == "pairwise" and key != "correlation":
            raise Diagnostic("missing_policy_invalid", "配对删除只适用于相关分析")
        if missing == "error" and not np.isfinite(data).all():
            raise Diagnostic("missing_values", "输入包含缺失或无穷值，请指定处理策略")
        arrays[role] = data
    if key == "aggregate":
        data = arrays["input"]
        method = parameters.get("method", "mean")
        if method not in ("mean", "sum", "min", "max", "std", "median"):
            raise Diagnostic("aggregation_method_invalid", "聚合方法无效")
        axis = parameters.get("axis")
        if axis is not None and (
            type(axis) is not int or not -data.ndim <= axis < data.ndim
        ):
            raise Diagnostic("axis_out_of_range", "聚合轴超出维度")
        return np.asarray(getattr(np, method)(data, axis=axis)), {}
    left, right = arrays["left"], arrays["right"]
    if key == "elementwise":
        if not parameters.get("broadcast", False) and left.shape != right.shape:
            raise Diagnostic(
                "shape_mismatch", "逐元素运算默认要求形状相同；可明确开启广播"
            )
        try:
            shape = np.broadcast_shapes(left.shape, right.shape)
        except ValueError as error:
            raise Diagnostic("shape_mismatch", "输入形状不能广播") from error
        operation = parameters.get("operation", "subtract")
        if operation not in ("add", "subtract", "multiply", "divide"):
            raise Diagnostic("operation_invalid", "逐元素运算无效")
        dtype = np.result_type(
            left.dtype, right.dtype, np.float64 if operation == "divide" else left.dtype
        )
        output_budget(shape, dtype, maximum)
        with np.errstate(all="ignore"):
            return getattr(np, operation)(left, right), {}
    if key == "matmul":
        if left.ndim != 2 or right.ndim != 2 or left.shape[1] != right.shape[0]:
            raise Diagnostic("shape_mismatch", "矩阵乘法要求两个二维矩阵且内维度相同")
        output_budget(
            (left.shape[0], right.shape[1]),
            np.result_type(left.dtype, right.dtype),
            maximum,
        )
        return left @ right, {}
    if key == "correlation":
        if left.dtype.kind == "c" or right.dtype.kind == "c":
            raise Diagnostic("real_numeric_required", "Pearson 相关要求实数")
        if (left.ndim != 1 or right.ndim != 1) and not parameters.get("flatten", False):
            raise Diagnostic("shape_mismatch", "多维输入需要明确选择展开方式")
        left, right = left.ravel(), right.ravel()
        if left.size != right.size or left.size < 2:
            raise Diagnostic("shape_mismatch", "相关分析需要同长的至少两个配对元素")
        if parameters.get("missing") == "pairwise":
            selected = np.isfinite(left) & np.isfinite(right)
            left, right = left[selected], right[selected]
        if left.size < 2 or np.std(left) == 0 or np.std(right) == 0:
            raise Diagnostic("constant_input", "有效配对不足或输入没有变异")
        coefficient = float(np.corrcoef(left, right)[0, 1])
        if not math.isfinite(coefficient):
            raise Diagnostic("missing_values", "缺失值策略未产生有限相关结果")
        return np.asarray(coefficient), {
            "coefficient": coefficient,
            "pairs": int(left.size),
            "method": "Pearson",
        }
    raise Diagnostic("operation_invalid", "未注册联合运算")


def main():
    request = json.loads(sys.stdin.buffer.read(1024 * 1024))
    try:
        check_coordinates(request["operator"], request["inputs"], request["parameters"])
        values = {role: read_input(spec) for role, spec in request["inputs"].items()}
        result, statistics = calculate(
            request["operator"], values, request["parameters"], request["maximum"]
        )
        package = Path(__file__).resolve().parents[2]
        for name, directory in [
            ("contract_driven_ai_flow", package),
            ("contract_driven_ai_flow.research", package / "research"),
        ]:
            spec = spec_from_file_location(
                name,
                directory / "__init__.py",
                submodule_search_locations=[str(directory)],
            )
            module = module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
        from contract_driven_ai_flow.research.agent.sdk import TraceSession
        from contract_driven_ai_flow.research.agent.budget import CapturePolicy
        from contract_driven_ai_flow.research.agent.privacy import sanitize_json

        trace = TraceSession(
            "derived",
            policy=CapturePolicy(level="full", max_artifact_bytes=request["maximum"]),
            run_id=request["run_id"],
            artifact_root=Path(request["state"]),
        )
        with trace.scope("derived"):
            snapshot = trace.watch(
                request["name"],
                result,
                parent_snapshots=request["parents"],
                provenance="declared",
                coverage={
                    "mode": "derived",
                    "operator": request["operator"],
                    "inputs": "full",
                    "dependency": "declared",
                },
            )
        meaning = result_semantics(
            request["operator"], request["inputs"], request["parameters"], result
        )
        meaning["logical_key"] = snapshot["logical_key"]
        snapshot["descriptor"]["metadata"]["semantics"] = sanitize_json(meaning)
        if not snapshot.get("artifact_ref"):
            raise Diagnostic(
                "result_budget_exceeded",
                "派生结果无法完整保存：" + ", ".join(snapshot["truncation"]),
            )
        print(
            json.dumps(
                {"status": "ready", "snapshot": snapshot, "statistics": statistics},
                ensure_ascii=False,
                allow_nan=False,
            )
        )
    except Diagnostic as error:
        print(
            json.dumps(
                {"status": "error", "code": error.code, "message": str(error)},
                ensure_ascii=False,
            )
        )
    except (ImportError, ModuleNotFoundError):
        print(
            json.dumps(
                {
                    "status": "error",
                    "code": "dependency_missing",
                    "message": "所选解释器缺少运算依赖",
                },
                ensure_ascii=False,
            )
        )
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "error",
                    "code": "operation_failed",
                    "message": "联合运算失败：" + type(error).__name__,
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
