import { memo, useMemo, useState } from 'react';
import type { SnapshotRef } from './generated';
import type { DataSemantics } from './workspace/generated';
import { displayCell } from './matrix-renderer';

export const TableView = memo(function TableView({ snapshot, semantics, parameters = {} }: {
  snapshot: SnapshotRef; semantics?: DataSemantics | null; parameters?: Record<string, unknown>;
}) {
  const [top, setTop] = useState(0);
  const values = (snapshot.sample.values as unknown[][]) || [];
  const columnNames = (snapshot.sample.columns as unknown[]) || [];
  const index = (snapshot.sample.index as unknown[]) || [];
  const rowIndices = (snapshot.sample.row_indices as number[]) || [];
  const columnIndices = (snapshot.sample.column_indices as number[]) || [];
  const columns = columnNames.length ? columnNames : Array.from({ length: values[0]?.length ?? 0 }, (_, i) => columnIndices[i] ?? i);
  const indexed = index.length > 0, colSpan = columns.length + (indexed ? 2 : 1);
  const start = Math.max(0, Math.floor(top / 32) - 2);
  const shown = useMemo(() => values.slice(start, start + 20), [values, start]);
  const precision = Math.max(0, Math.min(12, Number(parameters.precision ?? 3) || 0));
  const types = (snapshot.descriptor.metadata.columns as { name: unknown; dtype: string }[]) || [];
  const columnSemantics = (i: number) => semantics?.columns[columnNames.length ? i : columnIndices[i] ?? i];
  const axis = semantics?.axes.at(-1);
  return <div className="ri-table-view">
    <p className="ri-fidelity">{snapshot.fidelity === 'exact' ? '全量已保存 / 当前预览' : '抽样预览'} · {values.length} 行 × {columns.length} 列</p>
    <div className="ri-table-scroll" onScroll={e => setTop(e.currentTarget.scrollTop)}>
      <table aria-label="数据表预览"><thead><tr>
        <th>行号</th>{indexed && <th>索引</th>}
        {columns.map((column, i) => {
          const meaning = columnSemantics(i), coordinate = columnIndices[i] ?? i;
          const label = meaning?.label || (columnNames.length ? displayCell(column) : axis?.labels[coordinate] || displayCell(column));
          return <th key={i} title={meaning?.meaning || axis?.meaning}>{label}{meaning?.unit ? ' (' + meaning.unit + ')' : ''}</th>;
        })}
      </tr></thead><tbody>
        {start > 0 && <tr aria-hidden="true"><td colSpan={colSpan} style={{ height: start * 32 }} /></tr>}
        {shown.map((row, i) => <tr key={start + i}>
          <th>{rowIndices[start + i] ?? start + i}</th>{indexed && <th>{displayCell(index[start + i])}</th>}
          {row.map((value, c) => <td key={c}>{typeof value === 'number' ? value.toFixed(precision) : displayCell(value)}</td>)}
        </tr>)}
        {start + shown.length < values.length && <tr aria-hidden="true"><td colSpan={colSpan} style={{ height: (values.length - start - shown.length) * 32 }} /></tr>}
      </tbody></table>
    </div>
    {!!types.length && <p className="ri-fidelity">列类型：{types.slice(0, 32).map(column => `${displayCell(column.name)}: ${column.dtype}`).join('；')}</p>}
    {!!snapshot.redacted.length && <p className="ri-fidelity">已脱敏：{snapshot.redacted.join('，')}</p>}
  </div>;
});
