"""Reproduce the checked-in gallery from executable examples and real run events."""
from pathlib import Path
import json

from contract_driven_ai_flow.compiler import compile_project
from contract_driven_ai_flow.examples import create_example, definition
from contract_driven_ai_flow.export import export_project
from contract_driven_ai_flow.runtime import Runner
from contract_driven_ai_flow.storage import Store, atomic_write, file_digest, now


def main():
    repository = Path(__file__).resolve().parents[1]
    records = []
    for name in ("data-pipeline", "business-flow", "nested-composite"):
        root = repository / "examples" / name
        project, source, success, failure = definition(name)
        if (root / "flow.yaml").exists():
            if Store(root).load().revision != project.revision or (root / "src/steps.py").read_text(encoding="utf-8") != source:
                raise RuntimeError(f"Example was edited; preserve changes and review before regenerating: {root}")
        else:
            create_example(root, name)
        plan = compile_project(project)
        assert plan.valid, plan.diagnostics
        case = {"example": name, "revision": project.revision, "source_digest": file_digest(source), "compile_diagnostics": [], "runs": []}
        for label, value in (("success", success), ("failure", failure)):
            run = Runner(root).run(value)
            expected = "passed" if label == "success" else "failed"
            assert (run["status"], run["quality"]) == ("completed", expected), run
            case["runs"].append({"fixture": label, "id": run["id"], "execution": run["status"], "quality": run["quality"]})
            directory = repository / "docs/examples" / name
            for format in ("html", "json"):
                export_project(root, format, directory / f"{label}.{format}", run["id"])
            if label == "failure":
                for format in ("svg", "png", "mermaid"):
                    export_project(root, format, directory / f"architecture.{format}", run["id"])
        records.append(case)
        print(f"{name}: execution completed, success quality passed, failure quality failed")
    atomic_write(repository / "docs/examples/validation.json", json.dumps({"generated_at": now(), "cases": records}, ensure_ascii=False, indent=2))
    links = "\n".join(f'<article><h2>{r["example"]}</h2><p>Observed runs · revision {r["revision"][:12]}</p><a href="{r["example"]}/success.html">Success evidence</a> · <a href="{r["example"]}/failure.html">Quality failure</a> · <a href="{r["example"]}/architecture.svg">SVG</a></article>' for r in records)
    atomic_write(repository / "docs/examples/index.html", '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Contract-Driven AI Flow · Examples</title><style>body{max-width:920px;margin:50px auto;padding:20px;font:16px system-ui;background:#0b1520;color:#e7f0f7}h1{font-size:38px}p{color:#9db5c6;line-height:1.7}article{padding:22px;margin:22px 0;border:1px solid #294255;border-radius:10px}a{color:#7be0bf}</style><h1>Code boundaries. Real evidence.</h1><p>Three local Python examples, each with a successful execution and a completed execution whose quality assertion fails. These offline views embed actual, sanitized events; design connections express reachability.</p>' + links + '<p><a href="validation.json">Validation record</a> · <a href="../index.html">Documentation</a></p></html>')


if __name__ == "__main__":
    main()
