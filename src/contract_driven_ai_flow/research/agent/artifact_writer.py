"""Explicit bounded materialisation with private atomic files; standard library."""
import os
import hashlib
import json
import uuid
from pathlib import Path


class LimitedFile:
    def __init__(self, stream, maximum):
        self.stream = stream
        self.maximum = maximum
        self.size = 0
        self.closed = False
        self.digest = hashlib.sha256()

    def write(self, data):
        if self.size + len(data) > self.maximum:
            raise ValueError("artifact_byte_limit")
        count = self.stream.write(data)
        self.size += count
        self.digest.update(data[:count])
        return count

    def tell(self):
        return self.size

    def flush(self):
        self.stream.flush()

    def writable(self):
        return True


class ArtifactWriter:
    def __init__(self, root: Path, policy):
        self.root = Path(root).resolve()
        self.policy = policy
        self.written = 0

    def save(self, value, adapter, descriptor):
        extension = getattr(adapter, "artifact_extension", "")
        if "materialize" not in descriptor.get("capabilities", []) or extension not in (".npy", ".arrow"):
            return None, "materialization_unsupported"
        estimated = descriptor.get("nbytes")
        if type(estimated) is not int or estimated < 0:
            return None, "materialization_size_unknown"
        if estimated + 4096 > self.policy.max_artifact_bytes:
            return None, "artifact_byte_limit"
        remaining = self.policy.max_run_bytes - self.written
        if estimated + 4096 > remaining:
            return None, "run_byte_limit"
        folder = self.root / "artifacts"
        folder.mkdir(parents=True, exist_ok=True)
        identifier = uuid.uuid4().hex
        final = folder / (identifier + extension)
        temporary = folder / (identifier + ".partial")
        committed = False
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                target = LimitedFile(stream, min(remaining, self.policy.max_artifact_bytes))
                metadata = adapter.save(value, target, self.policy) or {}
                stream.flush()
                os.fsync(stream.fileno())
                actual = target.size
            os.replace(temporary, final)
            receipt = {'schema_version': 2, 'sha256': target.digest.hexdigest(), 'bytes': actual,
                'shape': descriptor.get('shape'), 'dtype': descriptor.get('dtype'), 'metadata': metadata}
            receipt_data = json.dumps(receipt, allow_nan=False, ensure_ascii=False).encode('utf-8')
            if actual + len(receipt_data) > remaining or actual + len(receipt_data) > self.policy.max_artifact_bytes:
                final.unlink()
                return None, 'artifact_byte_limit'
            receipt_temp = final.with_suffix(final.suffix + '.meta.partial')
            receipt_path = final.with_suffix(final.suffix + '.meta.json')
            try:
                with os.fdopen(os.open(receipt_temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
                    stream.write(receipt_data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(receipt_temp, receipt_path)
            finally:
                receipt_temp.unlink(missing_ok=True)
            self.written += actual + len(receipt_data)
            committed = True
            return final.relative_to(self.root).as_posix(), None
        except (ImportError, ModuleNotFoundError):
            return None, "materialization_dependency_missing"
        except Exception as error:
            return None, "artifact_byte_limit" if type(error) is ValueError and str(error) == "artifact_byte_limit" else "materialization_failed:" + type(error).__name__
        finally:
            temporary.unlink(missing_ok=True)
            if not committed:
                final.unlink(missing_ok=True)
                final.with_suffix(final.suffix + '.meta.json').unlink(missing_ok=True)
