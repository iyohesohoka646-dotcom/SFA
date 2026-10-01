"""Collect successful local acceptance receipts and verify the delivered wheel."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import xml.etree.ElementTree as ET
import zipfile


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def main():
    repository = Path(__file__).resolve().parents[1]

    def read(name):
        return json.loads((repository / name).read_text(encoding="utf-8"))

    python_report = ET.parse(repository / ".work/python-tests.xml")
    suites = list(python_report.getroot().iter("testsuite"))
    python = {field: sum(int(s.get(field, "0")) for s in suites)
              for field in ("tests", "failures", "errors", "skipped")}
    python["duration_seconds"] = round(sum(float(s.get("time", "0")) for s in suites), 3)
    assert python["tests"] > 0 and python["failures"] == python["errors"] == python["skipped"] == 0

    browser_report = read(".work/browser-tests.json")
    browser = dict(browser_report["stats"])
    assert browser["expected"] > 0 and browser["unexpected"] == browser["flaky"] == browser["skipped"] == 0
    assert not browser_report["errors"]
    cases = []

    def collect(suite):
        for spec in suite.get("specs", []):
            assert spec["ok"] and all(test["status"] == "expected" for test in spec["tests"])
            cases.append({"title": spec["title"], "file": spec["file"], "line": spec["line"], "result": "passed"})
        for child in suite.get("suites", []):
            collect(child)

    for suite in browser_report["suites"]:
        collect(suite)
    assert len(cases) == browser["expected"]
    browser.update({"cases": cases, "engine": ("Microsoft Edge" if platform.system() == "Windows" else "Chromium") + " / Playwright", "reduced_motion": True})

    wheel_receipt = read(".work/wheel-validation.json")
    wheel = repository / "dist" / wheel_receipt["wheel"]
    assert wheel_receipt["result"] == wheel_receipt["installed_studio_http"] == "passed"
    assert wheel_receipt["studio_background_lifecycle"] == "passed"
    assert digest(wheel.read_bytes()) == wheel_receipt["wheel_sha256"]
    package_paths = []
    for package in ("contract_driven_ai_flow", "sfa"):
        for path in (repository / "src" / package).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and (path.suffix == ".py" or "static" in path.parts or "schemas" in path.parts):
                package_paths.append(path)
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        for path in package_paths:
            assert archive.read(path.relative_to(repository / "src").as_posix()) == path.read_bytes(), path
        static = {path.relative_to(repository / "src").as_posix() for path in package_paths if "static" in path.parts}
        assert {name for name in names if name.startswith("contract_driven_ai_flow/static/") and not name.endswith("/")} == static
        assert not any("runs.sqlite3" in name or "/node_modules/" in name for name in names)
    wheel_public = {key: wheel_receipt[key] for key in ("wheel", "wheel_sha256", "ordinary_install_needs_node", "cases", "static_asset_count", "installed_studio_http", "studio_background_lifecycle", "first_use_workspace", "installed_shortcuts", "windowless_launcher", "result")}
    wheel_public["installed"] = {key: wheel_receipt["installed"][key] for key in ("python", "dependencies")}
    wheel_public["source_and_assets_match"] = True
    wheel_public["verified_package_files"] = len(package_paths)

    examples = read("docs/examples/validation.json")
    assert len(examples["cases"]) == 3
    for example in examples["cases"]:
        assert [run["quality"] for run in example["runs"]] == ["passed", "failed"]
        assert all(run["execution"] == "completed" for run in example["runs"])

    archify = {"adapter": "archify", "result": "not_run", "note": "Optional adapter receipt was not provided in this run."}
    if (repository / ".work/archify-demo.html.validation.json").exists():
        archify = read(".work/archify-demo.html.validation.json")
        archify["validation"].pop("input", None)
        assert archify["validation"]["ok"] and all(check["ok"] for check in archify["validation"]["checks"])

    source_paths = set(package_paths)
    for directory in ("web/src", "web/tests", "web/scripts", "tests", "scripts"):
        source_paths.update(path for path in (repository / directory).rglob("*") if path.is_file() and path.suffix in (".py", ".ts", ".tsx", ".css", ".mjs", ".ps1"))
    source_paths.update(repository.glob("*.cmd"))
    source_paths.update(repository / name for name in ("pyproject.toml", "MANIFEST.in", "web/package.json", "web/package-lock.json", "web/tsconfig.json", "web/vite.config.ts", "web/playwright.config.ts", "web/index.html", ".github/workflows/ci.yml"))
    manifest = {path.relative_to(repository).as_posix(): digest(path.read_bytes()) for path in sorted(source_paths)}
    source_manifest = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    receipt = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "version": "0.2.0", "scope": platform.system() + " local release-candidate acceptance",
        "baseline_revision": "c9a745e851d155b4c5fdede2d6cd2758c530e3c0",
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=repository, text=True).strip(),
        "platform": platform.platform(), "python_version": platform.python_version(),
        "node_version": subprocess.check_output(["node", "--version"], text=True).strip(),
        "python": python, "browser": browser, "wheel": wheel_public,
        "examples": examples, "archify": archify,
        "measurements": {name: read(f"docs/assets/{name}.json") for name in ("browser-performance", "large-graph-performance", "capture-performance")},
        "source_manifest_sha256": digest(source_manifest), "source_manifest": manifest,
        "pending_external_gates": ["cross-platform CI result recorded separately", "live paid-model calls", "default-branch merge, repository rename and PyPI publication"],
    }
    destination = repository / "docs/assets/validation.json"
    destination.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": destination.relative_to(repository).as_posix(), "python_passed": python["tests"], "browser_passed": browser["expected"], "wheel_sha256": wheel_public["wheel_sha256"], "verified_package_files": len(package_paths)}, indent=2))


if __name__ == "__main__":
    main()
