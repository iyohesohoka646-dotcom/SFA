"""Verify script and module project runs through an installed CLI, without Node."""
import json
from pathlib import Path
import subprocess


def verify_project_delivery(python, command, directory, environment):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    env = dict(environment)
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        env.pop(key, None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONUTF8"] = "1"
    prefix = list(map(str, command)) if isinstance(command, (list, tuple)) else [str(command)]
    cases = []
    for kind in ("script", "module"):
        root = directory / (kind + " 中文 lab")
        package = root / "lab"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "calc.py").write_text("def double(value):\n    X = value * 2\n    return X\n", encoding="utf-8")
        (root / "main.py").write_text("from lab.calc import double\nX = 7\nY = double(X)\nprint(Y)\n", encoding="utf-8")
        (package / "main.py").write_text("from .calc import double\nX = 7\nY = double(X)\nprint(Y)\n", encoding="utf-8")

        def invoke(*args):
            result = subprocess.run([*prefix, "--json", *map(str, args)], cwd=root, env=env,
                                    capture_output=True, text=True, encoding="utf-8", timeout=120)
            if result.returncode:
                raise RuntimeError((result.stderr or result.stdout)[-3000:])
            return json.loads(result.stdout)

        def project(*args):
            return invoke("workbench", "project", *args, "--project", root)

        registered = project("open", root)
        revision = project("index")
        assert revision["files_count"] == 4
        entry = root / "entry.json"
        entry.write_text(json.dumps([{"id": "main", "name": "Main", "kind": kind,
                                     "target": "main.py" if kind == "script" else "lab.main"}]))
        project("entries", "--save", entry)
        assert project("graph", "--view", "data")["project_id"] == registered["id"]
        plan = project("plan", "--entry", "main")
        task = project("run", "--plan", plan["id"])
        assert task["status"] == "completed", task
        exported = root / "evidence.json"
        invoke("research", "export", task["run_id"], "--project", root, "--output", exported)
        evidence = json.loads(exported.read_text(encoding="utf-8"))
        outputs = [s for s in evidence["snapshots"] if s["name"] == "Y"]
        assert any(s["sample"]["values"][0][0] == 14 for s in outputs), outputs
        assert any(s["source"]["path"].replace("\\", "/").endswith("lab/calc.py") for s in evidence["snapshots"])
        cases.append({"kind": kind, "files": 4, "result_value": 14,
                      "cross_module_evidence": True, "run_id": task["run_id"]})
    return {"result": "passed", "python": str(python), "cases": cases}
