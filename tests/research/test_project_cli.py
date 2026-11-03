"""P3 CLI tests: project commands compose the accepted ProjectApplication.

These launch the real interpreter through a frozen plan, so they are bounded
and use small fixtures. They never mock the core computation.
"""

import json

from typer.testing import CliRunner

from contract_driven_ai_flow.cli import app


def example(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "calc.py").write_text("def double(v):\n    result = v * 2\n    return result\n")
    (root / "main.py").write_text("from calc import double\nX = 7\nY = double(X)\n")


def run_cli(root, *args):
    runner = CliRunner()
    response = runner.invoke(app, ["--json", "workbench", "project", *args, "--project", str(root)])
    return response


def call(root, *args):
    response = run_cli(root, *args)
    assert response.exit_code == 0, response.output
    return json.loads(response.stdout)


def test_open_index_entries_plan_and_frozen_run(tmp_path):
    root = tmp_path / "中文 lab"
    example(root)
    project = call(root, "open", str(root))
    assert project["id"]
    # open registers only; it never publishes a revision on its own.
    assert run_cli(root, "run", "--plan", "missing").exit_code != 0
    revision = call(root, "index")
    assert revision["files_count"] == 2
    config = root / "entry.json"
    config.write_text(json.dumps([{"id": "main", "name": "Main", "kind": "script", "target": "main.py"}]))
    saved = call(root, "entries", "--save", str(config))
    assert saved["run_configurations"][0]["target"] == "main.py"
    plan = call(root, "plan", "--entry", "main")
    assert plan["project_id"] == project["id"]
    assert "sys.executable" not in plan and __import__("sys").executable not in json.dumps(plan)
    result = call(root, "run", "--plan", plan["id"])
    assert result["status"] == "completed", result
    assert result["run_id"]


def test_entries_default_reports_candidates_without_executing(tmp_path):
    root = tmp_path / "lab"
    example(root)
    call(root, "open", str(root))
    call(root, "index")
    entries = call(root, "entries")
    assert entries["project_id"]
    assert entries["revision_id"]
    assert entries["config_revision"] >= 0
    assert entries["entries"] == []
    assert any(item["target"] == "main.py" for item in entries["candidates"])


def test_bad_entry_fails_nonzero(tmp_path):
    root = tmp_path / "lab"
    example(root)
    call(root, "open", str(root))
    call(root, "index")
    response = run_cli(root, "plan", "--entry", "does-not-exist")
    assert response.exit_code != 0


def test_module_entry_runs(tmp_path):
    root = tmp_path / "lab"
    (root / "pkg").mkdir(parents=True, exist_ok=True)
    (root / "pkg" / "__init__.py").write_text("")
    (root / "pkg" / "helper.py").write_text("def scale(v):\n    doubled = v * 2\n    return doubled\n")
    (root / "pkg" / "main.py").write_text("from .helper import scale\nX = 5\nY = scale(X)\n")
    call(root, "open", str(root))
    call(root, "index")
    config = root / "entry.json"
    config.write_text(json.dumps([{"id": "pkg", "name": "Pkg", "kind": "module", "target": "pkg.main"}]))
    call(root, "entries", "--save", str(config))
    plan = call(root, "plan", "--entry", "pkg")
    result = call(root, "run", "--plan", plan["id"])
    assert result["status"] == "completed", result



def test_cli_graph_uses_project_query_semantics(tmp_path):
    root = tmp_path / "lab"
    example(root)
    call(root, "open", str(root))
    call(root, "index")
    graph = call(root, "graph", "--view", "code")
    assert graph["view"] == "code"
    assert graph["project_id"]
    assert graph["revision_id"]
    kinds = {node["kind"] for node in graph["graph"]["nodes"]}
    # The query projection drops data nodes; a raw service slice would keep them.
    assert "data" not in kinds
    assert "parameter" not in kinds


def test_cli_graph_data_view_projects_data_nodes(tmp_path):
    root = tmp_path / "lab"
    example(root)
    call(root, "open", str(root))
    call(root, "index")
    graph = call(root, "graph", "--view", "data")
    assert graph["view"] == "data"
    kinds = {node["kind"] for node in graph["graph"]["nodes"]}
    assert not (kinds & {"condition", "loop_header", "call"})