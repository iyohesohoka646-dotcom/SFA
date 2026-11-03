"""P2b project runtime helpers: freeze, verify and point at indexed sources.

Manifests are compact (path -> digest/identity) and immutable. They are stored
separately from the job document; the job JSON only carries a manifest pointer,
so the 128 KiB job cap survives a large project. No object graphs are frozen.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ...storage import atomic_write
from ..agent.source import read_source

MANIFEST_DIR = ".cdaf/research/projects/manifests"
MAX_MANIFEST_BYTES = 32 * 1024 * 1024


def manifest_file(project_root: Path, manifest_id: str) -> Path:
    return Path(project_root).resolve() / MANIFEST_DIR / (manifest_id + ".json")


def build_manifest(project_root, project_id: str, revision_id: str, units) -> dict:
    """Compact path -> {digest, file_id, project, revision} freeze record."""
    root = Path(project_root).resolve()
    manifest: dict = {}
    for unit in units:
        path = str((root / unit.relative_path).resolve())
        manifest[path] = {
            "digest": unit.digest,
            "file_id": unit.id,
            "relative_path": unit.relative_path,
            "project_id": project_id,
            "project_revision_id": revision_id,
        }
    return manifest


def save_manifest(project_root, manifest: dict) -> str:
    payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(payload.encode("utf-8")) > MAX_MANIFEST_BYTES:
        raise ValueError("Project manifest is too large")
    manifest_id = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
    target = manifest_file(project_root, manifest_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise RuntimeError("Project manifest identity conflict; refusing to overwrite")
    else:
        atomic_write(target, payload)
    return manifest_id


def load_manifest(project_root, manifest_id: str) -> dict:
    if not manifest_id:
        raise ValueError("Project plan has no frozen manifest")
    path = manifest_file(project_root, manifest_id)
    if not path.is_file():
        raise RuntimeError("Project manifest is unavailable; index and plan again")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise RuntimeError("Project manifest is invalid")
    return manifest


def verify_manifest(project_root, manifest: dict) -> None:
    """Re-read every frozen digest immediately before an actual launch."""
    root = Path(project_root).resolve()
    for raw_path, info in manifest.items():
        path = Path(raw_path)
        if not path.is_file():
            raise RuntimeError(
                "Project source is missing: " + str(info.get("relative_path") or path)
            )
        source = read_source(path)
        if source.digest != info.get("digest"):
            raise RuntimeError(
                "Project source changed before launch: "
                + str(info.get("relative_path") or path)
            )
        try:
            path.resolve().relative_to(root)
        except ValueError:
            raise RuntimeError("Project manifest escapes the project root")


def resolve_entry(units, configuration) -> dict:
    """Inert entry validation against the indexed revision (never imports)."""
    kind = getattr(configuration, "kind", "script")
    target = (getattr(configuration, "target", "") or "").strip()
    if not target:
        raise ValueError("Run configuration requires a target")
    by_path = {unit.relative_path: unit for unit in units}
    if kind == "script":
        relative = target.replace("\\", "/").lstrip("./")
        if relative not in by_path:
            raise ValueError(
                "Entry script is not part of the indexed revision: " + target
            )
        return {"kind": "script", "target": by_path[relative].relative_path}
    modules: dict = {}
    for unit in units:
        for name in unit.module_names:
            modules.setdefault(name, unit)
    normalized = target.replace("/", ".").removesuffix(".py")
    if normalized not in modules:
        raise ValueError(
            "Entry module is not part of the indexed revision: " + target
        )
    return {"kind": "module", "target": normalized}


def resolve_cwd(project_root, relative: str | None) -> Path:
    """Project cwd is explicitly relative to the project root."""
    root = Path(project_root).resolve()
    if relative in (None, "", "."):
        return root
    candidate = Path(relative)
    if candidate.is_absolute():
        raise ValueError("Project working directory must be relative to the project root")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError("Project working directory escapes the project root")
    return resolved