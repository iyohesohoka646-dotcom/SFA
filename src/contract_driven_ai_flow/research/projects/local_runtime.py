"""Machine-only local runtime settings for project launch references.

Interpreter paths and private environment values live in the host state
directory and are never written into project ``workbench.yaml``, public
plans or HTTP-facing receipts. Project documents only carry symbolic
references (``interpreter_ref`` / ``environment`` names).

Three private stores live under ``<host_root>/.cdaf``:

* ``runtime.json``      - the mutable interpreter map, named environment
  profiles and the maintained legacy single-variable environment map.
* ``runtime_snapshots/`` - opaque, plan-keyed freezes of the exact interpreter
  path and expanded explicit environment values captured at plan time.

Named environment sets let two projects pick distinct values (for example
distinct ``PYTHONPATH``) without sharing a variable.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import threading
from pathlib import Path
from uuid import uuid4


# Stable symbolic name prefix for a migrated legacy ``WorkbenchConfig.interpreter``.
LEGACY_INTERPRETER_PREFIX = "legacy"

SNAPSHOT_DIR = ".cdaf/runtime_snapshots"

MAX_REFERENCE = 128
MAX_ENVIRONMENT_VARIABLES = 64
MAX_ENVIRONMENT_VALUE = 8192
MAX_ENVIRONMENT_TOTAL = 64 * 1024

_REFERENCE_RE = re.compile(r"^[A-Za-z0-9._-]{1," + str(MAX_REFERENCE) + r"}$")
_ENVIRONMENT_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SNAPSHOT_RE = re.compile(r"^[0-9a-f]{32}$")


class RuntimeConflict(RuntimeError):
    """A frozen runtime reference no longer resolves; a replan is required."""


def settings_path(host_root: Path) -> Path:
    return Path(host_root).resolve() / ".cdaf" / "runtime.json"


def load_machine_settings(host_root: Path) -> dict:
    path = settings_path(host_root)
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def save_machine_settings(host_root: Path, settings: dict) -> None:
    """Atomically persist private machine settings (never public documents)."""
    from ...storage import atomic_write_private

    if not isinstance(settings, dict):
        raise ValueError("Machine settings must be an object")
    path = settings_path(host_root)
    atomic_write_private(
        path, json.dumps(settings, ensure_ascii=False, indent=2, sort_keys=True)
    )


# A minimal in-process lock serialises only the read/modify/write of the private
# machine settings file so concurrent writes never drop one another's entry.
# Public resolve calls stay lock-free (no per-request cost).
_settings_lock = threading.RLock()


def _revision(settings: dict) -> int:
    value = settings.get("version")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _bump(settings: dict) -> int:
    """Next machine revision for an in-place write (never lowers the counter)."""
    return _revision(settings) + 1


def _interpreters(settings: dict) -> dict:
    value = settings.get("interpreters")
    return dict(value) if isinstance(value, dict) else {}


def _profiles(settings: dict) -> dict:
    value = settings.get("environments")
    return value if isinstance(value, dict) else {}


def _legacy_environment(settings: dict) -> dict:
    value = settings.get("environment")
    return value if isinstance(value, dict) else {}


def legacy_interpreter_ref(interpreter: str) -> str:
    """Derive a stable symbolic ref from an actual interpreter path.

    The digest keeps distinct legacy interpreters on distinct references so a
    later project's plan can never overwrite an earlier project's executable.
    """
    digest = hashlib.sha256(str(interpreter).encode("utf-8")).hexdigest()[:16]
    return LEGACY_INTERPRETER_PREFIX + "-" + digest


def enroll_interpreter(host_root: Path, reference: str, interpreter: str) -> str:
    """Enroll an interpreter under a stable private symbolic reference.

    The read/modify/write window is guarded so two concurrent enrolments cannot
    lose either entry; the reference is preserved exactly as supplied.
    """
    ref = (reference or "").strip()
    if not ref:
        raise ValueError("Interpreter reference must not be blank")
    with _settings_lock:
        settings = dict(load_machine_settings(host_root))
        interpreters = _interpreters(settings)
        interpreters[ref] = str(interpreter)
        settings["interpreters"] = interpreters
        settings["version"] = _bump(settings)
        save_machine_settings(host_root, settings)
    return ref


def list_machine_references(host_root: Path) -> dict:
    """Names only for a later settings API; private values are never returned."""
    settings = load_machine_settings(host_root)
    interpreters = settings.get("interpreters")
    environment = settings.get("environment")
    return {
        "interpreters": sorted(interpreters) if isinstance(interpreters, dict) else [],
        "environment": sorted(environment) if isinstance(environment, dict) else [],
    }


def _resolve_interpreter(settings: dict, interpreter_ref: str | None) -> str:
    interpreters = _interpreters(settings)
    reference = (interpreter_ref or "").strip()
    if not reference:
        if "default" in interpreters:
            return str(interpreters["default"])
        return sys.executable
    if reference not in interpreters:
        raise ValueError("Unknown interpreter reference: " + reference)
    return str(interpreters[reference])


def resolve_interpreter(host_root: Path, interpreter_ref: str | None) -> str:
    """Resolve a symbolic interpreter reference; default to this interpreter."""
    with _settings_lock:
        return _resolve_interpreter(load_machine_settings(host_root), interpreter_ref)


def _expand_environment(settings: dict, names) -> dict:
    """Expand named environment sets plus legacy single-variable references.

    Merging is deterministic and ordered-free: duplicate variables carrying the
    same value are de-duplicated, while conflicting values are an explicit
    error (never an ordered override). Unknown or ambiguous references fail.
    """
    profiles = _profiles(settings)
    legacy = _legacy_environment(settings)
    resolved: dict = {}
    for raw_name in names or ():
        name = str(raw_name)
        in_profile = name in profiles
        in_legacy = name in legacy
        if in_profile and in_legacy:
            raise ValueError("Ambiguous environment reference: " + name)
        if in_profile:
            mapping = profiles[name]
            if not isinstance(mapping, dict):
                raise ValueError("Environment profile is invalid: " + name)
            items = [(str(key), str(value)) for key, value in mapping.items()]
        elif in_legacy:
            items = [(name, str(legacy[name]))]
        else:
            raise ValueError("Unknown environment reference: " + name)
        for key, value in items:
            if key in resolved and resolved[key] != value:
                raise ValueError(
                    "Conflicting environment value for " + key + "; use one profile"
                )
            resolved[key] = value
    return resolved


def resolve_environment(host_root: Path, names) -> dict:
    """Resolve symbolic environment references into private values."""
    with _settings_lock:
        return _expand_environment(load_machine_settings(host_root), names)


def environment_summary(interpreter_ref: str | None, names) -> dict:
    """Public, secret-free description frozen onto a plan."""
    return {
        "interpreter_ref": (interpreter_ref or "").strip(),
        "environment": [str(name) for name in (names or ())],
    }


# -- sanitized state and validated writes -----------------------------
def _validate_reference(reference) -> str:
    text = str(reference or "").strip()
    if not _REFERENCE_RE.fullmatch(text):
        raise ValueError(
            "Runtime reference must be 1-128 characters of letters, digits, "
            "'.', '_' or '-'"
        )
    return text


def _validate_interpreter_path(raw) -> str:
    text = str(raw if raw is not None else "")
    if not text or "\x00" in text:
        raise ValueError("Interpreter path is required")
    path = Path(text)
    if not path.is_absolute():
        raise ValueError("Interpreter path must be absolute")
    if not path.is_file():
        raise ValueError("Interpreter path does not exist")
    return str(path)


def _validate_environment_values(values) -> dict:
    if not isinstance(values, dict):
        raise ValueError("Environment values must be an object")
    if len(values) > MAX_ENVIRONMENT_VARIABLES:
        raise ValueError("An environment profile allows at most 64 variables")
    total = 0
    clean: dict = {}
    for key, value in values.items():
        name = str(key)
        if not _ENVIRONMENT_NAME_RE.fullmatch(name):
            raise ValueError("Invalid environment variable name: " + name)
        if not isinstance(value, str):
            raise ValueError("Environment value must be a string")
        if "\x00" in value:
            raise ValueError("Environment value must not contain NUL")
        if len(value) > MAX_ENVIRONMENT_VALUE:
            raise ValueError("Environment value exceeds 8192 characters")
        total += len(name) + len(value)
        clean[name] = value
    if total > MAX_ENVIRONMENT_TOTAL:
        raise ValueError("Environment profile exceeds 64 KiB in total")
    return clean


def runtime_state(host_root: Path) -> dict:
    """Fresh, sanitized machine runtime state (never returns private values)."""
    settings = load_machine_settings(host_root)
    profiles = _profiles(settings)
    return {
        "revision": _revision(settings),
        "interpreters": [
            {"id": key} for key in sorted(_interpreters(settings))
        ],
        "environments": [
            {
                "id": key,
                "keys": sorted(
                    str(name)
                    for name in (
                        profiles[key] if isinstance(profiles[key], dict) else {}
                    )
                ),
            }
            for key in sorted(profiles)
        ],
        "legacy_environment": sorted(_legacy_environment(settings)),
    }


def _expect_revision(settings: dict, expected_revision) -> None:
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
        raise ValueError("expected_revision must be an integer")
    if _revision(settings) != expected_revision:
        raise RuntimeConflict(
            "Runtime settings revision conflict; reload before saving"
        )


def set_interpreter_reference(
    host_root: Path, reference: str, path, expected_revision: int
) -> dict:
    ref = _validate_reference(reference)
    resolved = _validate_interpreter_path(path)
    with _settings_lock:
        settings = dict(load_machine_settings(host_root))
        _expect_revision(settings, expected_revision)
        interpreters = _interpreters(settings)
        interpreters[ref] = resolved
        settings["interpreters"] = interpreters
        settings["version"] = _bump(settings)
        save_machine_settings(host_root, settings)
    return runtime_state(host_root)


def set_environment_reference(
    host_root: Path, reference: str, values, expected_revision: int
) -> dict:
    ref = _validate_reference(reference)
    clean = _validate_environment_values(values)
    with _settings_lock:
        settings = dict(load_machine_settings(host_root))
        _expect_revision(settings, expected_revision)
        profiles = dict(_profiles(settings))
        profiles[ref] = clean
        settings["environments"] = profiles
        settings["version"] = _bump(settings)
        save_machine_settings(host_root, settings)
    return runtime_state(host_root)


# -- private plan-keyed snapshots -------------------------------------
def _snapshot_path(host_root: Path, snapshot_id: str) -> Path:
    return Path(host_root).resolve() / SNAPSHOT_DIR / (snapshot_id + ".json")


def freeze_runtime(
    host_root: Path,
    *,
    project_id: str,
    plan_id: str,
    interpreter_ref,
    environment_names,
) -> str:
    """Freeze the exact interpreter path and expanded explicit environment.

    Returns an opaque, plan-keyed snapshot id; the raw values only ever live in
    the private host state, never on the public plan.
    """
    reference = (interpreter_ref or "").strip()
    names = [str(name) for name in (environment_names or ())]
    with _settings_lock:
        settings = load_machine_settings(host_root)
        interpreter = _resolve_interpreter(settings, reference)
        environment = _expand_environment(settings, names)
    snapshot = {
        "protocol_version": 1,
        "project_id": str(project_id),
        "plan_id": str(plan_id),
        "interpreter_ref": reference,
        "interpreter": interpreter,
        "environment_refs": names,
        "environment": environment,
    }
    payload = json.dumps(
        snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    snapshot_id = uuid4().hex
    path = _snapshot_path(host_root, snapshot_id)
    if path.exists():
        if path.read_text(encoding="utf-8") != payload:
            raise RuntimeConflict("Frozen runtime snapshot identity conflict; replan")
    else:
        from ...storage import atomic_write_private

        atomic_write_private(path, payload)
    return snapshot_id


def load_runtime_snapshot(host_root: Path, snapshot_id) -> dict:
    text = str(snapshot_id or "")
    if not _SNAPSHOT_RE.fullmatch(text):
        raise RuntimeConflict(
            "Project plan has no frozen runtime snapshot; prepare it again"
        )
    path = _snapshot_path(host_root, text)
    if not path.is_file():
        raise RuntimeConflict(
            "Frozen runtime snapshot is unavailable; prepare the plan again"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeConflict("Frozen runtime snapshot is invalid; replan")
    return data


def verify_runtime_snapshot(
    host_root: Path, snapshot_id, *, project_id=None, plan_id=None
) -> dict:
    """Re-resolve the frozen refs and require the exact frozen values.

    Returns the frozen interpreter path and expanded environment only after the
    current machine references still resolve to them; any relevant change or a
    missing reference raises an explicit runtime conflict before any launch.
    """
    data = load_runtime_snapshot(host_root, snapshot_id)
    if project_id is not None and data.get("project_id") != str(project_id):
        raise RuntimeConflict("Frozen runtime snapshot belongs to another project; replan")
    if plan_id is not None and data.get("plan_id") != str(plan_id):
        raise RuntimeConflict("Frozen runtime snapshot belongs to another plan; replan")
    try:
        with _settings_lock:
            settings = load_machine_settings(host_root)
            interpreter = _resolve_interpreter(settings, data.get("interpreter_ref"))
            environment = _expand_environment(settings, data.get("environment_refs") or [])
    except ValueError as error:
        raise RuntimeConflict("Frozen runtime reference is unavailable; replan") from error
    if interpreter != data.get("interpreter"):
        raise RuntimeConflict(
            "Interpreter reference changed after planning; prepare the project again"
        )
    if environment != (data.get("environment") or {}):
        raise RuntimeConflict(
            "Environment reference changed after planning; prepare the project again"
        )
    return {"interpreter": interpreter, "environment": environment}
