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
    app = create_research_app(root, token="research-test-session", port=8879)
    app.mount("/", StaticFiles(directory=base / "src/contract_driven_ai_flow/static", html=True))
    uvicorn.run(app, host="127.0.0.1", port=8879, access_log=False)
