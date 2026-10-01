"""Disposable scientific UI fixture; no user code/environment is modified."""
from pathlib import Path
import tempfile
import uvicorn
from fastapi.staticfiles import StaticFiles
from contract_driven_ai_flow.research.routes import create_research_app
from contract_driven_ai_flow.research.models import ObservationEvent, SnapshotRef, ValueDescriptor
from contract_driven_ai_flow.research.store import ExperimentStore

if __name__ == "__main__":
    base = Path(__file__).resolve().parents[1]
    root = Path(tempfile.mkdtemp(prefix="research-browser-", dir=base / ".work"))
    script = root / "analysis.py"
    script.write_text("# 科研界面性能夹具，未执行计算\n" + "\n".join(f"X{i} = {i}" for i in range(1000)), encoding="utf-8")
    store = ExperimentStore(root)
    run = store.create_run(str(script), interpreter="fixture-not-executed", source_digest="fixture-source")
    source = store.state / "sources"
    source.mkdir()
    (source / "fixture-source.txt").write_text(script.read_text(encoding="utf-8"), encoding="utf-8")
    for version in range(1, 11):
        events = []
        for i in range(1000):
            snapshot = SnapshotRef(id=f"s{i}-{version}", run_id=run["id"], binding_id=f"main:X{i}", name=f"X{i}", scope_id="main", version=version,
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
    extension = store.create_run(str(script), interpreter=sys.executable, source_digest="fixture-source", name="Point cloud extension")
    with TraceSession("Point cloud", run_id=extension["id"], registry=registry) as trace:
        trace.watch("points", example.PointCloud(((1.0,2.0),(3.0,4.0))))
    store.append([ObservationEvent.model_validate(e) for e in trace.transport.drain()])
    app = create_research_app(root, token="research-test-session", port=8879)
    import os
    import asyncio
    from fastapi import Request
    from fastapi.responses import JSONResponse
    os.environ['CDAF_BROWSER_TEST_KEY']='synthetic-browser-model-key'

    @app.get('/fake-model/v1/models')
    async def fake_models(request: Request):
        return {'data':[{'id':'model-a'},{'id':'model-b'}]}

    @app.post('/fake-model/v1/chat/completions')
    async def fake_completion(request: Request):
        body=await request.json()
        if body.get('model')=='slow-model':
            await asyncio.sleep(30)
        if body.get('model')=='error-model':
            return JSONResponse({'message':'synthetic-private-error'},status_code=401)
        return {'choices':[{'message':{'content':'事实：这是已记录的数值运算。推测：实验意义需要用户标注。'}}], 'usage':{'prompt_tokens':24,'completion_tokens':12}}
    app.mount("/", StaticFiles(directory=base / "src/contract_driven_ai_flow/static", html=True))
    uvicorn.run(app, host="127.0.0.1", port=8879, access_log=False)
