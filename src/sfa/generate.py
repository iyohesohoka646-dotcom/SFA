"""`sfa generate <module>` orchestration.

Prepares a generation plan (prompt -> LLM -> diff) without touching disk,
then applies it on user acceptance: save the old file as a history
version and write the new content.
"""
from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from . import ai as ai_mod
from . import history as history_mod
from . import llm as llm_mod
from .config import SFAError, find_project_root, load_config
from .topology import find_module


def prepare_generation(root: Path, module_id: str) -> dict[str, Any]:
    """Build a generation plan without writing to disk.

    Returns a dict with keys: module, file_path, old_content, new_content,
    diff, warnings, entry_range.
    """
    root = find_project_root(root)
    module = find_module(root, module_id)
    if module.get("type") != "atomic":
        raise SFAError(
            f"模块 {module_id} 类型为 {module.get('type')}，仅 atomic 模块可生成代码。\n"
            "可操作建议：对复合模块请先 `sfa drill` 进入内部视图，对其子模块生成。"
        )

    cfg = load_config(root)
    source_dir = str(cfg.get("source_dir", "src"))

    client = llm_mod.get_client(cfg)
    system, user = ai_mod.build_prompt(root, module, cfg)
    raw = client.complete(system, user)
    gen_code = ai_mod.extract_code_block(raw)

    import_violations = ai_mod.scan_imports(gen_code, cfg.get("allowed_imports") or [])
    side_warnings = ai_mod.detect_side_effects(gen_code)
    warnings = [f"违规 import：{name}" for name in import_violations] + side_warnings

    file_path = (root / module["path"]).resolve()
    if not file_path.is_file():
        raise SFAError(
            f"模块源文件不存在：{file_path}\n"
            f"相关模块：{module_id}\n"
            "可操作建议：检查 sfa.yml 的 source_dir 与模块 path，或恢复源文件。"
        )
    # Read once as text (normalizes CRLF -> LF), then derive bytes for
    # tree-sitter so locate_entry_range does not re-read the file.
    old_content = file_path.read_text(encoding="utf-8")
    source_bytes = old_content.encode("utf-8")

    start, end = ai_mod.locate_entry_range(root, module, source_dir, source_bytes=source_bytes)
    new_content = _replace_line_range(old_content, start, end, gen_code)

    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    rel_path = module["path"]
    diff_lines = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{rel_path}",
        tofile=f"b/{rel_path}",
    )
    diff = "".join(diff_lines)

    return {
        "module": module,
        "file_path": file_path,
        "old_content": old_content,
        "new_content": new_content,
        "diff": diff,
        "warnings": warnings,
        "entry_range": (start, end),
    }


def apply_generation(root: Path, plan: dict[str, Any]) -> Path:
    """Persist a plan: save history then write new content. Returns the
    history version path."""
    root = find_project_root(root)
    module = plan["module"]
    history_path = history_mod.save_version(root, module["id"], plan["old_content"])
    plan["file_path"].write_text(plan["new_content"], encoding="utf-8")
    return history_path


def _replace_line_range(
    content: str, line_start: int, line_end: int, replacement: str
) -> str:
    """Replace 1-indexed lines [line_start, line_end] with *replacement*.

    All other lines are preserved verbatim.
    """
    lines = content.splitlines(keepends=True)
    # Ensure the replacement ends with a newline so it forms a clean line.
    repl = replacement if replacement.endswith("\n") else replacement + "\n"
    # Handle file without trailing newline gracefully.
    if not lines and line_start == 1 and line_end == 1:
        return repl
    before = lines[: line_start - 1]
    after = lines[line_end:]
    new_lines = before + [repl] + after
    return "".join(new_lines)


__all__ = ["prepare_generation", "apply_generation"]
