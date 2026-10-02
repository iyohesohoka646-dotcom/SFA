"""Source identity and Python encoding handling, without editing scripts."""
import hashlib


def source_identity(path, digest, node, role):
    """Shared AST span identity without importing UI/server dependencies."""
    span = ':'.join(str(getattr(node, key, 0)) for key in ('lineno', 'col_offset', 'end_lineno', 'end_col_offset'))
    return hashlib.sha256(f'{path}\0{digest}\0{span}\0{role}'.encode()).hexdigest()[:24]


def logical_binding(source, scope, name):
    path = source.get('path', '') if isinstance(source, dict) else ''
    lexical = '<module>' if scope in ('main', '<module>') else scope.rsplit(':', 1)[0]
    return f'{path}::{lexical}::{name}'


def matches_probe(spec, snapshot):
    """Same matching in isolated agent gates and supervisor checks."""
    from fnmatch import fnmatchcase
    logical = snapshot.get('logical_key') or logical_binding(snapshot.get('source'), snapshot.get('scope_id', 'main'), snapshot['name'])
    if logical in spec.get('excluded_keys', []):
        return False
    keys = spec.get('target_keys')
    if keys is not None:
        return logical in keys
    binding = spec.get('binding', '*')
    return binding in (snapshot.get('id'), logical) or fnmatchcase(snapshot['name'], binding) or fnmatchcase(snapshot['binding_id'], binding)
import io
import tokenize
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SourceFile:
    path: str
    text: str
    digest: str


def read_source(path: Path) -> SourceFile:
    resolved = Path(path).resolve(strict=True)
    raw = resolved.read_bytes()
    encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
    return SourceFile(str(resolved), raw.decode(encoding), hashlib.sha256(raw).hexdigest())
