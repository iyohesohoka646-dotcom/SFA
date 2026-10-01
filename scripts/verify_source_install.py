"""Exercise a source-archive install through uv in an isolated tool directory."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen


def main():
    root = Path(__file__).resolve().parents[1]
    archive = sorted((root / "dist").glob("contract_driven_ai_flow-*.tar.gz"))[-1]
    uv = shutil.which("uv")
    if not uv:
        raise SystemExit("This optional source-install check requires uv")
    directory = Path(tempfile.mkdtemp(prefix="source-install-", dir=root / ".work"))
    env = {**os.environ, "PYTHONUTF8": "1", "UV_TOOL_DIR": str(directory / "tools"),
           "UV_TOOL_BIN_DIR": str(directory / "bin"), "CDAF_HOME": str(directory / "home")}

    def invoke(*args, timeout=120):
        result = subprocess.run([str(arg) for arg in args], cwd=directory, env=env,
                                capture_output=True, text=True, encoding="utf-8", timeout=timeout)
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout)[-3000:])
        return result.stdout

    invoke(uv, "tool", "install", "--python", sys.executable, archive, timeout=300)
    extension = ".exe" if os.name == "nt" else ""
    binary = directory / "bin" / ("cdaf" + extension)
    assert "0.2.0" in invoke(binary, "--version")
    assert (directory / "bin" / ("cdaf-studio" + extension)).is_file()
    diagnosis = json.loads(invoke(binary, "--json", "doctor"))
    assert diagnosis["healthy"]
    demo = json.loads(invoke(binary, "--json", "demo", "--target", directory / "demo"))
    assert [run["quality"] for run in demo["runs"]] == ["passed", "failed"]
    launched = json.loads(invoke(binary, "--json", "studio", "--workspace", "--no-open"))
    try:
        state = json.loads((directory / "home/.cdaf/studio.json").read_text(encoding="utf-8"))
        address = f"http://127.0.0.1:{launched['port']}/api/v1/workspace"
        with urlopen(Request(address, headers={"Authorization": "Bearer " + state["token"]}), timeout=5) as response:
            workspace = json.load(response)
        assert len(workspace["projects"]) == 1 and workspace["projects"][0]["available"]
        assert len(workspace["capabilities"]["features"]) >= 20
        shortcuts = json.loads(invoke(binary, "--json", "shortcut", "--directory", directory / "shortcuts"))
        assert all(Path(path).is_file() for path in shortcuts["files"])
    finally:
        invoke(binary, "--json", "studio", "--workspace", "--stop", "--no-open")
    receipt = {"source_archive": archive.name, "source_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
               "installer": "uv tool install", "isolated_tools": True, "ordinary_install_needs_node": False,
               "cli": "passed", "bundled_studio": "passed", "first_use_workspace": "passed",
               "native_shortcuts": "passed", "gui_entry_installed": True, "example": demo["runs"], "result": "passed"}
    (root / ".work/source-validation.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
