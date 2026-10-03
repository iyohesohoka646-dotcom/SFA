import { useEffect, useState } from "react";
import { client } from "../client";
import { numericCell } from "../matrix-renderer";
import { wb } from "./WorkbenchClient";
import { useSnapshot } from "./evidence";
import { MatrixView } from "../MatrixView";
import { TableView } from "../TableView";
import type { ProbeOutput, WorkbenchConfig } from "./generated";
function InputView({
  id,
  parameters,
}: {
  id: string;
  parameters: Record<string, unknown>;
}) {
  const { snapshot, error } = useSnapshot(id);
  if (error) return <div role="alert">{error}</div>;
  if (!snapshot) return <div>读取输入…</div>;
  return (
    <section className="comparison-input">
      <header>
        <strong>{snapshot.name}</strong>
        <small>
          v{snapshot.version} · {snapshot.fidelity} ·{" "}
          {snapshot.run_id.slice(0, 8)}
        </small>
      </header>
      {snapshot.sample.columns ? (
        <TableView snapshot={snapshot} parameters={parameters} />
      ) : snapshot.descriptor.shape ? (
        <MatrixView snapshot={snapshot} parameters={parameters} />
      ) : (
        <pre>{JSON.stringify(snapshot.sample, null, 2)}</pre>
      )}
    </section>
  );
}
export function ComparisonView({
  id,
  config,
}: {
  id: string;
  config?: WorkbenchConfig;
}) {
  const [output, setOutput] = useState<ProbeOutput>(),
    [error, setError] = useState(""),
    [zoom, setZoom] = useState(1),
    [individual, setIndividual] = useState<Record<string, number>>({}),
    [bounds, setBounds] = useState<{ minimum: number; maximum: number }>();
  useEffect(() => {
    const abort = new AbortController();
    setOutput(undefined);
    setBounds(undefined);
    setError("");
    void wb
      .output(id)
      .then(async (o) => {
        if (abort.signal.aborted) return;
        setOutput(o);
        const refs = Object.values(o.data.inputs ?? {}) as {
          snapshot_id: string;
        }[];
        const snapshots = await Promise.all(
          refs.map((r) => client.snapshot(r.snapshot_id)),
        );
        const numbers = snapshots
          .flatMap((s) =>
            ((s.sample.values ?? []) as unknown[][])
              .flat()
              .map((v) => numericCell(v, "real")),
          )
          .filter((v): v is number => v !== null && Number.isFinite(v));
        if (numbers.length && !abort.signal.aborted)
          setBounds({
            minimum: Math.min(...numbers),
            maximum: Math.max(...numbers),
          });
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(e.message);
      });
    return () => abort.abort();
  }, [id]);
  if (error) return <div role="alert">{error}</div>;
  if (!output) return <div>读取比较结果…</div>;
  if (!config?.probes.some((p) => p.id === output.instance_id && p.enabled))
    return <div className="wb-empty">此比较探针已停用</div>;
  const inputs = Object.values(output.data.inputs ?? {}) as {
      snapshot_id: string;
    }[],
    params = (output.data.parameters ?? {}) as Record<string, unknown>;
  return (
    <div className="comparison-pane">
      <div className="wb-view-toolbar">
        <strong>并排比较</strong>
        {(output.data.parameters as { linked_zoom?: boolean })?.linked_zoom !==
          false && (
          <label>
            联动缩放
            <input
              type="range"
              min={0.5}
              max={2}
              step={0.1}
              value={zoom}
              onChange={(e) => setZoom(Number(e.target.value))}
            />
          </label>
        )}
        <small>输入独立 · 抽样覆盖分别显示</small>
      </div>
      <div className="comparison-grid">
        {inputs.map((t) => (
          <section key={t.snapshot_id}>
            {params.linked_zoom === false && (
              <label>
                缩放
                <input
                  aria-label={"缩放 " + t.snapshot_id}
                  type="range"
                  min={0.5}
                  max={2}
                  step={0.1}
                  value={individual[t.snapshot_id] ?? 1}
                  onChange={(e) =>
                    setIndividual({
                      ...individual,
                      [t.snapshot_id]: Number(e.target.value),
                    })
                  }
                />
              </label>
            )}
            <InputView
              id={t.snapshot_id}
              parameters={{
                ...params,
                ...(params.shared_scale ? bounds : {}),
                zoom:
                  params.linked_zoom === false
                    ? (individual[t.snapshot_id] ?? 1)
                    : zoom,
              }}
            />
          </section>
        ))}
      </div>
    </div>
  );
}
