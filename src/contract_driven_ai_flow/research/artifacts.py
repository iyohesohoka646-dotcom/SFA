"""Read bounded regions from the exact saved observation, never live objects."""
from __future__ import annotations

import json
from pathlib import Path

from .agent.privacy import cell


def selectors_for(shape, selectors):
    if len(selectors) > len(shape):
        raise ValueError("Too many slice selectors")
    result, remaining = [], 1
    for axis, size in enumerate(shape):
        selection = selectors[axis] if axis < len(selectors) else ({"index": 0} if axis < len(shape) - 2 else {"start": 0, "stop": min(size, 64)})
        if not isinstance(selection, dict) or set(selection) - {"index", "start", "stop", "step"}:
            raise ValueError("Invalid slice selector")
        if "index" in selection:
            index = selection["index"]
            if type(index) is not int or not 0 <= index < size or len(selection) != 1:
                raise ValueError("Slice index is outside the dimension")
            result.append(index)
            continue
        start, stop, step = selection.get("start", 0), selection.get("stop", min(size, 64)), selection.get("step", 1)
        if any(type(v) is not int for v in (start, stop, step)) or not (0 <= start <= stop <= size and step > 0):
            raise ValueError("Invalid slice range")
        count = len(range(start, stop, step))
        if count > 64:
            raise ValueError("A slice dimension is limited to 64 values")
        remaining *= count
        if remaining > 4096:
            raise ValueError("A slice is limited to 4096 cells")
        result.append(slice(start, stop, step))
    if sum(isinstance(s, slice) for s in result) > 2:
        raise ValueError("Fix higher axes before requesting a 2D slice")
    return tuple(result)


def read_slice(state: Path, snapshot, selectors) -> dict:
    root = Path(state).resolve()
    path = (root / snapshot.artifact_ref).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError("Artifact path is outside the evidence store")
    if not path.is_file():
        return {"available": False, "snapshot_id": snapshot.id, "reason": "Complete artifact is missing or expired"}
    if path.suffix == ".npy":
        import numpy as np
        array = np.load(path, mmap_mode="r", allow_pickle=False)
        selected = array[selectors_for(array.shape, selectors)]
        actual_shape = list(selected.shape)
        if selected.ndim == 0:
            values = [[cell(selected[()])]]
        elif selected.ndim == 1:
            values = [[cell(v) for v in selected]]
        else:
            values = [[cell(v) for v in row] for row in selected]
    elif path.suffix == ".arrow":
        import pyarrow as pa
        import pyarrow.ipc as ipc
        with pa.memory_map(str(path), "r") as stream:
            table = ipc.open_file(stream).read_all()
            row_selector, column_selector = selectors_for((table.num_rows, table.num_columns), selectors)
            rows = [row_selector] if type(row_selector) is int else range(*row_selector.indices(table.num_rows))
            columns = [column_selector] if type(column_selector) is int else range(*column_selector.indices(table.num_columns))
            tagged = (table.schema.metadata or {}).get(b"cdaf.cell_encoding") == b"json-v1"
            values = [[json.loads(table.column(c)[r].as_py()) if tagged else cell(table.column(c)[r].as_py()) for c in columns] for r in rows]
            actual_shape = [len(rows), len(columns)]
    else:
        raise ValueError("Unsupported complete artifact format")
    return {"available": True, "snapshot_id": snapshot.id, "fidelity": "exact", "shape": actual_shape, "values": values}
