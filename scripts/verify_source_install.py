"""Exercise a source-archive install through uv in an isolated tool directory."""
import hashlib
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", help="A source archive or git+URL; defaults to the locally built archive")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    archive = sorted((root / "dist").glob("contract_driven_ai_flow-*.tar.gz"))[-1] if not args.source else None
    source = args.source or str(archive)
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

    invoke(uv, "tool", "install", "--python", sys.executable, source, timeout=300)
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
    receipt = {"installer": "uv tool install", "isolated_tools": True, "ordinary_install_needs_node": False,
               "cli": "passed", "bundled_studio": "passed", "first_use_workspace": "passed",
               "native_shortcuts": "passed", "gui_entry_installed": True, "example": demo["runs"], "result": "passed"}
    github = source.startswith(("git+", "https://"))
    if github:
        installed_python = directory / "tools/contract-driven-ai-flow" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        direct = json.loads(invoke(installed_python, "-c", "import importlib.metadata as m; print(m.distribution('contract-driven-ai-flow').read_text('direct_url.json'))"))
        receipt["source_url"] = source
        if "vcs_info" in direct:
            receipt["source_commit"] = direct["vcs_info"]["commit_id"]
        else:
            receipt["source_archive_hashes"] = direct.get("archive_info", {}).get("hashes", {})
    else:
        tested = Path(source).resolve()
        receipt.update({"source_archive": tested.name, "source_sha256": hashlib.sha256(tested.read_bytes()).hexdigest()})
    filename = "github-validation.json" if github else "source-validation.json"
    (root / ".work" / filename).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
