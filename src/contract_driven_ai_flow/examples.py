"""Three offline, runnable reference projects with a success and a quality failure."""
from __future__ import annotations

import json
from pathlib import Path

from .models import Contract, ModuleSpec, PortBinding, ProbeSpec, ProjectSpec, Source, SymbolRef
from .paths import FlowError
from .storage import Store, atomic_write


def object_schema(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


NUMBER = {"type": "number"}
NUMBERS = {"type": "array", "items": NUMBER}


def module(mid, input_props, output, *, example=None, **kwargs):
    return ModuleSpec(id=mid, name=mid.replace("_", " ").title(), symbol=SymbolRef(path="src/steps.py", qualname=mid),
                      contract=Contract(input=object_schema(input_props), output=output, examples=[example] if example else []), **kwargs)


def bind(target, port, source=None, pointer="", literal=None, project=False):
    return PortBinding(id=f"{source or 'input'}_{target}_{port}", target=target, port=port,
                       source=Source(kind="project" if project else "module" if source else "literal", module=source, pointer=pointer, value=literal))


def definition(name: str):
    if name == "data-pipeline":
        project = ProjectSpec(name="Signal quality · 数据质量流水线", input_schema=object_schema({"values": NUMBERS, "scale": NUMBER}),
            modules=[module("ingest", {"values": NUMBERS}, NUMBERS, description="Receive source measurements through a typed boundary", example={"input": {"values": [2, 4, 6]}, "output": [2, 4, 6]}),
                     module("normalize", {"values": NUMBERS, "scale": NUMBER}, NUMBERS, description="Scale each measurement in an isolated worker", example={"input": {"values": [2, 4, 6], "scale": 2}, "output": [1, 2, 3]}),
                     module("summarize", {"values": NUMBERS}, object_schema({"mean": NUMBER, "count": {"type": "integer"}}), description="Summarize the normalized signal", example={"input": {"values": [1, 2, 3]}, "output": {"mean": 2, "count": 3}}),
                     module("report", {"summary": object_schema({"mean": NUMBER, "count": {"type": "integer"}})}, {"type": "string"}, description="Publish a local, reproducible result", example={"input": {"summary": {"mean": 2, "count": 3}}, "output": "3 samples · mean 2.00"})],
            bindings=[bind("ingest", "values", pointer="/values", project=True), bind("normalize", "values", "ingest"), bind("normalize", "scale", pointer="/scale", project=True), bind("summarize", "values", "normalize"), bind("report", "summary", "summarize")],
            probes=[ProbeSpec(id="positive_scale", module="normalize", boundary="input", expression="$input.scale > 0", policy="block"),
                    ProbeSpec(id="mean_in_range", module="summarize", expression="$output.mean <= 5"),
                    ProbeSpec(id="sample_count", module="normalize", kind="metric"),
                    ProbeSpec(id="output_sample", module="summarize", kind="capture")])
        source = '''def ingest(values):
    return values


def normalize(values, scale):
    return [value / scale for value in values]


def summarize(values):
    return {"mean": sum(values) / len(values) if values else 0, "count": len(values)}


def report(summary):
    return f"{summary['count']} samples · mean {summary['mean']:.2f}"
'''
        success, failure = {"values": [2, 4, 6], "scale": 2}, {"values": [20, 40, 60], "scale": 2}
    elif name == "business-flow":
        project = ProjectSpec(name="Order approval · 本地外部服务", input_schema=object_schema({"amount": NUMBER, "stock": {"type": "integer"}}),
            modules=[module("inventory", {"stock": {"type": "integer"}}, object_schema({"available": {"type": "boolean"}}), side_effects=True, allowed_imports=["http.server", "http", "threading", "urllib", "json"], description="Call a loopback HTTP inventory stub; no remote credential required"),
                     ModuleSpec(id="approve", name="Approve order", kind="decision", condition="$input.available == True", contract=Contract(input=object_schema({"available": {"type": "boolean"}}), output={"type": "boolean"})),
                     module("fulfill", {"amount": NUMBER}, object_schema({"total": NUMBER}), guard={"decision": "approve", "when": True}),
                     module("decline", {"amount": NUMBER}, {"type": "string"}, guard={"decision": "approve", "when": False})],
            bindings=[bind("inventory", "stock", pointer="/stock", project=True), bind("approve", "available", "inventory", "/available"), bind("fulfill", "amount", pointer="/amount", project=True), bind("decline", "amount", pointer="/amount", project=True)],
            probes=[ProbeSpec(id="stock_available", module="inventory", expression="$output.available == True"), ProbeSpec(id="legacy_observation", module="inventory", kind="branch_observer", expression="$output.available == True", true_target="fulfill", false_target="decline")])
        source = '''def inventory(stock):
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.request import urlopen

    class InventoryHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            data = json.dumps({"available": stock > 0}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    with HTTPServer(("127.0.0.1", 0), InventoryHandler) as server:
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        with urlopen(f"http://127.0.0.1:{server.server_port}/inventory", timeout=3) as response:
            value = json.load(response)
        thread.join(timeout=3)
    return value


def fulfill(amount):
    return {"total": amount}


def decline(amount):
    return "Inventory unavailable"
'''
        success, failure = {"amount": 120, "stock": 3}, {"amount": 120, "stock": 0}
    elif name == "nested-composite":
        project = ProjectSpec(name="Nested transforms · 复合模块", input_schema=object_schema({"value": NUMBER}),
            modules=[ModuleSpec(id="pipeline", name="Transform pipeline", kind="composite", contract=Contract(input=object_schema({"value": NUMBER}), output=object_schema({"result": NUMBER})), outputs={"result": Source(kind="module", module="stage", pointer="/result")}),
                     ModuleSpec(id="stage", name="Inner stage", parent="pipeline", kind="composite", contract=Contract(input=object_schema({"value": NUMBER}), output=object_schema({"result": NUMBER})), outputs={"result": Source(kind="module", module="double")}),
                     module("double", {"value": NUMBER}, NUMBER, parent="stage"), module("display", {"result": NUMBER}, NUMBER)],
            bindings=[bind("pipeline", "value", pointer="/value", project=True), bind("stage", "value", "pipeline", "/value"), bind("double", "value", "stage", "/value"), bind("display", "result", "pipeline", "/result")],
            probes=[ProbeSpec(id="result_limit", module="display", expression="$output < 100")])
        source = "def double(value):\n    return value * 2\n\n\ndef display(result):\n    return result\n"
        success, failure = {"value": 12}, {"value": 80}
    else:
        raise FlowError("Example must be data-pipeline, business-flow or nested-composite")
    project.metadata = {"example": name, "inputs": {"success": success, "failure": failure}, "description": "Reproducible local example; failure demonstrates a completed execution with failed quality."}
    return project, source, success, failure


def create_example(root: Path, name="data-pipeline") -> Path:
    root = root.resolve()
    if root.exists() and any(root.iterdir()):
        raise FlowError(f"Destination must be empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    project, source, success, failure = definition(name)
    Store(root).save(project, None)
    atomic_write(root / "src/steps.py", source)
    for label, value in (("success", success), ("failure", failure)):
        atomic_write(root / f"{label}.json", json.dumps(value, ensure_ascii=False, indent=2))
    atomic_write(root / ".gitignore", ".cdaf/\n__pycache__/\n")
    atomic_write(root / "README.md", f"# {project.name}\n\nRun `cdaf run --input success.json` and `cdaf run --input failure.json`, then `cdaf studio`. Both execute real Python code; the second fails a quality assertion. The business example uses a loopback HTTP fixture.\n")
    return root
