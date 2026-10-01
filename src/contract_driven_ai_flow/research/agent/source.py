"""Source identity and Python encoding handling, without editing scripts."""
import hashlib
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
