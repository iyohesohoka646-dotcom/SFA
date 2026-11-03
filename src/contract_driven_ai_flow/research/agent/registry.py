"""Explicitly enabled versioned adapters; no ambient plugin execution."""
from .adapters import NumpyAdapter, PandasAdapter, ScalarAdapter, UnknownAdapter


class AdapterRegistry:
    def __init__(self):
        self._custom = []
        self._builtins = [ScalarAdapter(), NumpyAdapter(), PandasAdapter()]
        self._unknown = UnknownAdapter()

    def register(self, adapter):
        if getattr(adapter, "protocol_version", None) != 1:
            raise ValueError("Adapter protocol must be version 1")
        for name in ("supports", "describe", "capture"):
            if not callable(getattr(adapter, name, None)):
                raise ValueError("Adapter is missing " + name)
        backend = getattr(adapter, "backend", None)
        if type(backend) is not str or not backend or len(backend) > 256:
            raise ValueError("Adapter must declare a bounded backend ID")
        if any(a.backend == backend for a in self._custom):
            raise ValueError("Adapter backend is already registered")
        self._custom.append(adapter)

    def enable(self, names):
        if not names:
            return
        from importlib.metadata import entry_points

        available = {e.name: e for e in entry_points(group="cdaf.research.adapters")}
        for name in names:
            if name not in available:
                raise ValueError("Unknown explicitly enabled adapter: " + name)
            self.register(available[name].load()())

    def resolve(self, value):
        for adapter in (*self._custom, *self._builtins):
            if adapter.supports(value):
                return adapter
        return self._unknown
