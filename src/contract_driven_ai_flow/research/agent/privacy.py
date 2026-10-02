"""Bounded primitive encoding; never stringify unrecognised user objects."""
import math
import re
import sys
from datetime import date, datetime, timedelta


def type_name(value):
    cls = type(value)
    return type.__getattribute__(cls, "__module__") + "." + type.__getattribute__(cls, "__qualname__")


def sensitive(name: str, fields=()) -> bool:
    folded = name.casefold()
    return any(f.casefold() in folded for f in (*fields, "password", "secret", "api_key", "access_token", "authorization"))


def clean_text(value: str, limit: int = 512) -> str:
    value = value[:limit]
    value = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[REDACTED_EMAIL]", value)
    # Match an identifier once at its boundary, then classify it. Searching an
    # unanchored greedy identifier for an embedded credential word was quadratic
    # even for ordinary long strings with no credentials.
    def credential(prefix):
        return any(word in prefix.casefold().replace('-', '_') for word in ('api_key', 'apikey', 'password', 'token', 'secret', 'authorization'))
    prefix = r"(?i)(?<![\w.-])([\"']?[A-Za-z0-9_.-]+[\"']?\s*[:=]\s*)(?:[rbuf]*)(\"\"\"[\s\S]*?(?:\"\"\"|$)|'''[\s\S]*?(?:'''|$)|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')"
    value = re.sub(prefix, lambda m: m.group(1) + '"[REDACTED]"' + '\n' * m.group(2).count('\n') if credential(m.group(1)) else m.group(0), value)
    unquoted = r"(?i)(?<![\w.-])([\"']?[A-Za-z0-9_.-]+[\"']?\s*[:=]\s*)([^\s,;\"']+)"
    value = re.sub(unquoted, lambda m: m.group(1) + '[REDACTED]' if credential(m.group(1)) else m.group(0), value)
    return re.sub(r"(?i)(bearer\s+)[^\s,;\"']+", r"\1[REDACTED]", value)


def finite_number(value):
    value = float(value)
    return value if math.isfinite(value) else None


def cell(value, depth: int = 0):
    """Type tags preserve complex/non-finite/datetime values in strict JSON."""
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is float:
        if math.isfinite(value):
            return value
        return {"type": "nonfinite", "value": "nan" if math.isnan(value) else ("inf" if value > 0 else "-inf")}
    if type(value) is str:
        text = clean_text(value)
        return {"type": "truncated-string", "value": text, "length": len(value)} if len(value) > 512 else text
    if type(value) is complex:
        return {"type": "complex", "real": cell(value.real), "imag": cell(value.imag)}
    if type(value) in (datetime, date):
        return {"type": "datetime", "value": value.isoformat()}
    if type(value) is timedelta:
        return {"type": "timedelta", "seconds": value.total_seconds()}
    if type(value) is tuple and depth < 2:
        return [cell(v, depth + 1) for v in value[:8]]
    pd = sys.modules.get("pandas")
    if pd is not None:
        if value is pd.NA or value is pd.NaT:
            return None
        if type(value) is pd.Timestamp:
            return {"type": "datetime", "value": value.isoformat()}
        if type(value) is pd.Timedelta:
            return {"type": "timedelta", "seconds": value.total_seconds()}
    np = sys.modules.get("numpy")
    if np is not None and isinstance(value, np.generic):
        if value.dtype.kind in "mM":
            return None if np.isnat(value) else {"type": "datetime" if value.dtype.kind == "M" else "timedelta", "value": str(value)}
        if value.dtype.kind in "biufcUS":
            return cell(value.item(), depth)
    return {"type": "unavailable", "type_name": type_name(value)}


def sanitize_json(value, fields=(), depth=0, *, string_limit=16384):
    if depth > 16:
        raise ValueError("Adapter JSON exceeds maximum depth")
    if type(value) is dict:
        if len(value) > 4096:
            raise ValueError("Adapter JSON has too many fields")
        return {k: "[REDACTED]" if sensitive(k, fields) else sanitize_json(v, fields, depth + 1, string_limit=string_limit)
                for k, v in value.items() if type(k) is str and len(k) <= 256}
    if type(value) in (list, tuple):
        if len(value) > 65536:
            raise ValueError("Adapter JSON has too many elements")
        return [sanitize_json(v, fields, depth + 1, string_limit=string_limit) for v in value]
    if type(value) is float and not math.isfinite(value):
        raise ValueError("Adapter returned non-finite JSON")
    if value is None or type(value) in (bool, int, float):
        return value
    if type(value) is str:
        return clean_text(value, string_limit)
    raise TypeError("Adapter returned a non-JSON value")
