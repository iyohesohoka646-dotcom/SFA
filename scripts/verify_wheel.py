"""Install a built wheel in an isolated environment and exercise Python-only delivery."""
from pathlib import Path
import json
import hashlib
import os
import subprocess
import sys
import tempfile
import venv
import zipfile
import socket
import time
from urllib.request import Request, urlopen


def main():
    repository = Path(__file__).resolve().parents[1]
    wheel = sorted((repository / "dist").glob("contract_driven_ai_flow-*.whl"))[-1]
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert "contract_driven_ai_flow/static/index.html" in names
        assert any("static/assets/elk-worker" in name for name in names)
        assert any("static/licenses/" in name and "elkjs" in name for name in names)
        assert not any("runs.sqlite3" in name or "/node_modules/" in name for name in names)
    work = repository / ".work"
    work.mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="installed-wheel-", dir=work))
    environment = directory / "venv"
    venv.EnvBuilder(with_pip=True, system_site_packages=False).create(environment)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    binary = environment / ("Scripts/cdaf.exe" if os.name == "nt" else "bin/cdaf")
    env = {**os.environ, "PYTHONUTF8": "1", "CDAF_HOME": str(directory / "user home")}

    def invoke(args, expected=0, timeout=120):
        result = subprocess.run([str(a) for a in args], cwd=directory, env=env, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
        if result.returncode != expected:
            raise RuntimeError(f"{args[0]} exited {result.returncode}: {(result.stderr or result.stdout)[-3000:]}")
        return result.stdout

    invoke([python, "-m", "pip", "--isolated", "install", "--no-user", str(wheel) + "[research,tables,views]"], timeout=300)
    from research_acceptance import verify_research_delivery
    research = verify_research_delivery(python, binary, directory / "research-acceptance", env)
    assert research["version"] in invoke([binary, "--version"])
    installed = json.loads(invoke([python, "-c", 'import sys,json,importlib.metadata as metadata; import contract_driven_ai_flow as pkg; print(json.dumps({"python":sys.version.split()[0],"package_file":pkg.__file__,"dependencies":{name:metadata.version(name) for name in ("typer","pydantic","fastapi","libcst","jsonschema")}}))']))
    assert environment.resolve() in Path(installed["package_file"]).resolve().parents
    records = []
    for name in ("data-pipeline", "business-flow", "nested-composite"):
        root = directory / name
        data = json.loads(invoke([binary, "demo", "--example", name, "--target", root]))
        assert [r["quality"] for r in data["runs"]] == ["passed", "failed"]
        invoke([binary, "check", "--project", root])
        records.append({"example": name, "runs": data["runs"]})
    # HTTP check uses stdlib only. Node, Playwright and TestClient are unnecessary.
    source = '''from pathlib import Path
import contract_driven_ai_flow as pkg
from contract_driven_ai_flow.api import create_app
from contract_driven_ai_flow.storage import Store
app = create_app(Path("data-pipeline"), token="installation-smoke")
assert app.state.session_token == "installation-smoke"
assert Path(pkg.__file__).parent.joinpath("static/index.html").is_file()
assert Store(Path("data-pipeline")).runs()[0]["quality"] == "failed"
print("Bundled Studio and runtime metadata available")'''
    invoke([python, "-c", source])
    with socket.socket() as socket_handle:
        socket_handle.bind(("127.0.0.1", 0))
        port = socket_handle.getsockname()[1]
    launched = json.loads(invoke([binary, "studio", "--project", directory / "data-pipeline", "--port", port, "--background", "--no-open"]))
    state = json.loads((directory / "data-pipeline/.cdaf/studio.json").read_text(encoding="utf-8"))
    try:
        with urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
            index = response.read().decode("utf-8")
        assert "assets/index-" in index
        request = Request(f"http://127.0.0.1:{port}/api/v1/project", headers={"Authorization": "Bearer " + state["token"]})
        with urlopen(request, timeout=3) as response:
            assert len(json.load(response)["project"]["modules"]) == 4
        again = json.loads(invoke([binary, "studio", "--project", directory / "data-pipeline", "--port", port, "--background", "--no-open"]))
        assert again["reused"] and again["pid"] == launched["pid"]
    finally:
        stopped = json.loads(invoke([binary, "studio", "--project", directory / "data-pipeline", "--stop", "--no-open"]))
        assert stopped["stopped"]
    invoke([environment / ("Scripts/sfa.exe" if os.name == "nt" else "bin/sfa"), "check", "--project", directory / "data-pipeline"])
    # Empty-cwd installed launch: no authored project, key, Node or repository import.
    with socket.socket() as socket_handle:
        socket_handle.bind(("127.0.0.1", 0))
        workspace_port = socket_handle.getsockname()[1]
    workspace_service = json.loads(invoke([binary, "studio", "--workspace", "--port", workspace_port, "--no-open"]))
    home = directory / "user home"
    workspace_state = json.loads((home / ".cdaf/studio.json").read_text(encoding="utf-8"))
    try:
        request = Request(f"http://127.0.0.1:{workspace_port}/api/v1/workspace", headers={"Authorization": "Bearer " + workspace_state["token"]})
        with urlopen(request, timeout=5) as response:
            catalogue = json.load(response)
        assert len(catalogue["projects"]) == 1
        assert len(catalogue["capabilities"]["features"]) >= 20
        project = catalogue["projects"][0]
        request = Request(f"http://127.0.0.1:{workspace_port}/p/{project['id']}/api/v1/project", headers={"Authorization": "Bearer " + workspace_state["token"]})
        with urlopen(request, timeout=5) as response:
            assert len(json.load(response)["project"]["modules"]) == 4
        created = json.loads(invoke([binary, "projects", "create", "--name", "Installed blank", "--template", "blank"]))
        assert len(json.loads(invoke([binary, "projects", "list"]))) == 2
        assert json.loads(invoke([binary, "doctor", "-p", created["path"]]))["healthy"]
        shortcuts = json.loads(invoke([binary, "shortcut", "--directory", directory / "shortcuts"]))
        assert len(shortcuts["files"]) == 1 and all(Path(path).is_file() for path in shortcuts["files"])
        assert (environment / ("Scripts/cdaf-studio.exe" if os.name == "nt" else "bin/cdaf-studio")).is_file()
        # The exact module used by the GUI shortcut must reuse the independent server.
        invoke([python, "-m", "contract_driven_ai_flow.launcher", "--home", home, "--no-open"])
        assert json.loads((home / ".cdaf/launcher.json").read_text())["pid"] == workspace_service["pid"]
        invoke([binary, "studio", "--workspace", "--stop", "--no-open"])
        (home / ".cdaf/launcher.json").unlink()
        gui = environment / ("Scripts/cdaf-studio.exe" if os.name == "nt" else "bin/cdaf-studio")
        invoke([gui, "--home", home, "--no-open"])
        deadline = time.monotonic() + 25
        while not (home / ".cdaf/launcher.json").is_file() and time.monotonic() < deadline:
            time.sleep(.1)
        gui_result = json.loads((home / ".cdaf/launcher.json").read_text())
        assert gui_result["reused"] is False
        gui_state = json.loads((home / ".cdaf/studio.json").read_text())
        request = Request(f"http://127.0.0.1:{gui_state['port']}/api/v1/workspace", headers={"Authorization": "Bearer " + gui_state["token"]})
        with urlopen(request, timeout=5) as response:
            assert len(json.load(response)["projects"]) == 2
    finally:
        invoke([binary, "studio", "--workspace", "--stop", "--no-open"])
    receipt = {"wheel": wheel.name, "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(), "isolated_environment": str(directory), "installed": installed, "research": research, "ordinary_install_needs_node": False, "cases": records, "static_asset_count": len([n for n in names if "static/" in n]), "installed_studio_http": "passed", "studio_background_lifecycle": "passed", "first_use_workspace": "passed", "installed_shortcuts": "passed", "windowless_launcher": "passed", "result": "passed"}
    (work / "wheel-validation.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
