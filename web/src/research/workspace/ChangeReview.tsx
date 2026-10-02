import { useEffect, useState } from "react";
import type {
  AnalysisDocument,
  CodeProposal,
  ProbeOutput,
  SourceObject,
  TaskRecord,
} from "./generated";
import { wb } from "./WorkbenchClient";

export function ChangeReview({
  analysis,
  object,
  proposalId,
  tasks,
  outputs,
  onAccepted,
  onError,
}: {
  analysis?: AnalysisDocument;
  object?: SourceObject;
  proposalId?: string;
  tasks: TaskRecord[];
  outputs: ProbeOutput[];
  onAccepted: (path: string) => void;
  onError: (message: string) => void;
}) {
  const [proposals, setProposals] = useState<CodeProposal[]>([]),
    [id, setId] = useState(proposalId ?? ""),
    [candidate, setCandidate] = useState("");
  const [newFile, setNewFile] = useState(false),
    [path, setPath] = useState("derived_analysis.py"),
    [busy, setBusy] = useState(false);
  const version = tasks
    .filter(
      (t) =>
        t.kind.startsWith("intelligence.") &&
        !["running", "queued"].includes(t.status),
    )
    .map((t) => t.id)
    .join("|");
  const refresh = () => wb.changes().then(setProposals);
  useEffect(() => {
    const abort = new AbortController();
    void wb
      .changes(abort.signal)
      .then(setProposals)
      .catch((e) => {
        if (!abort.signal.aborted) onError(e.message);
      });
    return () => abort.abort();
  }, [version]);
  useEffect(() => setId(proposalId ?? ""), [proposalId]);
  const proposal = proposals.find((p) => p.id === id);
  const apply = async (
    action: "validate" | "accept" | "reject" | "rollback",
  ) => {
    if (!proposal) return;
    setBusy(true);
    try {
      const next = await wb.change(proposal.id, action);
      await refresh();
      setId(next.id);
      if (action === "accept") onAccepted(next.path);
    } catch (e) {
      onError((e as Error).message);
      await refresh();
    } finally {
      setBusy(false);
    }
  };
  const completed = tasks.find(
    (t) => t.kind === "compute" && t.status === "completed" && t.run_id,
  );
  const checks = outputs.filter(
    (o) =>
      o.execution === "program" &&
      o.capability === "check" &&
      o.status === "pass" &&
      o.run_id === completed?.run_id,
  );
  return (
    <div className="wb-full-pane">
      <div className="wb-view-toolbar">
        <strong>代码审查</strong>
        <button onClick={() => void refresh().catch((e) => onError(e.message))}>
          刷新
        </button>
      </div>
      <div className="wb-scroll wb-review-content">
        <div className="wb-proposal-list">
          {proposals.map((p) => (
            <button
              key={p.id}
              aria-pressed={id === p.id}
              onClick={() => setId(p.id)}
            >
              {p.path.split(/[\\/]/).at(-1)}
              <small>
                {p.status} ·{" "}
                {p.behavior === "verified" ? "已验证所选检查" : "行为未验证"}
              </small>
            </button>
          ))}
        </div>
        {proposal ? (
          <>
            <div className="wb-section-label">
              {proposal.status} ·{" "}
              {proposal.behavior === "verified"
                ? "已验证所选检查"
                : "行为未验证"}{" "}
              <code>{proposal.source_digest.slice(0, 12)}</code>
            </div>
            <pre className="wb-diff" data-testid="proposal-diff">
              {proposal.diff.split("\n").map((line, i) => (
                <span
                  key={i}
                  className={
                    line.startsWith("+")
                      ? "diff-add"
                      : line.startsWith("-")
                        ? "diff-remove"
                        : ""
                  }
                >
                  {line + "\n"}
                </span>
              ))}
            </pre>
            {proposal.diagnostics.map((d, i) => (
              <div key={i} role="alert">
                {d}
              </div>
            ))}
            <div className="wb-form-actions">
              <button
                disabled={
                  busy ||
                  !["proposed", "valid", "invalid"].includes(proposal.status)
                }
                onClick={() => void apply("validate")}
              >
                验证修改范围
              </button>
              <button
                className="wb-primary"
                disabled={busy || proposal.status !== "valid"}
                onClick={() => void apply("accept")}
              >
                接受并应用
              </button>
              <button
                disabled={
                  busy ||
                  !["proposed", "valid", "invalid"].includes(proposal.status)
                }
                onClick={() => void apply("reject")}
              >
                退回
              </button>
              <button
                disabled={busy || proposal.status !== "accepted"}
                onClick={() => void apply("rollback")}
              >
                生成回滚提案
              </button>
            </div>
            {proposal.status === "accepted" && (
              <button
                disabled={!completed || !checks.length || busy}
                onClick={() => {
                  setBusy(true);
                  void wb
                    .validation(
                      proposal.id,
                      completed!.run_id!,
                      checks.map((o) => o.id),
                    )
                    .then(refresh)
                    .catch((e) => onError(e.message))
                    .finally(() => setBusy(false));
                }}
              >
                关联已通过的程序检查
              </button>
            )}
          </>
        ) : (
          <div className="wb-empty">选择提案查看差异</div>
        )}
        <details className="wb-local-proposal">
          <summary>创建局部代码提案</summary>
          <div className="wb-form">
            <label>
              <input
                type="checkbox"
                checked={newFile}
                onChange={(e) => setNewFile(e.target.checked)}
              />
              新分析文件
            </label>
            {newFile ? (
              <label>
                文件路径
                <input
                  aria-label="新分析文件路径"
                  value={path}
                  onChange={(e) => setPath(e.target.value)}
                />
              </label>
            ) : (
              <span>{object?.qualname ?? "先在源码中选择函数或赋值"}</span>
            )}
            <textarea
              aria-label="候选代码"
              value={candidate}
              onChange={(e) => setCandidate(e.target.value)}
              placeholder="完整函数或赋值；应用前会验证差异"
            />
            <button
              disabled={
                !analysis || !candidate.trim() || (!newFile && !object) || busy
              }
              onClick={() => {
                setBusy(true);
                void wb
                  .propose(
                    analysis!.id,
                    newFile ? null : object!.id,
                    candidate,
                    path,
                  )
                  .then(async (p) => {
                    await refresh();
                    setId(p.id);
                  })
                  .catch((e) => onError(e.message))
                  .finally(() => setBusy(false));
              }}
            >
              创建提案
            </button>
          </div>
        </details>
      </div>
    </div>
  );
}
