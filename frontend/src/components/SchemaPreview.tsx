import React from "react";
import { Badge } from "./Badge";

interface Column {
  column?: string;
  name?: string;
  column_name?: string;
  type?: string;
  data_type?: string;
  nullable?: boolean;
  sample_values?: string[];
  distinct_count?: number;
}

interface SchemaPreviewProps {
  columns: Column[];
  className?: string;
}

export const SchemaPreview: React.FC<SchemaPreviewProps> = ({ columns, className }) => {
  if (!columns || columns.length === 0) return null;

  return (
    <div className={`overflow-x-auto rounded-lg border border-slate-200 ${className || ""}`}>
      <table className="w-full text-left text-xs">
        <thead className="bg-slate-50 text-xs uppercase text-slate-600">
          <tr>
            <th className="px-3 py-2">Column</th>
            <th className="px-3 py-2">Type</th>
            <th className="px-3 py-2">Samples</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {columns.map((col, idx) => {
            const name = col.column || col.name || col.column_name || `col_${idx}`;
            const type = col.type || col.data_type || "TEXT";
            return (
              <tr key={name} className="hover:bg-slate-50">
                <td className="px-3 py-1.5 font-mono font-medium text-slate-900">{name}</td>
                <td className="px-3 py-1.5">
                  <Badge tone="neutral">{type}</Badge>
                </td>
                <td className="px-3 py-1.5 text-slate-500 truncate max-w-[200px]">
                  {col.sample_values?.slice(0, 3).join(", ") || "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};
