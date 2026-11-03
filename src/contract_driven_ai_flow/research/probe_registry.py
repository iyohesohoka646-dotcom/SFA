"""Explicit probe plugins and discoverable built-in checks, protocol v1."""
import re


BUILTINS = {
    "finite": "NaN / Infinity", "shape": "Shape", "dtype": "Data type", "broadcast": "Broadcast dimensions",
    "dimensions": "Operation dimensions", "range": "Value range", "missing": "Missing ratio",
    "variance": "Variance", "symmetry": "Symmetry", "capture_size": "Value memory", "duration": "Operation duration",
    "rank": "Matrix rank", "condition": "Condition number", "eigenvalues": "Eigenvalues",
}
EXPENSIVE = {"rank", "condition", "eigenvalues"}


class ProbeRegistry:
    def __init__(self):
        self._plugins = {}

    def register(self, kind: str, entrypoint: str, *, label=None):
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", kind) or kind in BUILTINS or kind in self._plugins:
            raise ValueError("Probe kind is invalid or already registered")
        module, separator, name = entrypoint.rpartition(":")
        if not separator or not module or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or len(entrypoint) > 4096:
            raise ValueError("Use an explicit module:Class or file.py:Class probe entrypoint")
        self._plugins[kind] = {"kind": kind, "entrypoint": entrypoint, "label": label or kind, "protocol_version": 1}

    def enable(self, names):
        if not names:
            return
        from importlib.metadata import entry_points
        installed = {e.name: e for e in entry_points(group="cdaf.research.probes")}
        for name in names:
            if name not in installed:
                raise ValueError("Unknown explicitly enabled probe: " + name)
            self.register(name, installed[name].value)

    def plugin(self, kind):
        return self._plugins.get(kind)

    def types(self):
        return [{"kind": kind, "label": label, "expensive": kind in EXPENSIVE, "protocol_version": 1, "builtin": True}
                for kind, label in BUILTINS.items()] + [{**value, "builtin": False, "expensive": False} for value in self._plugins.values()]
