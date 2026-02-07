import React, { useMemo, useState } from "react";

interface Props {
  rows: any[];
  maxRows?: number;
}

function formatCell(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "number") {
    if (Number.isInteger(value) && Math.abs(value) < 1e15) return value.toLocaleString();
    return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  return String(value);
}

function isNumeric(value: unknown): boolean {
  return typeof value === "number";
}

export const DataTable: React.FC<Props> = ({ rows, maxRows = 100 }) => {
  const [page, setPage] = useState(0);

  const columns = useMemo(() => (rows && rows.length > 0 ? Object.keys(rows[0]) : []), [rows]);
  const numericCols = useMemo(() => {
    if (!rows || rows.length === 0) return new Set<string>();
    return new Set(columns.filter((col) => rows.some((r) => isNumeric(r[col]))));
  }, [rows, columns]);

  if (!rows || rows.length === 0) return <p className="text-sm text-slate-600">No rows.</p>;

  const totalPages = Math.ceil(rows.length / maxRows);
  const pageRows = rows.slice(page * maxRows, (page + 1) * maxRows);

  const handleExportCSV = () => {
    const header = columns.join(",");
    const body = rows.map((row) => columns.map((col) => {
      const v = row[col];
      if (v == null) return "";
      const s = String(v);
      return s.includes(",") || s.includes('"') || s.includes("\n") ? `"${s.replace(/"/g, '""')}"` : s;
    }).join(",")).join("\n");
    const blob = new Blob([header + "\n" + body], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `data-export-${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-500">{rows.length} row{rows.length !== 1 ? "s" : ""}</span>
        <button
          onClick={handleExportCSV}
          className="rounded-md bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600 transition hover:bg-slate-200"
        >
          Export CSV
        </button>
      </div>
      <div className="overflow-auto rounded-lg border border-slate-200">
        <table className="min-w-full border-collapse text-sm">
          <thead className="bg-slate-50 sticky top-0">
            <tr>
              {columns.map((col) => (
                <th
                  key={col}
                  className={`border-b border-slate-200 px-3 py-2 text-left font-semibold text-slate-700 ${
                    numericCols.has(col) ? "text-right" : ""
                  }`}
                >
                  {col.replace(/_/g, " ")}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageRows.map((row, idx) => (
              <tr key={idx} className="odd:bg-white even:bg-slate-50 hover:bg-blue-50/40 transition-colors">
                {columns.map((col) => (
                  <td
                    key={col}
                    className={`border-b border-slate-100 px-3 py-2 text-slate-800 ${
                      numericCols.has(col) ? "text-right tabular-nums" : ""
                    }`}
                  >
                    {formatCell(row[col])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-xs text-slate-500">
          <span>
            Page {page + 1} of {totalPages}
          </span>
          <div className="flex gap-2">
            <button
              className="rounded border border-slate-200 px-2 py-0.5 hover:bg-slate-100 disabled:opacity-40"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
            >
              Prev
            </button>
            <button
              className="rounded border border-slate-200 px-2 py-0.5 hover:bg-slate-100 disabled:opacity-40"
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
