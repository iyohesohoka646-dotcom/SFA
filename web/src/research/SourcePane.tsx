import { memo, useEffect, useMemo, useRef, useState } from "react";
import type { SourceFile } from "./client";
import type { SourceRef } from "./generated";
import { sourceLineParts, type SourceOccurrence } from "./workspace/sourceOccurrences";
import "./workspace/source-occurrences.css";

const lineHeight = 22;
export const SourcePane = memo(function SourcePane({ file, selection, occurrences = [], ranges = [] }: {
  file?: SourceFile;
  selection?: SourceRef | null;
  occurrences?: SourceOccurrence[];
  ranges?: SourceRef[];
}) {
  const lines = useMemo(() => file?.code.split("\n") || [], [file?.digest, file?.code]);
  const line = selection?.line || 1, code = useRef<HTMLDivElement>(null);
  const [top, setTop] = useState(0);
  const start = Math.max(0, Math.floor(top / lineHeight) - 10), end = Math.min(lines.length, start + 150);
  const spansByLine = useMemo(() => {
    const index = new Map<number, SourceOccurrence[]>();
    for (const span of occurrences)
      for (let number = span.line; number <= span.end_line; number++)
        index.set(number, [...(index.get(number) ?? []), span]);
    return index;
  }, [occurrences]);
  useEffect(() => {
    const next = Math.max(0, (line - 1) * lineHeight - (code.current?.clientHeight ?? 0) / 2);
    if (code.current) code.current.scrollTop = next;
    setTop(next);
  }, [line, file?.digest]);
  const definitionCount = occurrences.filter(span => span.role === "definition").length;
  const useCount = occurrences.filter(span => span.role === "use").length;
  return <section className="ri-source">
    <header><h2>源码与定义</h2><span>{occurrences.length ? `${definitionCount} 处定义 · ${useCount} 处使用` : selection?.line ? `第 ${line} 行` : ""}</span></header>
    <p className="ri-source-path" title={file?.path}>{file?.path || "打开代码，或者选择运行记录。"}</p>
    {selection?.code && <pre data-testid="source-selection" className="ri-source-selection">{selection.code}</pre>}
    {!lines.length ? <p className="ri-empty">源码预览只读；运行证据绑定当时的源码摘要。</p> :
      <div className="ri-code" ref={code} role="region" aria-label="分析源码" tabIndex={0} onScroll={event => setTop(event.currentTarget.scrollTop)}>
        <div className="ri-code-window" style={{ height: lines.length * lineHeight }}>
          {lines.slice(start, end).map((text, index) => {
            const number = start + index + 1, spans = spansByLine.get(number) ?? [];
            const active = ranges.some(r => number >= r.line && number <= r.end_line) || (occurrences.length ? spans.length > 0 : Boolean(selection && number >= line && number <= (selection.end_line || line)));
            return <div key={number} className={"ri-code-line" + (active ? " active" : "")} style={{ top: (number - 1) * lineHeight }} aria-label={`源码第 ${number} 行`}>
              <span>{number}</span><code>{sourceLineParts(text, number, spans).map((part, partIndex) => part.role
                ? <mark key={partIndex} className={"source-occurrence " + part.role} data-source-occurrence={part.role}>{part.text}</mark> : part.text)}</code>
            </div>;
          })}
        </div>
      </div>}
  </section>;
});
