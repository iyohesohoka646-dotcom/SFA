"""Publish portable scientific acceptance evidence only from successful receipts."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform

from contract_driven_ai_flow import __version__


def main():
    root = Path(__file__).resolve().parents[1]

    def read(relative):
        return json.loads((root / relative).read_text(encoding="utf-8"))

    release = read("docs/assets/validation.json")
    wheel = read(".work/wheel-validation.json")
    source = read(".work/source-validation.json")
    desktop = read("docs/assets/research-desktop-validation.json")
    assert release["version"] == wheel["research"]["version"] == source["research"]["version"] == desktop["core_version"] == __version__
    assert release["python"]["failures"] == release["python"]["errors"] == release["python"]["skipped"] == 0
    assert release["browser"]["unexpected"] == release["browser"]["flaky"] == release["browser"]["skipped"] == 0
    assert any("research-journey:" in case["title"] for case in release["browser"]["cases"])
    assert wheel["result"] == source["result"] == desktop["result"] == "passed"
    assert all(desktop[key] for key in ("installed", "window_close", "port_released", "own_script", "matrix_and_anomaly",
        "probe_preview_and_save", "explanation_scope", "shared_cli_history", "offline_report_privacy", "source_preserved"))
    installer = root / "dist/desktop" / f"Scientific Dataflow Inspector Setup {__version__}.exe"
    assert installer.is_file()
    soak = read("docs/assets/research-soak-comparison.json")
    live_stream = read("docs/assets/research-stream-performance.json")
    assert live_stream["status"] == "completed" and live_stream["p95_ms"] <= 250
    assert live_stream["rendered_versions"] >= 100 and live_stream["duration_seconds"] >= 60
    receipt = {
        "recorded_at": datetime.now(timezone.utc).isoformat(), "version": __version__,
        "display_name": "Scientific Dataflow Inspector", "platform": platform.platform(),
        "python": release["python"], "browser": release["browser"],
        "scientific_install": wheel["research"], "source_install": source,
        "wheel_sha256": wheel["wheel_sha256"],
        "desktop": {key: value for key, value in desktop.items() if key not in ("backend_pid", "run_id")},
        "installer": {"filename": installer.name, "sha256": hashlib.sha256(installer.read_bytes()).hexdigest(),
            "signing": "unsigned local Windows candidate"},
        "ui_performance": read("docs/assets/research-workbench-performance.json"),
        "live_soak_comparison": soak,
        "live_stream": live_stream,
        "source_manifest_sha256": release["source_manifest_sha256"],
        "unverified": ["macOS/Linux native desktop installation and window lifetime", "GPU/sparse/distributed/non-Python built-in adapters",
            "live paid-model inference", "remote publication or default-branch merge"],
    }
    destination = root / "docs/assets/research-validation.json"
    destination.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": destination.relative_to(root).as_posix(), "python_passed": receipt["python"]["tests"],
        "browser_passed": receipt["browser"]["expected"], "installer_sha256": receipt["installer"]["sha256"]}, indent=2))


if __name__ == "__main__":
    main()
