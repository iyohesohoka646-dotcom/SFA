import { useResearchServices } from "./ResearchServices";
import { useEffect, useState } from "react";
import { MatrixView } from "../MatrixView";
import { TableView } from "../TableView";
import { displayCell } from "../matrix-renderer";
import { renderers } from "../renderer-registry";

import type { SnapshotRef } from "../generated";
import type { DataSemantics, ProbeDefinition, ProbeInstance, ProbeOutput } from "./generated";
import { ArtifactView } from "./ArtifactView";
import { sameParameters } from "./probe-results";

function InputRelations({ snapshot }: { snapshot: SnapshotRef }) {
  const { research: { client } } = useResearchServices();
  const [parents, setParents] = useState<SnapshotRef[]>([]), [error, setError] = useState("");
  useEffect(() => {
    const abort = new AbortController(); setParents([]); setError("");
    void Promise.all(snapshot.parents.slice(0, 24).map(id => client.snapshot(id, abort.signal)))
      .then(values => { if (!abort.signal.aborted) setParents(values); }).catch(e => { if (!abort.signal.aborted) setError(e.message); });
    return () => abort.abort();
  }, [snapshot.id]);
  return <div className="probe-input-relations">{parents.length ? <><span>{parents.map(p => p.name).join(" + ")}</span><span aria-hidden="true"> → </span><strong>{snapshot.name}</strong></>
    : <span>{error || (snapshot.parents.length ? "读取输入…" : "此版本未保存输入关系")}</span>}
    {snapshot.parents.length > 24 && <small>另有 {snapshot.parents.length - 24} 个输入</small>}</div>;
}

export function ProbePresentation({ snapshot, instance, definition, output, semantics }: {
  snapshot: SnapshotRef; instance: ProbeInstance; definition?: ProbeDefinition; output?: ProbeOutput; semantics: DataSemantics | null;
}) {
  const plugin = renderers.resolve(snapshot.descriptor);
  const renderer = definition?.renderer === "auto" ? plugin ? "plugin" : snapshot.sample.columns ? "table" : snapshot.descriptor.shape?.length ? "matrix" : "raw" : definition?.renderer;
  const fresh = output && sameParameters(output.data.parameters, instance.parameters);
  if (definition?.entrypoint || definition?.tool_id) {
    if (!output) return <div className="wb-empty">尚未执行此探针</div>;
    if (!fresh) return <div className="wb-empty">配置已修改，执行探针后更新此结果</div>;
    if (output.status === "error" || output.status === "fail") return <div className="wb-empty" role="alert">{output.message || output.status}</div>;
    return output.artifact_id ? <ArtifactView id={output.artifact_id} /> : <pre className="wb-json">{JSON.stringify(output.data, null, 2)}</pre>;
  }
  if (renderer === "plugin" && plugin) return <plugin.Component snapshot={snapshot} />;
  if (renderer === "matrix" && snapshot.descriptor.shape?.length) return <MatrixView snapshot={snapshot} parameters={instance.parameters} semantics={semantics} />;
  if (renderer === "table") return <TableView snapshot={snapshot} parameters={instance.parameters} semantics={semantics} />;
  if (renderer === "relationships") return <InputRelations snapshot={snapshot} />;
  if (renderer === "compare") return <div className="wb-empty">联合比较在任务与结果中打开</div>;
  return <pre className="wb-json" data-testid="raw-data">{snapshot.descriptor.kind === "scalar" && Array.isArray(snapshot.sample.values)
    ? displayCell((snapshot.sample.values as unknown[][])[0]?.[0]) : JSON.stringify(snapshot.sample, null, 2)}</pre>;
}
