from pathlib import Path


class FlowError(Exception):
    pass


class Conflict(FlowError):
    pass


def inside(root: Path, relative: str) -> Path:
    base = root.resolve()
    path = (base / relative).resolve()
    if not path.is_relative_to(base) or Path(relative).is_absolute():
        raise FlowError(f"Path escapes project: {relative}")
    return path


def project_root(path: Path | None = None) -> Path:
    path = (path or Path.cwd()).resolve()
    for candidate in (path, *path.parents):
        if (candidate / "flow.yaml").is_file():
            return candidate
    raise FlowError(f"No flow.yaml under {path}; run cdaf demo or cdaf init")
