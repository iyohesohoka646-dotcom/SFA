"""Spawn entrypoint: load project code only in the child, transfer strict JSON bytes."""
from __future__ import annotations

import asyncio
import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import inspect
import json
import os
import sys
import types
from pathlib import Path

from .models import canonical
from .paths import inside
from .storage import file_digest

MAX_PAYLOAD = 16 * 1024 * 1024


def load_entry(base: Path, path: Path, content: str):
    """Resolve relative imports, including parent re-exports, from verified bytes."""
    search_root = base / "src" if path.is_relative_to(base / "src") and not (base / "src/__init__.py").exists() else base
    parts = list(path.relative_to(search_root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    if not parts or not all(part.isidentifier() for part in parts):
        parts = ["_entry"]
    prefix = "_cdaf_user_code"
    namespace = types.ModuleType(prefix)
    namespace.__path__ = [str(search_root)]
    namespace.__spec__ = importlib.machinery.ModuleSpec(prefix, loader=None, is_package=True)
    namespace.__spec__.submodule_search_locations = namespace.__path__
    sys.modules[prefix] = namespace
    name = prefix + "." + ".".join(parts)

    class VerifiedLoader(importlib.machinery.SourceFileLoader):
        def get_code(self, fullname):
            return compile(content, str(path), "exec")

    class EntryFinder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, import_path=None, target=None):
            if fullname == name:
                return importlib.util.spec_from_file_location(name, path, loader=VerifiedLoader(name, str(path)))
            return None

    finder = EntryFinder()
    sys.meta_path.insert(0, finder)
    try:
        return importlib.import_module(name)
    finally:
        sys.meta_path.remove(finder)


def invoke(connection, root: str, symbol: dict, payload: bytes, expected_source_digest: str):
    # Prevent print(), native writes and import-time logging from leaking captures.
    with open(os.devnull, "w") as sink:
        sys.stdout = sink
        sys.stderr = sink
        for descriptor in (1, 2):
            try:
                os.dup2(sink.fileno(), descriptor)
            except OSError:
                pass
        try:
            base = Path(root)
            path = inside(base, symbol["path"])
            sys.path[:0] = [str(base), str(base / "src"), str(path.parent)]
            os.chdir(base)
            content = path.read_text(encoding="utf-8")
            if file_digest(content) != expected_source_digest:
                raise SourceRevisionMismatch()
            module = load_entry(base, path, content)
            target = module
            for part in symbol["qualname"].split("."):
                target = getattr(target, part)
            kwargs = json.loads(payload)
            positional = []
            for parameter in inspect.signature(target).parameters.values():
                if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
                    if parameter.name in kwargs:
                        positional.append(kwargs.pop(parameter.name))
                    elif parameter.default is not inspect.Parameter.empty:
                        positional.append(parameter.default)
                    else:
                        raise TypeError("Required positional input is unbound")
            value = target(*positional, **kwargs)
            if inspect.isawaitable(value):
                value = asyncio.run(value)
            encoded = canonical({"status": "completed", "output": value}).encode("utf-8")
            if len(encoded) > MAX_PAYLOAD:
                raise ValueError("Output exceeds 16 MiB boundary limit")
            connection.send_bytes(encoded)
        except BaseException as exc:
            # Values in exception strings can contain secrets. Report type and source
            # location, never unbounded user messages, stdout, stderr or repr(instance).
            locations = []
            tb = exc.__traceback__
            while tb:
                p = Path(tb.tb_frame.f_code.co_filename).resolve()
                if p.is_relative_to(Path(root).resolve()):
                    locations.append({"path": str(p.relative_to(root)).replace("\\", "/"), "line": tb.tb_lineno})
                tb = tb.tb_next
            connection.send_bytes(canonical({"status": "failed", "error": {"type": type(exc).__name__, "message": "Module execution or JSON encoding failed", "locations": locations[-8:]}}).encode("utf-8"))
        finally:
            connection.close()


class SourceRevisionMismatch(Exception):
    """A source file changed after the run recorded its version."""
