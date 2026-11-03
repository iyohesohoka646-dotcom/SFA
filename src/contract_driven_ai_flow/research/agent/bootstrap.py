"""Load only the tool's package, without adding its site-packages to sys.path."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import runpy
import sys


def main():
    package = Path(__file__).resolve().parents[2]
    # Preserve Python -m's script-directory discovery for local opted-in plugins.
    sys.path[0] = str(Path.cwd())
    for name, directory in (
        ("contract_driven_ai_flow", package),
        ("contract_driven_ai_flow.research", package / "research"),
    ):
        spec = spec_from_file_location(name, directory / "__init__.py",
                                       submodule_search_locations=[str(directory)])
        module = module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    runpy.run_module("contract_driven_ai_flow.research.agent.entry", run_name="__main__")


if __name__ == "__main__":
    main()
