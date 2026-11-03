"""Run the measured browser fixture and save exact machine-local UI timings."""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).resolve().parents[1]
result = subprocess.run(["npm.cmd" if os.name == "nt" else "npm", "run", "test:e2e", "--", "research-performance"], cwd=root / "web")
if result.returncode:
    raise SystemExit(result.returncode)
report = json.loads((root / ".work/browser-tests.json").read_text(encoding="utf-8"))
measurements = []
def visit(suites):
    for suite in suites:
        for spec in suite.get("specs", []):
            for test in spec.get("tests", []):
                for result in test.get("results", []):
                    for attachment in result.get("attachments", []):
                        if attachment["name"] == "paint-latency.json":
                            import base64
                            content = Path(attachment["path"]).read_text() if attachment.get("path") else base64.b64decode(attachment["body"]).decode()
                            measurements.append(json.loads(content))
        visit(suite.get("suites", []))
visit(report["suites"])
if not measurements:
    raise RuntimeError("Browser test did not produce timing evidence")
output = {"measured_at": datetime.now(timezone.utc).isoformat(), "fixture": {"logical_values":1000,"maximum_visible_nodes":80,"stored_events":10000},
    "browser": "Edge" if sys.platform=="win32" else "Chromium", "measurements":measurements,
    "scope":"Synthetic UI history fixture; excludes scientific computation and initial server preparation"}
(root / "docs/assets/research-workbench-performance.json").write_text(json.dumps(output, ensure_ascii=False, indent=2),encoding="utf-8")
