"""Dependency-free HTML/SVG/JSON/Mermaid and Pillow PNG exports, sanitized by default."""
from __future__ import annotations

import html
import io
import json
from pathlib import Path

from .compiler import compile_project
from .models import ProjectSpec, canonical
from .paths import FlowError
from .privacy import sanitize_project
from .storage import Store, atomic_write


def export_data(root: Path, run_id=None, *, current=False):
    store = Store(root)
    spec = store.load()
    if current and run_id:
        raise FlowError("Choose the current architecture or a historical run, not both")
    run = store.run(run_id) if run_id else None
    if run is None and not current:
        runs = store.runs()
        run = store.run(runs[0]["id"]) if runs else None
    project = run["graph"] if run else sanitize_project(spec)
    return {"format": "cdaf.export.v1", "project": project, "revision": run["revision"] if run else spec.revision,
            "run": {k: v for k, v in run.items() if k != "graph"} if run else None,
            "events": store.all_events(run["id"]) if run else [], "view": store.views()["view"],
            "evidence": "Observed events are historical execution evidence. Design links alone express static reachability."}


def scene(data):
    project = ProjectSpec.model_validate(data["project"])
    plan = compile_project(project)
    rank = {}
    for mid in plan.order:
        parents = [b.source.module for b in plan.bindings if b.target == mid and b.source.kind == "module"]
        rank[mid] = max((rank.get(p, 0) + 1 for p in parents), default=0)
    columns, positions = {}, {}
    for module in project.modules:
        column = rank.get(module.id, 0)
        row = columns.get(column, 0)
        positions[module.id] = {"x": 60 + column * 290, "y": 110 + row * 150}
        columns[column] = row + 1
    # Saved view is presentation only; historic semantic models retain their own IDs.
    for mid, point in data.get("view", {}).get("positions", {}).items():
        if mid in positions and isinstance(point, dict) and all(type(point.get(k)) in (float, int) for k in ("x", "y")):
            positions[mid] = {"x": max(20, point["x"]), "y": max(100, point["y"])}
    width = max([800] + [int(p["x"] + 280) for p in positions.values()])
    height = max([380] + [int(p["y"] + 170) for p in positions.values()])
    status = {}
    for event in data["events"]:
        mid = event.get("module")
        if event["kind"].startswith("module.") and mid:
            status[mid] = event["kind"].split(".")[1]
        if event["kind"] == "probe.result" and event["data"]["status"] in ("fail", "error"):
            status[mid + ":quality"] = event["data"]["status"]
    return project, positions, width, height, status


def svg(data):
    project, pos, width, height, statuses = scene(data)
    esc = html.escape
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Contract-Driven AI Flow architecture">',
             '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#5d8296"/></marker></defs>',
             f'<rect width="{width}" height="{height}" fill="#0b1520"/>',
             f'<text x="40" y="43" fill="#f3f8fc" font-family="Segoe UI, Noto Sans CJK SC, sans-serif" font-size="23" font-weight="600">{esc(project.name)}</text>',
             f'<text x="40" y="70" fill="#86a2b5" font-family="sans-serif" font-size="12">Contract-Driven AI Flow · revision {data["revision"][:12]} · {"observed run" if data["run"] else "architecture"}</text>']
    seen = set()
    for binding in project.bindings:
        source, target = binding.source.module, binding.target
        if source not in pos or target not in pos or (source, target) in seen:
            continue
        seen.add((source, target))
        p, q = pos[source], pos[target]
        x1, y1, x2, y2 = p["x"] + 230, p["y"] + 48, q["x"], q["y"] + 48
        observed = any(e.get("binding") == binding.id and e["kind"] == "binding.transferred" for e in data["events"])
        color = "#63dab6" if observed else "#5d8296"
        parts.append(f'<path d="M{x1},{y1} C{x1+55},{y1} {x2-55},{y2} {x2},{y2}" stroke="{color}" stroke-width="2" fill="none" marker-end="url(#arrow)"/>')
        parts.append(f'<text x="{(x1+x2)/2}" y="{(y1+y2)/2-8}" fill="#9cb3c4" font-family="sans-serif" font-size="10" text-anchor="middle">{esc(binding.port[:20])}</text>')
    for module in project.modules:
        p = pos[module.id]
        state = statuses.get(module.id, "designed")
        quality = statuses.get(module.id + ":quality")
        color = "#ffbb6a" if quality else "#65dfb9" if state == "completed" else "#ff8293" if state in ("failed", "timeout", "blocked") else "#7796c4"
        label = (module.name or module.id)[:28]
        parts.extend([f'<g data-node="{esc(module.id, quote=True)}" tabindex="0" role="button" aria-label="{esc(module.name or module.id, quote=True)}">',
                      f'<rect x="{p["x"]}" y="{p["y"]}" width="230" height="100" rx="12" fill="#152737" stroke="{color}"/>',
                      f'<text x="{p["x"]+16}" y="{p["y"]+24}" fill="{color}" font-family="sans-serif" font-size="10">{esc(module.kind.upper())} · {esc(module.id)}</text>',
                      f'<text x="{p["x"]+16}" y="{p["y"]+51}" fill="#f1f6fb" font-family="Segoe UI, Noto Sans CJK SC, sans-serif" font-size="17">{esc(label)}</text>',
                      f'<text x="{p["x"]+16}" y="{p["y"]+79}" fill="#aac0ce" font-family="sans-serif" font-size="11">{esc(state)}{ " · quality " + quality if quality else ""}</text></g>'])
    parts.append("</svg>")
    return "".join(parts)


def visual_receipt(data):
    _, pos, width, height, _ = scene(data)
    ids = list(pos)
    overlaps = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if abs(pos[a]["x"] - pos[b]["x"]) < 230 and abs(pos[a]["y"] - pos[b]["y"]) < 100:
                overlaps.append([a, b])
    return {"revision": data["revision"], "nodes": len(ids), "width": width, "height": height, "node_overlaps": overlaps,
            "validation": "Geometry checked; browser screenshot checks cover text rendering and interactive controls separately"}


def offline_html(data):
    embedded = canonical(data).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Contract-Driven AI Flow · Offline view</title>
<style>:root{color-scheme:dark;font:14px system-ui;background:#0b1520;color:#e7f0f7}*{box-sizing:border-box}body{margin:0}header{display:flex;align-items:center;gap:20px;padding:16px 24px;border-bottom:1px solid #294255}input,button,select{font:inherit;color:inherit;background:#172a39;border:1px solid #3a566a;border-radius:6px;padding:8px}main{display:grid;grid-template-columns:1fr 350px;height:calc(100vh - 70px)}#canvas{overflow:auto;padding:20px}aside{padding:22px;background:#101e2a;overflow:auto;border-left:1px solid #294255}pre{white-space:pre-wrap;overflow-wrap:anywhere;color:#a9c4d7;font-size:12px}h2{font-size:19px}small{color:#91acbf}g[data-node]{cursor:pointer}g[data-node]:focus rect{stroke:white;stroke-width:3}.dim{opacity:.18}label{display:block;margin:12px 0}a{color:#73dcc1}@media(max-width:800px){main{grid-template-columns:1fr}aside{border-top:1px solid #294255;max-height:40vh}header{flex-wrap:wrap}}@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}</style>
<header><strong>◈ Contract-Driven AI Flow</strong><small>OFFLINE EVIDENCE</small><input id="search" aria-label="Search modules" placeholder="Search modules / 搜索模块"><button id="reset">Show all</button></header>
<main><div id="canvas">''' + svg(data) + '''</div><aside><small id="revision"></small><h2 id="title">Execution evidence</h2><p id="description">Select a module to inspect its contract and recorded events.</p><label>Recorded event <select id="timeline" aria-label="Recorded event"><option value="">All events</option></select></label><div id="details"></div></aside></main>
<script type="application/json" id="data">''' + embedded + '''</script><script>
const data=JSON.parse(document.getElementById('data').textContent); const nodes=[...document.querySelectorAll('[data-node]')];
document.getElementById('revision').textContent='REVISION '+data.revision.slice(0,12)+(data.run?' · RUN '+data.run.id.slice(0,8):'');
const details=document.getElementById('details');function block(title,value){const h=document.createElement('h3');h.textContent=title;const p=document.createElement('pre');p.textContent=JSON.stringify(value,null,2);details.append(h,p)}
function inspect(id){const m=data.project.modules.find(n=>n.id===id);if(!m)return;document.getElementById('title').textContent=m.name||m.id;document.getElementById('description').textContent=m.description;details.replaceChildren();block('Contract',m.contract);block('Source',m.symbol);block('Observed events',data.events.filter(e=>e.module===id));location.hash='module='+encodeURIComponent(id)}
nodes.forEach(n=>{n.onclick=()=>inspect(n.dataset.node);n.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();inspect(n.dataset.node)}}});
function filter(q){nodes.forEach(n=>n.classList.toggle('dim',!n.textContent.toLowerCase().includes(q.toLowerCase())))}document.getElementById('search').oninput=e=>filter(e.target.value);document.getElementById('reset').onclick=()=>{document.getElementById('search').value='';filter('')};
data.events.forEach(e=>{const option=document.createElement('option');option.value=e.sequence;option.textContent=e.sequence+' · '+(e.module||'run')+' · '+e.kind;document.getElementById('timeline').append(option)});document.getElementById('timeline').onchange=e=>{const event=data.events.find(x=>String(x.sequence)===e.target.value);if(event){details.replaceChildren();block('Recorded event',event);if(event.module)filter(event.module)}else filter('')};
const id=new URLSearchParams(location.hash.slice(1)).get('module');if(id)inspect(id);else{block('Run',data.run);block('Evidence semantics',data.evidence)}
</script></html>'''


def png(data):
    from PIL import Image, ImageDraw, ImageFont
    project, pos, width, height, statuses = scene(data)
    if width * height > 40_000_000:
        raise FlowError("PNG exceeds 40 megapixels; collapse the graph or export SVG")
    font_paths = [Path("C:/Windows/Fonts/msyh.ttc"), Path("C:/Windows/Fonts/segoeui.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/System/Library/Fonts/PingFang.ttc")]
    font_path = next((p for p in font_paths if p.exists()), None)
    font = ImageFont.truetype(str(font_path), 17) if font_path else ImageFont.load_default(size=17)
    small = ImageFont.truetype(str(font_path), 12) if font_path else ImageFont.load_default(size=12)
    image = Image.new("RGB", (width, height), "#0b1520")
    draw = ImageDraw.Draw(image)
    draw.text((40, 25), project.name, fill="#f3f8fc", font=font)
    draw.text((40, 60), "Contract-Driven AI Flow · " + data["revision"][:12], fill="#91acbf", font=small)
    for binding in project.bindings:
        if binding.source.module in pos and binding.target in pos:
            p, q = pos[binding.source.module], pos[binding.target]
            draw.line([(p["x"] + 230, p["y"] + 48), (q["x"], q["y"] + 48)], fill="#63dab6", width=2)
    for module in project.modules:
        p = pos[module.id]
        draw.rounded_rectangle((p["x"], p["y"], p["x"] + 230, p["y"] + 100), 12, fill="#152737", outline="#63dab6", width=1)
        draw.text((p["x"] + 16, p["y"] + 12), module.kind.upper() + " · " + module.id, fill="#91acbf", font=small)
        draw.text((p["x"] + 16, p["y"] + 38), (module.name or module.id)[:24], fill="#f3f8fc", font=font)
        draw.text((p["x"] + 16, p["y"] + 73), statuses.get(module.id, "designed"), fill="#91acbf", font=small)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def render_export(root: Path, format: str, run_id=None, *, current=False):
    data = export_data(root, run_id, current=current)
    if format == "json":
        return json.dumps(data, ensure_ascii=False, indent=2), "application/json"
    if format == "html":
        return offline_html(data), "text/html"
    if format == "svg":
        return svg(data), "image/svg+xml"
    if format == "png":
        return png(data), "image/png"
    if format in ("mermaid", "mmd"):
        ids = {m["id"]: f"n{i}" for i, m in enumerate(data["project"]["modules"])}
        lines = ["flowchart LR"]
        for module in data["project"]["modules"]:
            label = html.escape(module["name"] or module["id"], quote=True).replace("\n", " ")
            lines.append(f'  {ids[module["id"]]}["{label}"]')
        for binding in data["project"]["bindings"]:
            source, target = binding["source"]["module"], binding["target"]
            if source in ids and target in ids:
                lines.append(f'  {ids[source]} --> {ids[target]}')
        return "\n".join(lines) + "\n", "text/plain"
    raise FlowError("Export format must be html, svg, png, mermaid or json")


def export_project(root: Path, format: str, destination: Path, run_id=None, *, current=False):
    value, _ = render_export(root, format, run_id, current=current)
    atomic_write(destination, value)
    atomic_write(destination.with_suffix(destination.suffix + ".validation.json"), json.dumps(visual_receipt(export_data(root, run_id, current=current)), ensure_ascii=False, indent=2))
    return destination.resolve()
