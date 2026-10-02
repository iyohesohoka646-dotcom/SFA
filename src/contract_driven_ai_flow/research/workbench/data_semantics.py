"""Reusable scientific meaning and view parameters, independent of renderers."""

from __future__ import annotations

import hashlib
from typing import Literal
from pydantic import Field, JsonValue
from ..models import WireModel
from .store import WorkbenchStore


class AxisSemantics(WireModel):
    label: str = ""
    meaning: str = ""
    unit: str = ""
    coordinates: list[JsonValue] = Field(default_factory=list, max_length=100000)
    labels: list[str] = Field(default_factory=list, max_length=100000)
    origin: Literal["program", "user", "model"] = "user"


class ColumnSemantics(WireModel):
    key: str
    label: str = ""
    meaning: str = ""
    unit: str = ""
    format: str = ""
    missing: str = "—"
    origin: Literal["program", "user", "model"] = "user"


class DataSemantics(WireModel):
    protocol_version: Literal[3] = 3
    logical_key: str
    kind: Literal[
        "matrix", "table", "series", "scatter", "points", "graph", "generic"
    ] = "generic"
    axes: list[AxisSemantics] = Field(default_factory=list, max_length=32)
    columns: list[ColumnSemantics] = Field(default_factory=list, max_length=4096)
    element_meaning: str = ""
    unit: str = ""
    mappings: dict[str, JsonValue] = Field(default_factory=dict)
    origin: Literal["program", "user", "model"] = "user"
    revision: int = Field(default=0, ge=0)
    accepted: bool = True

    def validate_shape(self, shape):
        if shape is None and self.axes:
            raise ValueError("Unknown shape cannot validate axis coordinates")
        if len(self.axes) > len(shape or []):
            raise ValueError("More axis definitions than data dimensions")
        for i, axis in enumerate(self.axes):
            if (
                axis.coordinates
                and len(axis.coordinates) != shape[i]
                or axis.labels
                and len(axis.labels) != shape[i]
            ):
                raise ValueError(
                    f"axis {i} coordinate/label length must equal {shape[i]}"
                )
        if self.columns and shape and len(shape) == 2 and len(self.columns) != shape[1]:
            raise ValueError("Column definitions must match table width")
        return self


class PresentationSpec(WireModel):
    precision: int = Field(default=3, ge=0, le=12)
    show_values: bool = False
    show_coordinates: bool = True
    palette: Literal["diverging", "sequential", "gray"] = "diverging"
    scale: Literal["linear", "log", "symmetric"] = "linear"
    row_labels: list[str] = Field(default_factory=list)
    column_labels: list[str] = Field(default_factory=list)
    semantics: DataSemantics | None = None


class SemanticsService:
    def __init__(self, root):
        self.store = WorkbenchStore(root)

    @staticmethod
    def key(logical_key):
        return hashlib.sha256(logical_key.encode()).hexdigest()

    def get(self, logical_key):
        try:
            return DataSemantics.model_validate(
                self.store.get("semantics", self.key(logical_key))
            )
        except KeyError:
            return None

    def save(self, semantics, *, shape, expected_revision=None):
        semantics.validate_shape(shape)
        semantics = semantics.model_copy(deep=True)
        if (
            semantics.origin == "user"
            and semantics.accepted
            and len(semantics.axes) == len(shape or [])
            and all(axis.coordinates or axis.labels for axis in semantics.axes)
        ):
            semantics.mappings.pop("coordinate_gaps", None)
        current = self.get(semantics.logical_key)
        revision = current.revision if current else 0
        if expected_revision is not None and expected_revision != revision:
            raise ValueError("Data semantics revision conflict")
        updated = semantics.model_copy(deep=True, update={"revision": revision + 1})
        self.store.put("semantics", self.key(updated.logical_key), updated)
        return updated

    def save_template(self, key, label, definition_id, parameters, semantics=None):
        import jsonschema
        from .catalog import ProbeCatalog

        definition = ProbeCatalog().resolve(definition_id)
        jsonschema.validate(parameters, definition.parameter_schema)
        template = {
            "id": key,
            "label": label,
            "definition_id": definition_id,
            "parameters": parameters,
            "semantics": semantics.model_dump(mode="json") if semantics else None,
        }
        self.store.put("templates", key, template)
        return template

    def templates(self):
        return self.store.list("templates", limit=1000)
