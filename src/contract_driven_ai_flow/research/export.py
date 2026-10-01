"""Portable evidence report; values are saved, sanitised previews only."""
import html
import json


def offline_report(service, run_id):
    from .agent.privacy import sanitize_json
    run = service.store.run(run_id)
    snapshots = service.store.snapshots(run_id, limit=1000)
    source = service.source(run_id)
    body = sanitize_json({"schema_version": 1, "run": run, "source": source,
        "snapshots": [s.model_dump(mode="json") for s in snapshots],
        "scope": "Saved previews, not full data or a new execution", "maximum_variables": 1000})
    content = json.dumps(body, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Scientific Dataflow Inspector</title><style>
body{background:#0c1720;color:#e5eef2;font:15px/1.6 system-ui,sans-serif;margin:0;padding:24px}main{max-width:1200px;margin:auto}h1{font-size:24px}h2{font-size:18px}input,button{background:#11222e;color:inherit;border:1px solid #537184;border-radius:6px;padding:8px}section{margin:20px 0;border-top:1px solid #29414f;padding-top:12px}pre{white-space:pre-wrap;overflow:auto;background:#11222e;padding:16px;font:13px/1.6 monospace}small{color:#a7becb}button{cursor:pointer}button:focus-visible,input:focus-visible{outline:2px solid #7be0c2}canvas{max-width:100%;image-rendering:pixelated}
</style><main><h1>Scientific Dataflow Inspector</h1><p>本地运行证据 · 已保存的脱敏预览</p><small id="summary"></small><p><input id="search" type="search" aria-label="搜索变量" placeholder="搜索变量"></p><div id="values"></div><section id="source"><h2>source · 源码</h2><pre></pre></section></main>
<script type="application/json" id="evidence">""" + content + """</script><script>
const evidence=JSON.parse(document.getElementById('evidence').textContent);document.getElementById('summary').textContent=evidence.run.name+' · '+evidence.run.status+' · '+evidence.scope;document.querySelector('#source pre').textContent=evidence.source.code;
function draw(){const query=document.getElementById('search').value.toLowerCase(),target=document.getElementById('values');target.replaceChildren();for(const value of evidence.snapshots.filter(s=>s.name.toLowerCase().includes(query)).slice(0,80)){const section=document.createElement('section'),heading=document.createElement('h2'),meta=document.createElement('small'),pre=document.createElement('pre');heading.textContent=value.name+' · v'+value.version;meta.textContent=(value.descriptor.shape||[]).join(' × ')+' · '+(value.descriptor.dtype||value.descriptor.type_name)+' · '+value.fidelity;pre.textContent=JSON.stringify({sample:value.sample,statistics:value.statistics,source:value.source,redacted:value.redacted},null,2);section.append(heading,meta,pre);target.append(section);}}document.getElementById('search').addEventListener('input',draw);draw();
</script></html>"""
