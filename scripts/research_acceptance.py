"""Exercise scientific delivery through an explicitly selected installed CLI."""
from pathlib import Path
import hashlib
import json
import os
import subprocess


def verify_research_delivery(python, command, directory, environment):
    environment = {key: value for key, value in environment.items() if key.upper() in {
        "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "USERPROFILE", "HOME",
        "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "LANG", "LC_ALL", "PYTHONUTF8", "CDAF_HOME",
    }}
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    prefix = [str(a) for a in command] if isinstance(command, (tuple, list)) else [str(command)]

    def invoke(arguments, expected=0):
        process = subprocess.run([str(a) for a in arguments], cwd=directory, env=environment,
                                 capture_output=True, text=True, encoding="utf-8", timeout=120)
        if process.returncode != expected:
            raise RuntimeError(f"Scientific acceptance exited {process.returncode}: {(process.stderr or process.stdout)[-2000:]}")
        return process.stdout

    installed = json.loads(invoke([python, "-c", "import json,sys,pathlib,contract_driven_ai_flow as pkg; print(json.dumps({'version':pkg.__version__,'templates':str(pathlib.Path(pkg.__file__).parent/'templates/research-analysis'),'python':sys.version.split()[0]}))"]))
    template = Path(installed["templates"]) / "analysis.py"
    original = hashlib.sha256(template.read_bytes()).hexdigest()
    cases = []
    for failure in ("none", "nan", "dimension"):
        project = directory / ("analysis-" + failure)
        expected = 1 if failure == "dimension" else 0
        record = json.loads(invoke([*prefix, "--json", "observe", template, "--python", python,
                                   "--project", project, "--arg=--failure", "--arg=" + failure], expected))
        assert record["status"] == ("failed" if expected else "completed")
        if failure == "none":
            assert record["summary"]["quality"] == "pass"
        elif failure == "nan":
            assert record["summary"]["quality"] == "fail"
        cases.append({"failure": failure, "id": record["id"], "status": record["status"],
                      "quality": record["summary"]["quality"], "exit_code": expected})
    assert hashlib.sha256(template.read_bytes()).hexdigest() == original

    independent = directory / "scientific-env"
    invoke([python, "-m", "venv", "--without-pip", independent])
    scientific_python = independent / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    script = directory / "independent.py"
    script.write_text("import importlib.util\nassert importlib.util.find_spec('fastapi') is None\nassert importlib.util.find_spec('pydantic') is None\nX = 42\n", encoding="utf-8")
    project = directory / "independent-evidence"
    record = json.loads(invoke([*prefix, "--json", "observe", script, "--python", scientific_python, "--project", project]))
    assert record["status"] == "completed"
    evidence = directory / "independent.json"
    invoke([*prefix, "--json", "research", "export", record["id"], "--project", project, "--output", evidence])
    data = json.loads(evidence.read_text(encoding="utf-8"))
    value = next(s for s in data["snapshots"] if s["name"] == "X")["sample"]["values"][0][0]
    assert value == 42

    private_script = directory / "private_table.py"
    private_script.write_text("import pandas as pd\nframe = pd.DataFrame({'value':[1,2], 'email':['lab-sensitive@example.org','another@example.org']})\n", encoding="utf-8")
    project = directory / "private-evidence"
    record = json.loads(invoke([*prefix, "--json", "observe", private_script, "--project", project]))
    report = directory / "private-evidence.html"
    invoke([python, "-c", "from pathlib import Path; import sys; from contract_driven_ai_flow.research.service import ResearchService; from contract_driven_ai_flow.research.export import offline_report\nwith ResearchService(Path(sys.argv[1])) as service: Path(sys.argv[3]).write_text(offline_report(service,sys.argv[2]),encoding='utf-8')", project, record["id"], report])
    html = report.read_text(encoding="utf-8")
    assert "lab-sensitive@example.org" not in html and "another@example.org" not in html
    assert "Scientific Dataflow Inspector" in html and 'src="http' not in html
    profiles = json.loads(invoke([*prefix, "--json", "models", "list", "--project", project]))
    assert any(profile["id"] == "offline" for profile in profiles)
    return {"result": "passed", "version": installed["version"], "python": installed["python"],
            "cases": cases, "independent_interpreter": {"tool_dependencies": False, "value": value, "status": "completed"},
            "offline_privacy": "passed", "offline_models": "passed", "template_preserved": True}
