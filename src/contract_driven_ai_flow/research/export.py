"""Portable evidence report; values are saved, sanitised previews only."""
import html
import json
import base64
from pathlib import Path


def offline_report(service, run_id):
    from .agent.privacy import sanitize_json
    run = service.store.run(run_id)
    snapshots = service.store.snapshots(run_id, limit=1000)
    source = service.source(run_id)
    body = sanitize_json({"schema_version": 1, "run": run, "source": source,
        "snapshots": [s.model_dump(mode="json") for s in snapshots],
        "scope": "Saved previews, not full data or a new execution", "maximum_variables": 1000})
    # Evidence records are already sanitised. Bound embedded artifacts separately;
    # never send their binary base64 through text truncation/sanitisation.
    outputs = service.workbench.outputs(run_id=run_id)[:128]
    body['probe_outputs'] = sanitize_json(outputs)
    plots = []
    remaining = 16 * 1024 * 1024
    uses_vega = False
    for output in outputs:
        artifact_id = output.get('artifact_id')
        if not artifact_id:
            continue
        try:
            path, receipt = service.workbench.drawing.artifact(artifact_id)
            if path.stat().st_size > remaining:
                plots.append('<section><h2>绘图产物超过离线嵌入预算</h2></section>')
                continue
            data = path.read_bytes(); remaining -= len(data)
            label = html.escape(output['definition_id'] + ' · ' + output['status'] + ' · ' + output['provenance'])
            if data.startswith(b'\x89PNG'):
                view = '<img alt="绘图探针产物" style="max-width:100%" src="data:image/png;base64,' + base64.b64encode(data).decode() + '">'
            elif path.suffix == '.html':
                view = '<iframe title="绘图探针产物" sandbox="allow-scripts" style="width:100%;height:520px;border:0" srcdoc="' + html.escape(data.decode('utf-8'), quote=True) + '"></iframe>'
            else:
                spec = json.loads(data)
                from .agent.privacy import sanitize_json
                spec = sanitize_json(spec)
                # Saved Vega-Lite artifacts contain inline bounded values only.
                def external(value):
                    if isinstance(value, dict): return 'url' in value or any(external(v) for v in value.values())
                    if isinstance(value, list): return any(external(v) for v in value)
                    return False
                if external(spec): raise ValueError('External data resource')
                uses_vega = True
                encoded = html.escape(json.dumps(spec, ensure_ascii=False, allow_nan=False), quote=True)
                view = '<div class="saved-vega" data-spec="' + encoded + '"></div>'
            plots.append('<section><h2>' + label + '</h2>' + view + '</section>')
        except (LookupError, ValueError, OSError):
            plots.append('<section><h2>绘图产物不可用</h2></section>')
    resources = ''
    if uses_vega:
        directory = Path(__file__).parents[1] / 'static' / 'export'
        for name in ('vega.min.js', 'vega-lite.min.js'):
            path = directory / name
            if path.is_file(): resources += '<script>' + path.read_text(encoding='utf-8').replace('</script', '<\\/script') + '</script>'
        resources += '<script>if(window.vega&&window.vegaLite)for(const node of document.querySelectorAll(".saved-vega")){try{const spec=vegaLite.compile(JSON.parse(node.dataset.spec)).spec;new vega.View(vega.parse(spec),{renderer:"canvas"}).initialize(node).runAsync();}catch(error){node.textContent="绘图资源不可用";}}</script>'
    content = json.dumps(body, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Scientific Dataflow Inspector</title><style>
body{background:#0c1720;color:#e5eef2;font:15px/1.6 system-ui,sans-serif;margin:0;padding:24px}main{max-width:1200px;margin:auto}h1{font-size:24px}h2{font-size:18px}input,button{background:#11222e;color:inherit;border:1px solid #537184;border-radius:6px;padding:8px}section{margin:20px 0;border-top:1px solid #29414f;padding-top:12px}pre{white-space:pre-wrap;overflow:auto;background:#11222e;padding:16px;font:13px/1.6 monospace}small{color:#a7becb}button{cursor:pointer}button:focus-visible,input:focus-visible{outline:2px solid #7be0c2}canvas{max-width:100%;image-rendering:pixelated}
</style><main><h1>Scientific Dataflow Inspector</h1><p>本地运行证据 · 已保存的脱敏预览</p><small id="summary"></small><p><input id="search" type="search" aria-label="搜索变量" placeholder="搜索变量"></p><div id="values"></div><section id="source"><h2>source · 源码</h2><pre></pre></section></main>
""" + ''.join(plots) + """<script type="application/json" id="evidence">""" + content + """</script><script>
const evidence=JSON.parse(document.getElementById('evidence').textContent);document.getElementById('summary').textContent=evidence.run.name+' · '+evidence.run.status+' · '+evidence.scope;document.querySelector('#source pre').textContent=evidence.source.code;
function draw(){const query=document.getElementById('search').value.toLowerCase(),target=document.getElementById('values');target.replaceChildren();for(const value of evidence.snapshots.filter(s=>s.name.toLowerCase().includes(query)).slice(0,80)){const section=document.createElement('section'),heading=document.createElement('h2'),meta=document.createElement('small'),pre=document.createElement('pre');heading.textContent=value.name+' · v'+value.version;meta.textContent=(value.descriptor.shape||[]).join(' × ')+' · '+(value.descriptor.dtype||value.descriptor.type_name)+' · '+value.fidelity;pre.textContent=JSON.stringify({sample:value.sample,statistics:value.statistics,source:value.source,redacted:value.redacted},null,2);section.append(heading,meta,pre);target.append(section);}}document.getElementById('search').addEventListener('input',draw);draw();
</script>""" + resources + """<script>for(const output of evidence.probe_outputs){const section=document.createElement('section'),heading=document.createElement('h2'),pre=document.createElement('pre');heading.textContent=output.definition_id+' · '+output.status+' · '+output.execution;pre.textContent=JSON.stringify(output,null,2);document.querySelector('main').append(section,heading,pre);}</script></html>"""
