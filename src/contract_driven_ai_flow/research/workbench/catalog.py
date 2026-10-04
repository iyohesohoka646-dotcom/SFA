from ..probe_registry import BUILTINS, ProbeRegistry
from .models import ProbeDefinition, InputRole

VIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "precision": {"type": "integer", "minimum": 0, "maximum": 12, "default": 3},
        "show_values": {"type": "boolean", "default": False},
        "show_coordinates": {"type": "boolean", "default": True},
        "row_labels": {"type": "array", "items": {"type": "string"}, "default": []},
        "column_labels": {"type": "array", "items": {"type": "string"}, "default": []},
        "palette": {"type": "string", "enum": ["diverging", "sequential", "gray"], "default": "diverging"},
        "scale": {"type": "string", "enum": ["linear", "log", "symmetric"], "default": "linear"},
        "unit": {"type": "string", "default": ""},
        "semantics": {"type": "object"},
    },
}


class ProbeCatalog:
    """Explicit registration; installed packages never become capabilities implicitly."""

    def __init__(self, registry=None):
        self.registry = registry or ProbeRegistry()
        self._definitions = {}
        for kind, label in [
            ("auto", "自动数据视图"),
            ("matrix", "矩阵 / 热图"),
            ("table", "数据表"),
            ("scalar", "数值"),
            ("relationships", "直接关系"),
        ]:
            self.register(
                ProbeDefinition(
                    id="view." + kind,
                    label=label,
                    capability="view",
                    execution="builtin",
                    renderer=kind,
                    parameter_schema=VIEW_SCHEMA,
                    output_kinds=["view"],
                )
            )
        for tool, label in [
            ("matplotlib", "Matplotlib"),
            ("seaborn", "Seaborn"),
            ("plotly", "Plotly"),
            ("altair", "Altair"),
        ]:
            self.register(
                ProbeDefinition(
                    id="view." + tool,
                    label=label,
                    capability="view",
                    execution="program",
                    tool_id=tool,
                    parameter_schema={
                        "type": "object",
                        "properties": {
                            "kind": {
                                "type": "string",
                                "enum": ["heatmap", "line", "histogram"],
                                "default": "heatmap",
                            }
                        },
                    },
                )
            )
        for kind, label in BUILTINS.items():
            numeric = {"type": ["number", "null"], "default": None}
            fields = {
                "shape": {
                    "expected": {
                        "type": "array",
                        "title": "期望形状",
                        "items": {"type": ["integer", "null"], "minimum": 0},
                        "default": [],
                        "description": "逗号分隔；* 表示任意大小，留空表示标量",
                    }
                },
                "dtype": {"expected": {"type": "string", "title": "期望数据类型", "default": "float64"}},
                "range": {"min": numeric, "max": numeric},
                "variance": {"min": numeric, "max": numeric},
                "missing": {
                    "max_ratio": {"type": "number", "minimum": 0, "maximum": 1, "default": 0}
                },
                "symmetry": {"tolerance": {"type": "number", "minimum": 0, "default": 1e-8}},
                "capture_size": {"max_bytes": {"type": "integer", "minimum": 0, "default": 104857600}},
                "duration": {"max_ms": {"type": "number", "minimum": 0, "default": 1000}},
                "broadcast": {
                    "other_shape": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 0},
                        "default": [],
                    }
                },
                "dimensions": {
                    "operation": {"type": "string", "enum": ["broadcast", "matmul"], "default": "broadcast"},
                    "other_shape": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 0},
                        "default": [],
                    },
                },
                "rank": {"enable_expensive": {"type": "boolean", "default": False}},
                "condition": {"enable_expensive": {"type": "boolean", "default": False}},
                "eigenvalues": {"enable_expensive": {"type": "boolean", "default": False}},
            }.get(kind, {})
            self.register(
                ProbeDefinition(
                    id="check." + kind,
                    label=label,
                    capability="check",
                    execution="program",
                    parameter_schema={"type": "object", "properties": fields},
                )
            )
        for kind, execution, capability, label in [
            ("model", "model", "interpret", "智能解读"),
            ("skill", "skill", "interpret", "Skill 解读"),
            ("manual", "manual", "check", "人工判断"),
        ]:
            self.register(
                ProbeDefinition(
                    id=capability + "." + kind,
                    label=label,
                    capability=capability,
                    execution=execution,
                    parameter_schema={
                        "type": "object",
                        "properties": {
                            "task": {"type": "string", "default": "解读选中对象的计算作用、数据特征及直接关系。"},
                            "focus": {"type": "string", "default": "关键数值、异常与证据覆盖范围"},
                            "constraints": {"type": "string", "default": "仅依据提供的证据，明确标注未知项。"},
                            "output_format": {"type": "string", "default": "用简洁中文给出结论、依据与待确认项。"},
                            "prompt": {"type": "string", "default": ""},
                            **({
                                "provider_id": {"type": "string", "default": ""},
                                "model": {"type": "string", "default": ""},
                            } if execution != "manual" else {}),
                            **(
                                {"skill_id": {"type": "string", "default": ""}}
                                if execution == "skill"
                                else {}
                            ),
                        },
                    },
                    supported_targets=[
                        "data",
                        "operation",
                        "function",
                        "control",
                        "file",
                        "project",
                    ],
                )
            )
        self.register(
            ProbeDefinition(
                id="check.structure",
                label="源码结构检查",
                capability="check",
                execution="builtin",
                supported_targets=["file", "function", "control"],
                evidence="metadata",
                output_kinds=["diagnostics"],
            )
        )
        self.register(
            ProbeDefinition(
                id="check.timing",
                label="函数与计算耗时",
                capability="check",
                execution="builtin",
                supported_targets=["operation", "function"],
                evidence="metadata",
                output_kinds=["metrics"],
                parameter_schema={
                    "type": "object",
                    "properties": {"maximum_ms": {"type": "number", "minimum": 0, "default": 1000}},
                    "additionalProperties": False,
                },
            )
        )
        self.register(
            ProbeDefinition(
                id="view.controls",
                label="条件与循环统计",
                capability="view",
                execution="builtin",
                supported_targets=["control", "function", "file"],
                evidence="metadata",
                output_kinds=["control_summary"],
            )
        )
        self.register(
            ProbeDefinition(
                id="view.compare",
                label="并排比较",
                capability="view",
                execution="builtin",
                renderer="compare",
                input_mode="joint",
                input_roles=[InputRole(name="left"), InputRole(name="right")],
                parameter_schema={
                    **VIEW_SCHEMA,
                    "properties": {
                        **VIEW_SCHEMA["properties"],
                        "shared_scale": {"type": "boolean", "default": True},
                        "linked_zoom": {"type": "boolean", "default": True},
                        "allow_cross_run": {"type": "boolean", "default": False},
                    },
                },
            )
        )
        for key, label in [
            ("elementwise", "逐元素运算"),
            ("matmul", "矩阵乘法"),
            ("correlation", "数值相关"),
            ("join", "按键表格连接"),
            ("aggregate", "聚合"),
        ]:
            roles = (
                [InputRole(name="input")]
                if key == "aggregate"
                else [InputRole(name="left"), InputRole(name="right")]
            )
            properties = {
                "missing": {
                    "type": "string",
                    "enum": ["error", "propagate"]
                    + (["pairwise"] if key == "correlation" else []),
                    "default": "error",
                },
                "alignment": {"type": "string", "enum": ["coordinates", "positional"], "default": "coordinates"},
                "allow_cross_run": {"type": "boolean", "default": False},
            }
            properties.update(
                {
                    "elementwise": {
                        "operation": {
                            "type": "string",
                            "enum": ["subtract", "add", "multiply", "divide"],
                            "default": "subtract",
                        },
                        "broadcast": {"type": "boolean", "default": False},
                    },
                    "matmul": {},
                    "correlation": {"flatten": {"type": "boolean", "default": False}},
                    "aggregate": {
                        "method": {
                            "type": "string",
                            "enum": ["mean", "sum", "min", "max", "std", "median"],
                            "default": "mean",
                        },
                        "axis": {"type": ["integer", "null"], "default": None},
                    },
                    "join": {
                        "keys": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                        },
                        "how": {
                            "type": "string",
                            "enum": ["inner", "left", "right", "outer"],
                            "default": "inner",
                        },
                        "cardinality": {
                            "type": "string",
                            "enum": [
                                "one_to_one",
                                "one_to_many",
                                "many_to_one",
                                "many_to_many",
                            ],
                            "default": "one_to_one",
                        },
                    },
                }[key]
            )
            self.register(
                ProbeDefinition(
                    id="derive." + key,
                    label=label,
                    capability="derive",
                    execution="builtin",
                    input_mode="joint",
                    input_roles=roles,
                    evidence="full_coordinates" if key == "join" else "full",
                    output_kinds=["data"],
                    parameter_schema={"type": "object", "properties": properties},
                )
            )

    def register(self, definition: ProbeDefinition):
        from jsonschema import Draft202012Validator, SchemaError

        try:
            Draft202012Validator.check_schema(definition.parameter_schema)
        except SchemaError as error:
            raise ValueError("Invalid parameter schema") from error
        if definition.id in self._definitions:
            raise ValueError("Probe definition is already registered")
        self._definitions[definition.id] = definition.model_copy(deep=True)

    def unregister_resource(self, resource_id):
        for key in [
            key
            for key, definition in self._definitions.items()
            if definition.resource_id == resource_id
        ]:
            del self._definitions[key]

    def definitions(self):
        known = list(self._definitions.values())
        for plugin in self.registry.types():
            if not plugin["builtin"]:
                known.append(
                    ProbeDefinition(
                        id="check." + plugin["kind"],
                        label=plugin["label"],
                        capability="check",
                        execution="program",
                    )
                )
        return [definition.model_copy(deep=True) for definition in known]

    def resolve(self, key):
        for definition in self.definitions():
            if definition.id == key:
                return definition
        raise ValueError("Probe definition is not registered")
