"""Tests for ``contract.validate_against_schema``."""
from __future__ import annotations

from sfa.config import SFAError
from sfa.contract import validate_against_schema


def test_validate_none_level_skips() -> None:
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
    assert validate_against_schema({"x": "not an int"}, schema, "none") == []


def test_validate_empty_schema_no_constraint() -> None:
    assert validate_against_schema({"anything": 1}, {}, "strict") == []
    assert validate_against_schema(42, {}, "lenient") == []


def test_validate_valid_instance_passes() -> None:
    schema = {
        "type": "object",
        "properties": {"user_id": {"type": "integer"}, "features": {"type": "array"}},
        "required": ["user_id"],
    }
    assert validate_against_schema({"user_id": 1, "features": [1, 2]}, schema, "strict") == []


def test_validate_invalid_instance_returns_messages() -> None:
    schema = {
        "type": "object",
        "properties": {"user_id": {"type": "integer"}},
        "required": ["user_id"],
    }
    errors = validate_against_schema({"user_id": "abc"}, schema, "strict")
    assert len(errors) >= 1
    assert any("user_id" in e for e in errors)


def test_validate_strict_and_lenient_return_same() -> None:
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
    strict_errs = validate_against_schema({"x": "no"}, schema, "strict")
    lenient_errs = validate_against_schema({"x": "no"}, schema, "lenient")
    assert strict_errs == lenient_errs
    assert strict_errs  # non-empty


def test_validate_scalar_schema_against_scalar() -> None:
    # output_schema for `-> int` is {"type": "integer"}
    assert validate_against_schema(42, {"type": "integer"}, "strict") == []
    errs = validate_against_schema("no", {"type": "integer"}, "strict")
    assert errs


def test_validate_missing_required_reports_path() -> None:
    schema = {
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "string"}},
        "required": ["a", "b"],
    }
    errors = validate_against_schema({"a": 1}, schema, "strict")
    # 'b' is required and missing
    assert any("b" in e for e in errors)


def test_validate_invalid_level_raises() -> None:
    try:
        validate_against_schema({}, {"type": "object"}, "bogus")
    except SFAError as exc:
        assert "bogus" in str(exc)
        return
    raise AssertionError("expected SFAError for invalid level")


def test_validate_malformed_schema_raises() -> None:
    # 'type' with an invalid value makes the schema itself invalid.
    bad_schema = {"type": "not_a_real_type"}
    try:
        validate_against_schema(1, bad_schema, "strict")
    except SFAError as exc:
        assert "Schema" in str(exc) or "校验" in str(exc)
        return
    raise AssertionError("expected SFAError for malformed schema")


def test_validate_additional_properties_allowed_by_default() -> None:
    # Inferred input_schema does not forbid extra keys.
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
    # Extra key 'y' is allowed (no additionalProperties: False).
    assert validate_against_schema({"x": 1, "y": "extra"}, schema, "strict") == []
