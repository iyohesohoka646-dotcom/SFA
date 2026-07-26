"""Configuration loading and project root discovery for SFA."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

SFA_DIR_NAME = ".sfa"
CONFIG_FILENAME = "sfa.yml"

DEFAULT_CONFIG: dict[str, Any] = {
    "project": {
        "name": "my-sfa-project",
        "language": "python",
    },
    "source_dir": "src",
    "default_visibility": "L2",
    "validation": "strict",
    "allowed_imports": ["json", "math", "typing", "dataclasses"],
    "sensitive_fields": [],
    "ai": {
        "provider": "openai",
        "model": "gpt-4o",
        "api_key_env": "OPENAI_API_KEY",
    },
}


class SFAError(Exception):
    """Base error for SFA. Messages always include a path and an actionable hint."""


def find_project_root(start: Path | None = None) -> Path:
    """Walk upward from *start* (defaults to cwd) until a directory containing
    a ``.sfa/`` metadata dir or a ``sfa.yml`` config is found.

    Raises SFAError with an actionable hint when not found.
    """
    start = Path(start or Path.cwd()).resolve()
    current = start
    while True:
        if (current / SFA_DIR_NAME).is_dir() or (current / CONFIG_FILENAME).is_file():
            return current
        if current == current.parent:
            break
        current = current.parent
    raise SFAError(
        "未找到 SFA 项目根目录（缺少 .sfa/ 或 sfa.yml）。\n"
        "可操作建议：请先在目标目录执行 `sfa init` 初始化项目。"
    )


def config_path(root: Path) -> Path:
    return root / CONFIG_FILENAME


def sfa_dir(root: Path) -> Path:
    return root / SFA_DIR_NAME


def load_config(root: Path | None = None) -> dict[str, Any]:
    """Load and merge ``sfa.yml`` with defaults. Returns a fully-populated dict.

    Missing optional sections fall back to DEFAULT_CONFIG.
    """
    root = root if root is not None else find_project_root()
    path = config_path(root)
    if not path.is_file():
        raise SFAError(
            f"项目配置文件不存在：{path}\n"
            "可操作建议：执行 `sfa init` 生成 sfa.yml，或手动创建后重试。"
        )
    with path.open("r", encoding="utf-8") as fh:
        user_cfg = yaml.safe_load(fh) or {}
    try:
        merged = _deep_merge(DEFAULT_CONFIG, user_cfg)
    except SFAError as exc:
        raise SFAError(f"{exc}\n相关配置文件：{path}") from exc
    return merged


def _deep_merge(
    base: dict[str, Any], override: dict[str, Any], _path: str = ""
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in base.items():
        loc = f"{_path}.{key}" if _path else key
        if isinstance(value, dict):
            sub = override.get(key)
            if sub is None:
                result[key] = value
            elif isinstance(sub, dict):
                result[key] = _deep_merge(value, sub, loc)
            else:
                raise SFAError(
                    f"配置字段 '{loc}' 应为映射（键值对），但得到 {type(sub).__name__}。"
                    "请使用缩进块语法，例如：\n  project:\n    name: my-project"
                )
        elif key in override:
            result[key] = override[key]
        else:
            result[key] = value
    for key, value in override.items():
        if key not in result:
            result[key] = value
    return result
