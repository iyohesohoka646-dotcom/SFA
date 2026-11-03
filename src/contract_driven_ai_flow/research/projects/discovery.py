"""Bounded, inert file discovery. Never imports or executes user sources."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path

MAX_FILE_BYTES = 10 * 1024 * 1024

EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".cdaf",
        "build",
        "dist",
    }
)


@dataclass(frozen=True)
class DiscoveredFile:
    relative_path: str
    path: Path
    digest: str
    size: int
    module_names: list[str] = field(default_factory=list)


def normalize_relative(root: Path, path: Path) -> str | None:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    text = rel.as_posix()
    if text == "." or text.startswith(".."):
        return None
    return text


def _inside(root: Path, path: Path) -> bool:
    return _inside_resolved(root.resolve(), path)


def _inside_resolved(root: Path, path: Path) -> bool:
    """Ancestry check against an already-resolved root (resolved once)."""
    try:
        path.resolve().relative_to(root)
        return True
    except ValueError:
        return False


def _relative_of(root: Path, path: Path) -> str | None:
    """Relative posix path for a known in-root path, without re-resolving root."""
    rel = os.path.relpath(path, root)
    if rel == "." or rel == os.pardir or rel.startswith(os.pardir + os.sep):
        return None
    return Path(rel).as_posix()


def _check_cancel(cancel) -> None:
    if cancel is not None and cancel.is_set():
        raise InterruptedError("Discovery cancelled")


def detect_layout(root: Path, cancel=None, progress=None) -> dict:
    """Bounded src-layout probe: prunes links, excluded and dependency dirs."""
    root = Path(root).resolve()
    src = root / "src"
    has_src = False
    if src.is_dir() and _inside_resolved(root, src):
        for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
            _check_cancel(cancel)
            current = Path(dirpath)
            kept = []
            for name in dirnames:
                child = current / name
                if name in EXCLUDED_DIRS or child.is_symlink() or not _inside_resolved(root, child):
                    continue
                kept.append(name)
            dirnames[:] = kept
            if any(name.endswith(".py") for name in filenames):
                has_src = True
                break
            if progress is not None:
                progress(str(current))
    return {"src_layout": has_src, "module_root": "src" if has_src else "."}


def module_names_for(relative_path: str, *, src_layout: bool) -> list[str]:
    parts = relative_path.split("/")
    if src_layout and parts and parts[0] == "src":
        parts = parts[1:]
    if not parts:
        return []
    stem = parts[-1]
    if not stem.endswith(".py"):
        return []
    parts = parts[:-1] + [stem[:-3]]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    package = ".".join(p for p in parts if p)
    names = [package] if package else []
    return names


def _matches_any(relative: str, patterns: list[str]) -> bool:
    """Glob match where ``**/`` also covers the project root itself."""
    name = relative.rsplit("/", 1)[-1]
    for pattern in patterns:
        stripped = pattern[3:] if pattern.startswith("**/") else pattern
        if (
            fnmatchcase(relative, pattern)
            or fnmatchcase(name, pattern)
            or fnmatchcase(relative, stripped)
        ):
            return True
    return False


def discover_files(root: Path, section, cancel=None, progress=None) -> tuple[list[DiscoveredFile], list[str]]:
    """Return candidate Python files and non-fatal diagnostics (cancellable)."""
    root = Path(root).resolve()
    diagnostics: list[str] = []
    include = list(section.include) or ["**/*.py"]
    exclude = list(section.exclude)
    source_roots = [str(s) for s in section.source_roots] or ["."]
    layout = detect_layout(root, cancel=cancel, progress=progress)

    candidates: dict[str, DiscoveredFile] = {}
    for source_root in source_roots:
        base = (root / source_root).resolve() if source_root not in (".", "") else root
        if not base.is_dir() or not _inside_resolved(root, base):
            diagnostics.append(f"Source root is unavailable or outside the project: {source_root}")
            continue
        for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
            _check_cancel(cancel)
            current = Path(dirpath)
            kept = []
            for name in dirnames:
                child = current / name
                if name in EXCLUDED_DIRS or child.is_symlink() or not _inside_resolved(root, child):
                    continue
                kept.append(name)
            dirnames[:] = kept
            for name in filenames:
                if not name.endswith(".py"):
                    continue
                path = current / name
                if path.is_symlink():
                    diagnostics.append(f"Skipped out-of-root link: {path}")
                    continue
                rel = _relative_of(root, path)
                if rel is None or _matches_any(rel, exclude):
                    continue
                if not _matches_any(rel, include):
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                if size > MAX_FILE_BYTES:
                    diagnostics.append(f"Skipped oversized file (>10 MiB): {rel}")
                    continue
                if rel in candidates:
                    continue
                _check_cancel(cancel)
                if progress is not None:
                    progress(rel)
                try:
                    raw = path.read_bytes()
                except OSError as error:
                    diagnostics.append(f"Skipped unreadable file: {rel} ({error.__class__.__name__})")
                    continue
                digest = hashlib.sha256(raw).hexdigest()
                candidates[rel] = DiscoveredFile(
                    relative_path=rel,
                    path=path,
                    digest=digest,
                    size=size,
                    module_names=module_names_for(rel, src_layout=layout["src_layout"]),
                )
    files = sorted(candidates.values(), key=lambda item: item.relative_path)
    return files, diagnostics