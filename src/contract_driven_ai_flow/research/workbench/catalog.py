from ..probe_registry import BUILTINS, ProbeRegistry
from .models import ProbeDefinition, InputRole

VIEW_SCHEMA = {'type': 'object', 'properties': {
    'precision': {'type': 'integer', 'minimum': 0, 'maximum': 12},
    'show_values': {'type': 'boolean'}, 'show_coordinates': {'type': 'boolean'},
    'row_labels': {'type': 'array', 'items': {'type': 'string'}},
    'column_labels': {'type': 'array', 'items': {'type': 'string'}},
    'palette': {'type': 'string', 'enum': ['diverging', 'sequential', 'gray']},
    'scale': {'type': 'string', 'enum': ['linear', 'log', 'symmetric']},
    'unit': {'type': 'string'}, 'semantics': {'type': 'object'}}}


class ProbeCatalog:
    """Explicit registration; installed packages never become capabilities implicitly."""
    def __init__(self, registry=None):
        self.registry = registry or ProbeRegistry()
        self._definitions = {}
        for kind, label in [('auto', '自动数据视图'), ('matrix', '矩阵 / 热图'), ('table', '数据表'), ('scalar', '数值'), ('relationships', '直接关系')]:
            self.register(ProbeDefinition(id='view.' + kind, label=label, capability='view', execution='builtin',
                renderer=kind, parameter_schema=VIEW_SCHEMA, output_kinds=['view']))
        for tool, label in [('matplotlib', 'Matplotlib'), ('seaborn', 'Seaborn'), ('plotly', 'Plotly'), ('altair', 'Altair')]:
            self.register(ProbeDefinition(id='view.' + tool, label=label, capability='view', execution='program', tool_id=tool,
                parameter_schema={'type': 'object', 'properties': {'kind': {'type': 'string', 'enum': ['heatmap', 'line', 'histogram']}}}))
        for kind, label in BUILTINS.items():
            self.register(ProbeDefinition(id='check.' + kind, label=label, capability='check', execution='program'))
        for kind, execution, capability, label in [('model', 'model', 'interpret', '智能解读'), ('skill', 'skill', 'interpret', 'Skill 解读'), ('manual', 'manual', 'check', '人工判断')]:
            self.register(ProbeDefinition(id=capability + '.' + kind, label=label, capability=capability, execution=execution,
                supported_targets=['data', 'operation', 'function', 'control', 'file', 'project']))
        self.register(ProbeDefinition(id='check.structure', label='源码结构检查', capability='check', execution='builtin',
            supported_targets=['file', 'function', 'control'], evidence='metadata', output_kinds=['diagnostics']))
        self.register(ProbeDefinition(id='check.timing', label='函数与计算耗时', capability='check', execution='builtin',
            supported_targets=['operation', 'function'], evidence='metadata', output_kinds=['metrics']))
        self.register(ProbeDefinition(id='view.controls', label='条件与循环统计', capability='view', execution='builtin',
            supported_targets=['control', 'function', 'file'], evidence='metadata', output_kinds=['control_summary']))
        self.register(ProbeDefinition(id='view.compare', label='并排比较', capability='view', execution='builtin', renderer='compare', input_mode='joint',
            input_roles=[InputRole(name='left'), InputRole(name='right')], parameter_schema={**VIEW_SCHEMA, 'properties': {**VIEW_SCHEMA['properties'], 'shared_scale': {'type': 'boolean'}, 'linked_zoom': {'type': 'boolean'}}}))
        for key, label in [('elementwise', '逐元素运算'), ('matmul', '矩阵乘法'), ('correlation', '数值相关'), ('join', '按键表格连接'), ('aggregate', '聚合')]:
            roles = [InputRole(name='input')] if key == 'aggregate' else [InputRole(name='left'), InputRole(name='right')]
            self.register(ProbeDefinition(id='derive.' + key, label=label, capability='derive', execution='builtin', input_mode='joint',
                input_roles=roles, evidence='full_coordinates' if key == 'join' else 'full', output_kinds=['data'], parameter_schema={'type': 'object'}))

    def register(self, definition: ProbeDefinition):
        from jsonschema import Draft202012Validator, SchemaError
        try:
            Draft202012Validator.check_schema(definition.parameter_schema)
        except SchemaError as error:
            raise ValueError('Invalid parameter schema') from error
        if definition.id in self._definitions:
            raise ValueError('Probe definition is already registered')
        self._definitions[definition.id] = definition.model_copy(deep=True)

    def unregister_resource(self, resource_id):
        for key in [key for key, definition in self._definitions.items() if definition.resource_id == resource_id]:
            del self._definitions[key]

    def definitions(self):
        known = list(self._definitions.values())
        for plugin in self.registry.types():
            if not plugin['builtin']:
                known.append(ProbeDefinition(id='check.' + plugin['kind'], label=plugin['label'], capability='check', execution='program'))
        return [definition.model_copy(deep=True) for definition in known]

    def resolve(self, key):
        for definition in self.definitions():
            if definition.id == key:
                return definition
        raise ValueError('Probe definition is not registered')
