"""Optional exporters. Core execution and Studio do not depend on either system."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .export import export_data, scene
from .models import canonical
from .paths import FlowError
from .storage import Store, atomic_write

ARCHIFY_REVISION = "a07fa1d5b2a10cbea110c5a2be2817397a301cdc"


def archify_ir(root: Path) -> dict:
    """Authored relations only: a design export does not infer execution paths."""
    data = export_data(root)
    project, positions, _, _, _ = scene(data)
    ids = {m.id: f"n{i}" for i, m in enumerate(project.modules)}
    components = [{"id": ids[m.id], "type": "cloud" if m.kind == "composite" else "backend",
                   "label": m.name or m.id, "sublabel": m.id, "tag": m.kind,
                   "pos": [positions[m.id]["x"], positions[m.id]["y"]], "size": [230, 100]}
                  for m in project.modules]
    pairs: dict[tuple[str, str], list[str]] = {}
    for binding in project.bindings:
        if binding.source.kind == "module" and binding.source.module in ids:
            pairs.setdefault((binding.source.module, binding.target), []).append(binding.port)
    connections = [{"id": f"e{i}", "from": ids[source], "to": ids[target], "label": ", ".join(ports),
                    "fromSide": "right", "toSide": "left", "route": "orthogonal-h"}
                   for i, ((source, target), ports) in enumerate(pairs.items())]
    return {"schema_version": 1, "diagram_type": "architecture",
            "meta": {"title": project.name, "subtitle": f"Design graph · CDAF revision {data['revision'][:12]}",
                     "animation": "none", "locale": "en", "legend": {"mode": "hidden"}},
            "components": components, "connections": connections}


def render_archify(root: Path, checkout: Path, output: Path) -> Path:
    """Invoke an explicitly supplied, clean checkout of the reviewed reference."""
    checkout = checkout.resolve()
    node, git = shutil.which("node"), shutil.which("git")
    if not node or not git:
        raise FlowError("Archify rendering requires Node.js and Git; ordinary exports need neither")

    def invoke(args):
        try:
            result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise FlowError("Archify command could not finish") from exc
        if result.returncode:
            raise FlowError("Archify command failed: " + (result.stderr or result.stdout)[-2000:])
        return result.stdout

    if invoke([git, "-C", str(checkout), "rev-parse", "HEAD"]).strip() != ARCHIFY_REVISION:
        raise FlowError(f"Archify checkout must be pinned to {ARCHIFY_REVISION}")
    invoke([git, "-C", str(checkout), "diff", "--quiet", "HEAD", "--"])
    cli = checkout / "archify/bin/archify.mjs"
    if not cli.is_file():
        raise FlowError("Expected the tt-a1i/archify repository checkout")
    ir = archify_ir(root)
    with tempfile.TemporaryDirectory(prefix="cdaf-archify-") as temp:
        source, rendered = Path(temp) / "design.json", Path(temp) / "design.html"
        atomic_write(source, canonical(ir))
        receipt = json.loads(invoke([node, str(cli), "validate", "architecture", str(source), "--json"]))
        invoke([node, str(cli), "render", "architecture", str(source), str(rendered)])
        invoke([node, str(cli), "check", str(rendered)])
        atomic_write(output, rendered.read_bytes())
        atomic_write(output.with_suffix(output.suffix + ".validation.json"), canonical({
            "adapter": "archify", "reference_revision": ARCHIFY_REVISION,
            "input_digest": hashlib.sha256(canonical(ir).encode()).hexdigest(), "validation": receipt}))
    return output.resolve()


def _nanoseconds(value: str) -> str:
    delta = datetime.fromisoformat(value) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return str((delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000)


def _attributes(data: dict) -> list[dict]:
    result = []
    for key, value in data.items():
        if value is None:
            continue
        if type(value) is bool:
            encoded = {"boolValue": value}
        elif type(value) is int:
            encoded = {"intValue": str(value)}
        elif type(value) is float:
            encoded = {"doubleValue": value}
        else:
            encoded = {"stringValue": value if isinstance(value, str) else canonical(value)}
        result.append({"key": key, "value": encoded})
    return result


def otel_payload(root: Path, run_id: str | None = None) -> dict:
    """OTLP/JSON traces with one span per attempt and links for upstream inputs."""
    store = Store(root)
    if not run_id:
        records = store.runs()
        if not records:
            raise FlowError("OpenTelemetry export requires an observed run")
        run_id = records[0]["id"]
    run, events = store.run(run_id), store.events(run_id)
    trace = hashlib.sha256(run_id.encode()).hexdigest()[:32]
    identifier = lambda name: hashlib.sha256(f"{run_id}:{name}".encode()).hexdigest()[:16]
    root_id = identifier("run")
    end = run["finished"] or (events[-1]["time"] if events else run["started"])
    root_span = {"traceId": trace, "spanId": root_id, "name": run["graph"]["name"], "kind": 1,
                 "startTimeUnixNano": _nanoseconds(run["started"]), "endTimeUnixNano": _nanoseconds(end),
                 "attributes": _attributes({"cdaf.run.id": run_id, "cdaf.revision": run["revision"],
                                             "cdaf.execution": run["status"], "cdaf.quality": run["quality"],
                                             "cdaf.incomplete": run["finished"] is None}),
                 "events": [], "links": [], "status": {"code": 1 if run["status"] == "completed" else 2}}
    spans, attempts = [root_span], {}
    by_sequence = {e["sequence"]: e for e in events}
    for event in events:
        key = (event["module"], event["attempt"])
        if event["kind"] == "module.started":
            links = []
            for relation in event["links"]:
                upstream = by_sequence.get(relation.get("sequence"))
                if upstream and upstream["module"]:
                    links.append({"traceId": trace, "spanId": identifier(f"{upstream['module']}:{upstream['attempt']}"),
                                  "attributes": _attributes({"cdaf.binding": relation.get("binding")})})
            span = {"traceId": trace, "spanId": identifier(f"{event['module']}:{event['attempt']}"), "parentSpanId": root_id,
                    "name": event["module"], "kind": 1, "startTimeUnixNano": _nanoseconds(event["time"]),
                    "endTimeUnixNano": _nanoseconds(end), "attributes": _attributes({"cdaf.attempt": event["attempt"],
                        "cdaf.contract.revision": event["contract_revision"], "cdaf.incomplete": True}),
                    "events": [], "links": links, "status": {"code": 0}}
            attempts[key] = span
            spans.append(span)
        span = attempts.get(key) or root_span
        # Captured data remains in CDAF evidence; exported trace events need metadata only.
        details = {k: v for k, v in event["data"].items() if k not in ("input", "output", "value")}
        span["events"].append({"name": event["kind"], "timeUnixNano": _nanoseconds(event["time"]),
                               "attributes": _attributes({"cdaf.sequence": event["sequence"], **details})})
        if event["kind"] in ("module.completed", "module.failed", "module.timeout", "module.cancelled", "module.blocked") and key in attempts:
            span["endTimeUnixNano"] = _nanoseconds(event["time"])
            span["status"] = {"code": 1 if event["kind"] == "module.completed" else 2}
            span["attributes"] = [a for a in span["attributes"] if a["key"] != "cdaf.incomplete"]
    return {"resourceSpans": [{"resource": {"attributes": _attributes({"service.name": "contract-driven-ai-flow",
                                 "service.version": "0.2.0"})},
                              "scopeSpans": [{"scope": {"name": "contract_driven_ai_flow", "version": "0.2.0"}, "spans": spans}]}]}


def export_otel(root: Path, exporter, run_id: str | None = None):
    """Use a caller-configured SpanExporter; importing CDAF never installs a provider."""
    try:
        from opentelemetry.sdk.trace import Event, ReadableSpan
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.trace import Link, SpanContext, SpanKind, Status, StatusCode, TraceFlags
    except ImportError as exc:
        raise FlowError("Install contract-driven-ai-flow[telemetry] for SDK export") from exc
    resource = otel_payload(root, run_id)["resourceSpans"][0]

    def attrs(values):
        result = {}
        for attribute in values:
            encoded = attribute["value"]
            value = next(iter(encoded.values()))
            result[attribute["key"]] = int(value) if "intValue" in encoded else value
        return result

    def ctx(trace, span):
        return SpanContext(int(trace, 16), int(span, 16), False, TraceFlags(TraceFlags.SAMPLED))

    spans = []
    for value in resource["scopeSpans"][0]["spans"]:
        spans.append(ReadableSpan(name=value["name"], context=ctx(value["traceId"], value["spanId"]),
            parent=ctx(value["traceId"], value["parentSpanId"]) if value.get("parentSpanId") else None,
            kind=SpanKind.INTERNAL, resource=Resource(attrs(resource["resource"]["attributes"])), attributes=attrs(value["attributes"]),
            start_time=int(value["startTimeUnixNano"]), end_time=int(value["endTimeUnixNano"]),
            status=Status({0: StatusCode.UNSET, 1: StatusCode.OK, 2: StatusCode.ERROR}[value["status"]["code"]]),
            links=[Link(ctx(link["traceId"], link["spanId"]), attrs(link["attributes"])) for link in value["links"]],
            events=[Event(event["name"], attrs(event["attributes"]), int(event["timeUnixNano"])) for event in value["events"]]))
    return exporter.export(spans)
