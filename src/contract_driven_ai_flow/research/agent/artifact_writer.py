"""Explicit bounded materialisation with private atomic files; standard library."""
import os
import uuid
from pathlib import Path


class LimitedFile:
    def __init__(self, stream, maximum):
        self.stream = stream
        self.maximum = maximum
        self.size = 0
        self.closed = False

    def write(self, data):
        if self.size + len(data) > self.maximum:
            raise ValueError("artifact_byte_limit")
        count = self.stream.write(data)
        self.size += count
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
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                target = LimitedFile(stream, min(remaining, self.policy.max_artifact_bytes))
                adapter.save(value, target, self.policy)
                stream.flush()
                os.fsync(stream.fileno())
                actual = target.size
            os.replace(temporary, final)
            self.written += actual
            return final.relative_to(self.root).as_posix(), None
        except (ImportError, ModuleNotFoundError):
            return None, "materialization_dependency_missing"
        except Exception as error:
            return None, "artifact_byte_limit" if type(error) is ValueError and str(error) == "artifact_byte_limit" else "materialization_failed:" + type(error).__name__
        finally:
            temporary.unlink(missing_ok=True)
