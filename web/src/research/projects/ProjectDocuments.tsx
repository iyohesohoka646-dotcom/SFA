import { useEffect, useState } from "react";
import { SourcePane } from "../SourcePane";
import { ProbeWorkspace } from "../workspace/ProbeWorkspace";
import { useSnapshot } from "../workspace/evidence";
import { useResearchServices } from "../workspace/ResearchServices";
import {
  selectedOccurrenceGroups,
  selectedStructureSources,
  type OccurrenceGroup,
} from "../workspace/sourceOccurrences";
import type { AnalysisDocument, TargetRef } from "../workspace/generated";
import type { WorkspaceDocument } from "../workspace/layout";
import type { ProjectQueries, ProjectSourceFile } from "./queries";

export function ProjectSourceDocument({
  document,
  queries,
  targets,
  onError,
}: {
  document: WorkspaceDocument;
  queries: ProjectQueries;
  targets: TargetRef[];
  onError: (message: string) => void;
}) {
  const { workbench: wb } = useResearchServices();
  const [file, setFile] = useState<ProjectSourceFile>(),
    [analysis, setAnalysis] = useState<AnalysisDocument>(),
    [occurrences, setOccurrences] = useState<OccurrenceGroup[]>([]);
  useEffect(() => {
    const abort = new AbortController();
    setFile(undefined);
    setAnalysis(undefined);
    setOccurrences([]);
    const { file_id: fileId, project_revision_id: revision } =
      document.reference;
    if (!fileId || !revision) {
      onError("源码缺少文件或版本引用");
      return;
    }
    void Promise.all([
      queries.source(revision, fileId, abort.signal),
      queries.analysis(revision, fileId, abort.signal),
    ])
      .then(([source, parsed]) => {
        if (abort.signal.aborted) return;
        setFile(source);
        setAnalysis(parsed);
        return wb.occurrences(parsed.id, abort.signal).then((groups) => {
          if (!abort.signal.aborted) setOccurrences(groups);
        });
      })
      .catch((e) => {
        if (!abort.signal.aborted) onError(e.message);
      });
    return () => abort.abort();
  }, [document.id, queries, wb]);
  const sameFile = targets.filter(
    (t) =>
      t.file_id === document.reference.file_id &&
      t.project_revision_id === document.reference.project_revision_id,
  );
  const spans = selectedOccurrenceGroups(occurrences, sameFile).flatMap(
    (g) => g.occurrences,
  );
  const ranges = file
    ? selectedStructureSources(analysis, sameFile, file.path, file.digest)
    : [];
  const first = sameFile.at(-1),
    object = analysis?.objects.find(
      (o) => o.id === first?.object_id || o.logical_key === first?.logical_key,
    );
  const fallback =
    object && file
      ? {
          path: file.path,
          line: object.line,
          end_line: object.end_line,
          column: object.column,
          end_column: object.end_column,
          qualname: object.qualname,
          digest: file.digest,
          code: object.code,
          project_id: first?.project_id ?? "",
          file_id: first?.file_id ?? "",
          project_revision_id: first?.project_revision_id ?? "",
          scope_id: "",
        }
      : null;
  return (
    <div className="wb-full-pane">
      <div className="wb-view-toolbar">
        <strong>{file?.path.split(/[\\/]/).at(-1) ?? "源码"}</strong>
        <small>{document.reference.project_revision_id?.slice(0, 8)}</small>
      </div>
      <SourcePane
        file={file}
        selection={ranges[0] ?? spans[0] ?? fallback}
        occurrences={spans}
        ranges={ranges}
      />
    </div>
  );
}

type DataProps = React.ComponentProps<typeof ProbeWorkspace> & {
  queries: ProjectQueries;
};
export function ProjectDataDocument({ queries, ...props }: DataProps) {
  const { snapshot } = useSnapshot(props.document.reference.snapshot_id);
  const [scope, setScope] = useState<{
      runId: string;
      analysis: AnalysisDocument;
    }>(),
    [error, setError] = useState("");
  useEffect(() => {
    const abort = new AbortController();
    setScope(undefined);
    setError("");
    if (!snapshot) return () => abort.abort();
    const source = snapshot.source;
    if (!source?.file_id || !source.project_revision_id) {
      setError("此历史数据缺少文件或版本引用");
      return;
    }
    void queries
      .analysis(source.project_revision_id, source.file_id, abort.signal)
      .then((analysis) => {
        if (!abort.signal.aborted)
          setScope({ runId: snapshot.run_id, analysis });
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(e.message);
      });
    return () => abort.abort();
  }, [snapshot?.id, queries]);
  return error ? (
    <p role="alert">{error}</p>
  ) : scope ? (
    <ProbeWorkspace {...props} runAnalysis={scope} />
  ) : (
    <p className="project-empty">读取数据版本…</p>
  );
}
