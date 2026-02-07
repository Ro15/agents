import React from "react";

interface Props {
  rows: any[];
}

export const DataTable: React.FC<Props> = ({ rows }) => {
  if (!rows || rows.length === 0) return <p className="text-sm text-slate-600">No rows.</p>;
  const columns = Object.keys(rows[0]);
  return (
    <div className="overflow-auto rounded-lg border border-slate-200">
      <table className="min-w-full border-collapse text-sm">
        <thead className="bg-slate-50">
          <tr>
            {columns.map((col) => (
              <th key={col} className="border-b border-slate-200 px-3 py-2 text-left font-semibold text-slate-700">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr key={idx} className="odd:bg-white even:bg-slate-50">
              {columns.map((col) => (
                <td key={col} className="border-b border-slate-100 px-3 py-2 text-slate-800">
                  {String(row[col])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};
