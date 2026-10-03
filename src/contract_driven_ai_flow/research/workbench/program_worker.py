"""Standard-library protocol for an explicitly enabled user probe program."""

import hashlib
import importlib
import importlib.util
import inspect
import asyncio
import json
from pathlib import Path
import sys


def main():
    request = json.load(sys.stdin)
    root = Path(request["root"]).resolve()
    sys.path.insert(0, str(root))
    if request.get("dependencies"):
        from importlib.metadata import version, PackageNotFoundError
        from packaging.requirements import Requirement

        for declared in request["dependencies"]:
            requirement = Requirement(declared)
            if requirement.marker and not requirement.marker.evaluate():
                continue
            try:
                installed = version(requirement.name)
            except PackageNotFoundError:
                raise ValueError("Dependency is not installed: " + requirement.name)
            if requirement.specifier and installed not in requirement.specifier:
                raise ValueError(
                    "Dependency version is incompatible: "
                    + requirement.name
                    + " "
                    + installed
                )
    if request.get("action") == "dependencies":
        print(json.dumps({"dependencies": "verified"}))
        return
    module, symbol = request["entrypoint"].split(":")
    origin = root.joinpath(*module.split(".")).with_suffix(".py")
    if not origin.is_file():
        spec = importlib.util.find_spec(module)
        if spec is None or not spec.origin:
            raise ValueError("Program entry module is unavailable")
        origin = Path(spec.origin)
    expected = request.get("implementation_digest")
    if expected and (
        not origin.is_file()
        or hashlib.sha256(origin.read_bytes()).hexdigest() != expected
    ):
        raise ValueError(
            "Program changed after review; import and enable a new resource version"
        )
    if origin.is_file() and origin.suffix == ".py":
        # Verify and execute the same bytes, bypassing timestamp-based pyc.
        code = origin.read_bytes()
        if expected and hashlib.sha256(code).hexdigest() != expected:
            raise ValueError("Program changed after review")
        spec = importlib.util.spec_from_file_location(module, origin)
        imported = importlib.util.module_from_spec(spec)
        sys.modules[module] = imported
        exec(compile(code, str(origin), "exec"), imported.__dict__)
    else:
        imported = importlib.import_module(module)
    fn = imported
    for component in symbol.split("."):
        fn = getattr(fn, component)
    if not callable(fn):
        raise TypeError("Program entry is not callable")
    if not origin.is_file() and getattr(imported, "__file__", None):
        origin = Path(imported.__file__)
    digest = (
        hashlib.sha256(origin.read_bytes()).hexdigest() if origin.is_file() else None
    )
    if request.get("action") == "describe":
        print(
            json.dumps(
                {
                    "program_digest": digest,
                    "path": str(origin),
                    "signature": str(inspect.signature(fn)),
                },
                ensure_ascii=False,
            )
        )
        return
    result = fn(request["context"], request["parameters"])
    if inspect.isawaitable(result):
        result = asyncio.run(result)
    if not isinstance(result, dict):
        raise ValueError("Program result must be an object")
    if result.get("status") not in (
        "ready",
        "pass",
        "fail",
        "error",
        "unknown",
        "skipped",
    ):
        raise ValueError("Program result requires an explicit result status")
    print(
        json.dumps(
            {"result": result, "program_digest": digest},
            ensure_ascii=False,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
