"""`sfa init` implementation: scaffold the .sfa/ metadata dir and sfa.yml."""
from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from .config import DEFAULT_CONFIG, SFAError, config_path, sfa_dir

SFA_SUBDIRS = ("modules", "history", "snapshots", "logs", "probes")

PIPELINE_YML = "pipeline.yml"

EMPTY_PIPELINE = "modules: []\npipes: []\n"


def init_project(target: Path | None = None, *, force: bool = False) -> Path:
    """Create the ``.sfa/`` structure and ``sfa.yml`` template under *target*.

    Idempotent: existing files are never overwritten unless ``force`` is set.
    Returns the project root path.
    """
    root = (target or Path.cwd()).resolve()
    root.mkdir(parents=True, exist_ok=True)

    meta = sfa_dir(root)
    meta.mkdir(exist_ok=True)
    for sub in SFA_SUBDIRS:
        (meta / sub).mkdir(exist_ok=True)

    _write_if_absent(meta / PIPELINE_YML, EMPTY_PIPELINE, force)

    cfg = config_path(root)
    if not cfg.exists() or force:
        with cfg.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(DEFAULT_CONFIG, fh, sort_keys=False, allow_unicode=True)

    return root


def _write_if_absent(path: Path, content: str, force: bool) -> None:
    if path.exists() and not force:
        return
    path.write_text(content, encoding="utf-8")


def clean_project(root: Path | None = None) -> Path:
    """Clear extraction cache while preserving authored definitions and evidence."""
    root = (root or Path.cwd()).resolve()
    meta = sfa_dir(root)
    if not meta.is_dir():
        raise SFAError(
            f"未找到 .sfa/ 元数据目录：{meta}\n"
            "可操作建议：请先执行 `sfa init` 初始化项目。"
        )
    cache = (meta / "elements.json").resolve()
    if not cache.is_relative_to(root):
        raise SFAError("Cache path escapes the project")
    cache.unlink(missing_ok=True)
    return root
