import { useEffect, useState } from "react";
import { SourcePane } from "../SourcePane";
import { client, type SourceFile } from "../client";
import type { SourceRef } from "../generated";
import type { AnalysisDocument, SourceObject, TargetRef } from "./generated";
import type { WorkspaceDocument } from "./layout";
import { wb } from "./WorkbenchClient";
import { logicalObjectGroups } from "./objectTree";
import { selectedOccurrenceGroups, selectedStructureSources, sourceFocus, type OccurrenceGroup } from "./sourceOccurrences";

export function SourceDocument({
  document,
  analysis,
  selection,
  targets = [],
  onSelect,
  onError,
}: {
  document: WorkspaceDocument;
  analysis?: AnalysisDocument;
  selection?: SourceRef | null;
  targets?: TargetRef[];
  onSelect: (object: SourceObject, analysis: AnalysisDocument) => void;
  onError: (message: string) => void;
}) {
  const [file, setFile] = useState<SourceFile>(),
    [objects, setObjects] = useState<AnalysisDocument>(),
    [occurrences, setOccurrences] = useState<OccurrenceGroup[]>([]);
  useEffect(() => {
    const abort = new AbortController();
    setFile(undefined);
    setObjects(undefined);
    setOccurrences([]);
    const loadObjects = (document: AnalysisDocument) => {
      if (abort.signal.aborted) return;
      setObjects(document);
      void wb.occurrences(document.id, abort.signal).then(groups => {
        if (!abort.signal.aborted) setOccurrences(groups);
      }).catch(error => { if (!abort.signal.aborted) onError(error.message); });
    };
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
        .then(loadObjects)
        .catch((e) => {
          if (!abort.signal.aborted) onError(e.message);
        });
    } else if (document.reference.run_id) {
      void client
        .source(document.reference.run_id, abort.signal)
        .then(setFile)
        .catch((e) => {
          if (!abort.signal.aborted) onError(e.message);
        });
      void wb.runAnalysis(document.reference.run_id, abort.signal).then(loadObjects)
        .catch(error => { if (!abort.signal.aborted) onError(error.message); });
    }
    return () => abort.abort();
  }, [document.id, document.reference.analysis_id, document.reference.run_id, analysis?.id]);
  const matched =
    file?.digest && selection?.digest === file.digest ? selection : null;
  const matchedObject = matched && objects?.objects.find(object => object.line === matched.line && object.column === matched.column && object.qualname === matched.qualname);
  const matchedSource = matchedObject && objects
    ? objects.graph.blocks.find(block => block.id === matchedObject.block_id)?.source ?? null
    : null;
  const fallback: TargetRef[] = matchedObject ? [{ kind: ["function", "class"].includes(matchedObject.kind) ? "function" : "data",
    logical_key: matchedObject.logical_key, object_id: matchedObject.id, block_id: matchedObject.block_id, analysis_id: objects!.id,
    run_id: null, snapshot_id: null,
    project_id: matchedSource?.project_id || null, file_id: matchedSource?.file_id || null, project_revision_id: matchedSource?.project_revision_id || null,
    exact_evidence: false }] : [];
  const activeTargets = targets.length ? targets.filter(target => !target.analysis_id || target.analysis_id === objects?.id
    || target.object_id && objects?.objects.some(object => object.id === target.object_id)) : fallback;
  const selectedGroups = selectedOccurrenceGroups(occurrences, activeTargets);
  const spans = selectedGroups.flatMap(group => group.occurrences);
  const ranges = file ? selectedStructureSources(objects, activeTargets, file.path, file.digest) : [];
  const focus = ranges[0] ?? (file ? sourceFocus(activeTargets.length && !matchedObject ? null : matched, selectedGroups, file.path, file.digest) : null);
  const logicalGroups = objects ? logicalObjectGroups(objects, occurrences) : [];
  const selectedGroup = logicalGroups.find(group => activeTargets.some(target => target.object_id && group.objectIds.includes(target.object_id)));
  return (
    <div className="wb-full-pane">
      <div className="wb-view-toolbar">
        <strong>源码</strong>
        {objects && (
          <select
            aria-label="源码对象"
            value={
              selectedGroup?.id ?? ""
            }
            onChange={(e) => {
              const object = logicalGroups.find(group => group.id === e.target.value)?.objects[0];
              if (object) onSelect(object, objects);
            }}
          >
            <option value="">选择逻辑对象</option>
            {logicalGroups.map((group) => (
              <option value={group.id} key={group.id}>
                {group.objects[0].qualname} · L{group.objects[0].line}{group.objects.length > 1 ? ` · ${group.objects.length} 处定义` : ""}
              </option>
            ))}
          </select>
        )}
      </div>
      <SourcePane file={file} selection={focus} occurrences={spans} ranges={ranges} />
    </div>
  );
}
