"""Source identity and Python encoding handling, without editing scripts."""
import hashlib


def source_identity(path, digest, node, role):
    """Shared AST span identity without importing UI/server dependencies."""
    span = ':'.join(str(getattr(node, key, 0)) for key in ('lineno', 'col_offset', 'end_lineno', 'end_col_offset'))
    return hashlib.sha256(f'{path}\0{digest}\0{span}\0{role}'.encode()).hexdigest()[:24]
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
