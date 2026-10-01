"""Version 1 data adapters. Numerical libraries are resolved lazily."""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from typing import Protocol

from .budget import CapturePolicy
from .privacy import cell, finite_number, sensitive, type_name


@dataclass
class CaptureResult:
    descriptor: dict
    sample: dict = field(default_factory=dict)
    statistics: dict = field(default_factory=dict)
    fidelity: str = "metadata_only"
    truncation: list[str] = field(default_factory=list)
    artifact_ref: str | None = None
    redacted: list[str] = field(default_factory=list)


class DataAdapter(Protocol):
    protocol_version: int
    backend: str

    def supports(self, value: object) -> bool: ...
    def describe(self, value: object) -> dict: ...
    def capture(self, value: object, policy: CapturePolicy) -> CaptureResult: ...


def indices(length: int, budget: int) -> list[int]:
    count = min(length, budget)
    if count < 1:
        return []
    if count == 1:
        return [0]
    return [i * (length - 1) // (count - 1) for i in range(count)]


def numeric_statistics(data, population: int, *, method="uniform-grid") -> dict:
    np = sys.modules["numpy"]
    exact = len(data) == population
    result = {"population_count": population, "sample_count": len(data), "exact": exact, "method": "all" if exact else method}
    if data.dtype.kind not in "biufc":
        return result
    finite = np.isfinite(data)
    result.update(finite_count=int(np.count_nonzero(finite)), nan_count=int(np.count_nonzero(np.isnan(data))),
                  inf_count=int(np.count_nonzero(np.isinf(data))), missing_count=int(np.count_nonzero(np.isnan(data))))
    good = data[finite]
    if data.dtype.kind == "c":
        with np.errstate(all="ignore"):
            good = np.abs(good)
        result["numeric_metric"] = "magnitude"
        result["metric_overflow_count"] = int(np.count_nonzero(~np.isfinite(good)))
    if good.size:
        with np.errstate(all="ignore"):
            result.update(min=finite_number(good.min()), max=finite_number(good.max()),
                          mean=finite_number(good.mean()), variance=finite_number(good.var()))
    return result


class UnknownAdapter:
    protocol_version = 1
    backend = "unknown"

    def supports(self, value):
        return True

    def describe(self, value):
        return {"schema_version": 1, "kind": "unknown", "backend": self.backend, "type_name": type_name(value), "capabilities": []}

    def capture(self, value, policy):
        return CaptureResult(self.describe(value))


class ScalarAdapter:
    protocol_version = 1
    backend = "python"

    def supports(self, value):
        return value is None or type(value) in (bool, int, float, complex, str)

    def describe(self, value):
        return {"schema_version": 1, "kind": "scalar", "backend": self.backend, "type_name": type_name(value),
                "shape": [], "dtype": type(value).__name__, "capabilities": ["preview"]}

    def capture(self, value, policy):
        return CaptureResult(self.describe(value), sample={} if policy.level == "metadata" else {"values": [[cell(value)]]},
                             fidelity="metadata_only" if policy.level == "metadata" else "exact")


class NumpyAdapter:
    protocol_version = 1
    backend = "numpy"
    artifact_extension = ".npy"

    def supports(self, value):
        np = sys.modules.get("numpy")
        return np is not None and isinstance(value, (np.ndarray, np.generic))

    @staticmethod
    def array(value):
        np = sys.modules["numpy"]
        # Strip ndarray subclass overrides without copying the storage.
        return np.ndarray.view(value, np.ndarray) if isinstance(value, np.ndarray) else np.asarray(value)

    def describe(self, value):
        np = sys.modules["numpy"]
        array = np.ndarray.view(value, np.ndarray) if isinstance(value, np.ndarray) else value
        numeric = array.dtype.kind in "biufc"
        return {"schema_version": 1, "kind": "matrix", "backend": self.backend, "type_name": type_name(value),
                "shape": list(array.shape), "dtype": str(array.dtype), "nbytes": int(array.nbytes), "device": "cpu",
                "capabilities": ["preview", "statistics", "alias", *(["materialize", "slice"] if numeric else [])],
                "metadata": {"contiguous": bool(array.flags.c_contiguous), "owns_data": bool(array.flags.owndata),
                             "alias_coverage": "storage-sharing candidates; hidden mutation is not automatically observed"}}

    def capture(self, value, policy):
        descriptor = self.describe(value)
        if policy.level == "metadata":
            return CaptureResult(descriptor)
        if value.dtype.itemsize > 4096:
            # Wide fixed-width cells can allocate megabytes per indexed element.
            return CaptureResult(descriptor, truncation=["cell_byte_limit"])
        array = self.array(value)
        fixed = {str(axis): 0 for axis in range(max(0, array.ndim - 2))}
        if not array.size:
            sample = {"values": [], "row_indices": [], "column_indices": [], "fixed_axes": fixed}
        elif array.ndim == 0:
            sample = {"values": [[cell(array[()])]], "row_indices": [0], "column_indices": [0], "fixed_axes": {}}
        else:
            plane = array[(0,) * max(0, array.ndim - 2)]
            if plane.ndim == 1:
                columns = indices(plane.shape[0], min(32, policy.max_preview_cells))
                rows = [0]
                values = [[cell(plane[c]) for c in columns]]
            else:
                rows = indices(plane.shape[0], min(32, policy.max_preview_cells))
                columns = indices(plane.shape[1], min(32, policy.max_preview_cells // max(1, len(rows))))
                values = [[cell(plane[r, c]) for c in columns] for r in rows]
            sample = {"values": values, "row_indices": rows, "column_indices": columns, "fixed_axes": fixed}
        stats = {}
        if policy.level in ("summary", "full") and array.dtype.kind in "biufc":
            # flat indexing allocates only the bounded sample, even for strided arrays.
            stats = numeric_statistics(array.flat[indices(array.size, policy.max_stat_elements)], array.size)
        preview_count = sum(len(row) for row in sample["values"])
        return CaptureResult(descriptor, sample=sample, statistics=stats,
                             fidelity="exact" if preview_count == array.size else "sampled",
                             truncation=["preview_sampled"] if preview_count < array.size else [])

    def save(self, value, target, policy):
        sys.modules["numpy"].save(target, self.array(value), allow_pickle=False)


class PandasAdapter:
    protocol_version = 1
    backend = "pandas"
    artifact_extension = ".arrow"

    def supports(self, value):
        pd = sys.modules.get("pandas")
        return pd is not None and type(value) in (pd.DataFrame, pd.Series)

    @staticmethod
    def frame(value):
        pd = sys.modules["pandas"]
        return value.to_frame() if type(value) is pd.Series else value

    def describe(self, value):
        frame = self.frame(value)
        columns = [{"name": cell(frame.columns[i]), "dtype": str(frame.iloc[:, i].dtype)} for i in range(min(frame.shape[1], 256))]
        return {"schema_version": 1, "kind": "table", "backend": self.backend, "type_name": type_name(value),
                "shape": list(frame.shape), "dtype": "table", "nbytes": int(frame.memory_usage(index=True, deep=False).sum()),
                "device": "cpu", "capabilities": ["preview", "statistics", "materialize", "slice"],
                "metadata": {"columns": columns, "omitted_columns": max(0, frame.shape[1] - 256), "index_type": type_name(frame.index)}}

    def capture(self, value, policy):
        descriptor = self.describe(value)
        if policy.level == "metadata":
            return CaptureResult(descriptor)
        frame = self.frame(value)
        rows = indices(frame.shape[0], min(32, policy.max_preview_cells))
        columns = indices(frame.shape[1], min(32, policy.max_preview_cells // max(1, len(rows))))
        private = {i for i in columns if type(frame.columns[i]) is str and sensitive(frame.columns[i], policy.sensitive_fields)}
        values = [["[REDACTED]" if c in private else cell(frame.iat[r, c]) for c in columns] for r in rows]
        sample = {"values": values, "row_indices": rows, "column_indices": columns,
                  "columns": [cell(frame.columns[c]) for c in columns], "index": [cell(frame.index[r]) for r in rows]}
        population = frame.shape[0] * frame.shape[1]
        stats = {}
        if policy.level in ("summary", "full"):
            chosen = indices(population, policy.max_stat_elements)
            numeric, missing = [], 0
            np = sys.modules["numpy"]
            for i in chosen:
                r, c = divmod(i, frame.shape[1])
                if type(frame.columns[c]) is str and sensitive(frame.columns[c], policy.sensitive_fields):
                    continue
                v = cell(frame.iat[r, c])
                if v is None or type(v) is dict and v.get("type") == "nonfinite" and v.get("value") == "nan":
                    missing += 1
                if type(v) in (int, float, bool):
                    numeric.append(v)
            stats = numeric_statistics(np.asarray(numeric, dtype=float), population)
            stats.update(sample_count=len(chosen), numeric_sample_count=len(numeric), missing_count=missing,
                         exact=len(chosen) == population and not private,
                         method="all" if len(chosen) == population else "uniform-grid")
        return CaptureResult(descriptor, sample=sample, statistics=stats,
                             fidelity="exact" if len(rows) * len(columns) == population else "sampled",
                             truncation=["preview_sampled"] if len(rows) * len(columns) < population else [],
                             redacted=["column:" + str(c) for c in sorted(private)])

    def save(self, value, target, policy):
        import pyarrow as pa
        import pyarrow.ipc as ipc

        frame = self.frame(value)
        # Explicit full capture still uses primitive encoding and redaction, so
        # arbitrary object columns cannot invoke repr/Arrow conversion hooks.
        columns = []
        estimated = 0
        for c in range(frame.shape[1]):
            name = frame.columns[c]
            private = type(name) is str and sensitive(name, policy.sensitive_fields)
            items = []
            for v in frame.iloc[:, c]:
                if private:
                    item = "[REDACTED]"
                elif type(v) is str:
                    # Size check precedes copying/JSON encoding, including
                    # object-column strings absent from shallow memory_usage.
                    estimated += len(v) * 4
                    if estimated > policy.max_artifact_bytes:
                        raise ValueError("artifact_byte_limit")
                    from .privacy import clean_text
                    item = clean_text(v, policy.max_artifact_bytes)
                else:
                    item = cell(v)
                estimated += 32
                if estimated > policy.max_artifact_bytes:
                    raise ValueError("artifact_byte_limit")
                items.append(item)
            if any(type(item) is dict and item.get("type") == "unavailable" for item in items):
                raise ValueError("Full table capture cannot encode arbitrary user objects")
            # Arrow provides portable columnar framing. Tagged strict JSON cells
            # retain nullable/complex/datetime types without Python pickles.
            import json
            columns.append(pa.array([json.dumps(v, allow_nan=False, ensure_ascii=False) for v in items]))
        table = pa.Table.from_arrays(columns, names=["column_" + str(i) for i in range(len(columns))])
        table = table.replace_schema_metadata({b"cdaf.cell_encoding": b"json-v1"})
        with ipc.new_file(target, table.schema) as writer:
            writer.write_table(table)


def describe(value: object) -> dict:
    from .registry import AdapterRegistry
    return AdapterRegistry().resolve(value).describe(value)


def capture(value: object, policy: CapturePolicy) -> CaptureResult:
    from .registry import AdapterRegistry
    return AdapterRegistry().resolve(value).capture(value, policy)
