import { useEffect, useState } from "react";
import { SourcePane } from "../SourcePane";
import { client, type SourceFile } from "../client";
import type { SourceRef } from "../generated";
import type { AnalysisDocument } from "./generated";
import type { WorkspaceDocument } from "./layout";
import { wb } from "./WorkbenchClient";

export function SourceDocument({
  document,
  analysis,
  selection,
  onSelect,
  onError,
}: {
  document: WorkspaceDocument;
  analysis?: AnalysisDocument;
  selection?: SourceRef | null;
  onSelect: (id: string) => void;
  onError: (message: string) => void;
}) {
  const [file, setFile] = useState<SourceFile>(),
    [objects, setObjects] = useState<AnalysisDocument>();
  useEffect(() => {
    const abort = new AbortController();
    setFile(undefined);
    setObjects(undefined);
    const id = document.reference.analysis_id;
    if (id) {
      void wb
        .source(id, abort.signal)
        .then(setFile)
        .catch((e) => {
          if (!abort.signal.aborted) onError(e.message);
        });
      void (
        analysis?.id === id
          ? Promise.resolve(analysis)
          : wb.analysis(id, abort.signal)
      )
        .then(setObjects)
        .catch((e) => {
          if (!abort.signal.aborted) onError(e.message);
        });
    } else if (document.reference.run_id)
      void client
        .source(document.reference.run_id, abort.signal)
        .then(setFile)
        .catch((e) => {
          if (!abort.signal.aborted) onError(e.message);
        });
    return () => abort.abort();
  }, [document.id]);
  const matched =
    file?.digest && selection?.digest === file.digest ? selection : null;
  return (
    <div className="wb-full-pane">
      <div className="wb-view-toolbar">
        <strong>源码</strong>
        {objects && (
          <select
            aria-label="源码对象"
            value={
              matched
                ? (objects.objects.find((o) => o.line === matched.line)?.id ??
                  "")
                : ""
            }
            onChange={(e) => onSelect(e.target.value)}
          >
            <option value="">选择定义</option>
            {objects.objects.slice(0, 256).map((o) => (
              <option value={o.id} key={o.id}>
                {o.qualname} · L{o.line}
              </option>
            ))}
          </select>
        )}
      </div>
      <SourcePane file={file} selection={matched} />
    </div>
  );
}
