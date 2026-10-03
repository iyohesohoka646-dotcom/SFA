"""Disposable scientific UI fixture; no user code/environment is modified."""
from pathlib import Path
import tempfile
import uvicorn
from fastapi.staticfiles import StaticFiles
from contract_driven_ai_flow.research.routes import create_research_app
from contract_driven_ai_flow.research.models import ObservationEvent, SnapshotRef, ValueDescriptor, SourceRef
from contract_driven_ai_flow.research.agent.source import read_source
from contract_driven_ai_flow.research.store import ExperimentStore
from browser_session import fixture_session

if __name__ == "__main__":
    base = Path(__file__).resolve().parents[1]
    root = Path(tempfile.mkdtemp(prefix="research-browser-", dir=base / ".work"))
    script = root / "analysis.py"
    script.write_text("# 科研界面性能夹具，未执行计算\n" + "\n".join(f"X{i} = {i}" for i in range(1000)), encoding="utf-8")
    store = ExperimentStore(root)
    digest = read_source(script).digest
    run = store.create_run(str(script), interpreter="fixture-not-executed", source_digest=digest)
    source = store.state / "sources"
    source.mkdir()
    (source / (digest+'.txt')).write_text(script.read_text(encoding="utf-8"), encoding="utf-8")
    for version in range(1, 11):
        events = []
        for i in range(1000):
            snapshot = SnapshotRef(id=f"s{i}-{version}", run_id=run["id"], binding_id=f"main:X{i}", name=f"X{i}", scope_id="main", version=version,
                logical_key=f'{script}::<module>::X{i}', source=SourceRef(path=str(script),line=i+2,end_line=i+2,digest=digest),
                descriptor=ValueDescriptor(kind="matrix", backend="fixture", type_name="Matrix", shape=[4,4], dtype="float64", capabilities=["preview"]),
                sample={"values": [[version] * 4 for _ in range(4)]}, fidelity="exact", provenance="inferred",
                parents=[f"s{i-1}-{version}"] if i else [])
            events.append(ObservationEvent(run_id=run["id"], kind="value.observed", snapshot_id=snapshot.id, payload={"snapshot": snapshot.model_dump(mode="json")}))
        store.append(events)
    store.append([ObservationEvent(run_id=run["id"], kind="run.finished", payload={"status":"completed", "quality":"unconfigured"})])
    import importlib.util
    import sys
    from contract_driven_ai_flow.research.agent.sdk import TraceSession
    from contract_driven_ai_flow.research.agent.registry import AdapterRegistry
    spec = importlib.util.spec_from_file_location("pointcloud_example", base / "examples/research/custom-adapter.py")
    example = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = example
    spec.loader.exec_module(example)
    registry = AdapterRegistry()
    registry.register(example.PointCloudAdapter())
    extension = store.create_run(str(script), interpreter=sys.executable, source_digest=digest, name="Point cloud extension")
    with TraceSession("Point cloud", run_id=extension["id"], registry=registry) as trace:
        trace.watch("points", example.PointCloud(((1.0,2.0),(3.0,4.0))))
    store.append([ObservationEvent.model_validate(e) for e in trace.transport.drain()])
    app = create_research_app(root, token=fixture_session(), port=8879)
    # Saved runs belong to an imported version; cold import is benchmarked
    # separately instead of making fixture startup race the object browser.
    app.state.research.workbench.import_source(script)
    import os
    import asyncio
    from fastapi import Request
    from fastapi.responses import JSONResponse
    os.environ['CDAF_BROWSER_TEST_KEY']='synthetic-browser-model-key'

    @app.get('/fake-model/v1/models')
    async def fake_models(request: Request):
        return {'data':[{'id':'model-a'},{'id':'model-b'},{'id':'harness-model'}]}

    @app.post('/fake-model/v1/chat/completions')
    async def fake_completion(request: Request):
        body=await request.json()
        if body.get('model')=='slow-model':
            await asyncio.sleep(30)
        if body.get('model')=='error-model':
            return JSONResponse({'message':'synthetic-private-error'},status_code=401)
        if body.get('model')=='harness-model':
            import json
            manifest = json.loads(body['messages'][0]['content'].split('\n', 1)[1])
            obj = manifest['focus']['object_id'] or next(o['id'] for o in manifest['objects'] if o['kind'] == 'function')
            last = body['messages'][-1]['content']
            if not last.startswith('Tool result'):
                action = {'tool': 'source.read', 'arguments': {'object_id': obj}}
            else:
                result = json.loads(last.split('\n', 1)[1])
                if manifest['role'] == 'code' and result['reference'].startswith('source:'):
                    action = {'tool': 'code.propose', 'arguments': {'object_id': obj, 'candidate': 'def calculate(x):\n    return x + 2\n'}}
                else:
                    action = {'answer': '已读取真实定义并记录证据。', 'citations': [result['reference']]}
            return {'choices': [{'message': {'content': json.dumps(action, ensure_ascii=False)}}], 'usage': {'prompt_tokens': 24, 'completion_tokens': 12}}
        return {'choices':[{'message':{'content':'事实：这是已记录的数值运算。推测：实验意义需要用户标注。'}}], 'usage':{'prompt_tokens':24,'completion_tokens':12}}
    app.mount("/", StaticFiles(directory=base / "src/contract_driven_ai_flow/static", html=True))
    uvicorn.run(app, host="127.0.0.1", port=8879, access_log=False)
