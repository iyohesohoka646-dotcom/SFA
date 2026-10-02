from ..probe_registry import BUILTINS, ProbeRegistry
from .models import ProbeDefinition


class ProbeCatalog:
    """Explicit registration; installed packages never become capabilities implicitly."""
    def __init__(self, registry=None):
        self.registry = registry or ProbeRegistry()
        self._definitions = {}
        for kind, label in [('auto', '自动数据视图'), ('matrix', '矩阵 / 热图'), ('table', '数据表'), ('scalar', '数值'), ('relationships', '直接关系')]:
            self.register(ProbeDefinition(id='view.' + kind, label=label, capability='view', execution='builtin'))
        for tool, label in [('matplotlib', 'Matplotlib'), ('seaborn', 'Seaborn'), ('plotly', 'Plotly'), ('altair', 'Altair')]:
            self.register(ProbeDefinition(id='view.' + tool, label=label, capability='view', execution='program', tool_id=tool,
                parameter_schema={'type': 'object', 'properties': {'kind': {'type': 'string', 'enum': ['heatmap', 'line', 'histogram']}}}))
        for kind, label in BUILTINS.items():
            self.register(ProbeDefinition(id='check.' + kind, label=label, capability='check', execution='program'))
        for kind, execution, capability, label in [('model', 'model', 'interpret', '智能解读'), ('skill', 'skill', 'interpret', 'Skill 解读'), ('manual', 'manual', 'check', '人工判断')]:
            self.register(ProbeDefinition(id=capability + '.' + kind, label=label, capability=capability, execution=execution))

    def register(self, definition: ProbeDefinition):
        if definition.id in self._definitions:
            raise ValueError('Probe definition is already registered')
        self._definitions[definition.id] = definition.model_copy(deep=True)

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
