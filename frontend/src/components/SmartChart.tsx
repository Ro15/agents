import React, { useMemo } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  BarChart,
  Bar,
  PieChart,
  Pie,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  Cell,
} from "recharts";
import type { ChartHint } from "../types";

const COLORS = [
  "#0F4C81", // brand blue
  "#1F9AAD", // brand teal
  "#F5C518", // brand yellow
  "#6366f1", // indigo
  "#ec4899", // pink
  "#f97316", // orange
  "#10b981", // emerald
  "#8b5cf6", // violet
];

interface Props {
  rows: Record<string, unknown>[];
  hint?: ChartHint;
  height?: number;
}

/** Determine if a value looks numeric */
function isNumericVal(v: unknown): boolean {
  if (typeof v === "number") return true;
  if (typeof v === "string") {
    const n = Number(v);
    return !isNaN(n) && v.trim() !== "";
  }
  return false;
}

/** Detect whether a column contains date/time-like strings */
function looksLikeDate(values: unknown[]): boolean {
  const sample = values.slice(0, 10).filter(Boolean);
  if (sample.length === 0) return false;
  return sample.every((v) => {
    const s = String(v);
    return (
      /^\d{4}-\d{2}-\d{2}/.test(s) ||
      /^\d{1,2}\/\d{1,2}\/\d{2,4}/.test(s) ||
      /^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)/i.test(s) ||
      /^(mon|tue|wed|thu|fri|sat|sun)/i.test(s) ||
      /^\d{1,2}\s+(am|pm)/i.test(s)
    );
  });
}

/** Pick the best chart type from the data shape */
function detectChartType(
  rows: Record<string, unknown>[],
  labelCol: string,
  numericCols: string[],
  hint?: ChartHint
): "line" | "bar" | "pie" | "area" {
  if (hint && hint !== "none") return hint;

  const labelValues = rows.map((r) => r[labelCol]);
  const hasDateLabels = looksLikeDate(labelValues);
  const rowCount = rows.length;

  // Time series → line or area
  if (hasDateLabels) {
    return numericCols.length > 1 ? "area" : "line";
  }

  // Few categories with one numeric → pie (max 8 slices)
  if (rowCount <= 8 && numericCols.length === 1) {
    return "pie";
  }

  // Default to bar
  return "bar";
}

/** Separate columns into label (first non-numeric) and numeric */
function classifyColumns(rows: Record<string, unknown>[]) {
  const cols = Object.keys(rows[0] || {});
  const numericCols: string[] = [];
  let labelCol: string | null = null;

  for (const col of cols) {
    const values = rows.map((r) => r[col]).filter((v) => v != null);
    if (values.length > 0 && values.every(isNumericVal)) {
      numericCols.push(col);
    } else if (!labelCol) {
      labelCol = col;
    }
  }

  // Fallback: use first column as label if no non-numeric found
  if (!labelCol && cols.length > 0) {
    labelCol = cols[0];
    // Remove it from numeric if it was there
    const idx = numericCols.indexOf(labelCol);
    if (idx !== -1) numericCols.splice(idx, 1);
  }

  return { labelCol: labelCol || cols[0], numericCols };
}

/** Format column name for display */
function formatLabel(col: string): string {
  return col
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Format numbers for tooltips/axes */
function formatValue(v: number): string {
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return v % 1 === 0 ? String(v) : v.toFixed(2);
}

export const SmartChart: React.FC<Props> = ({ rows, hint, height = 320 }) => {
  const { labelCol, numericCols, chartType, data } = useMemo(() => {
    if (!rows || rows.length === 0 || rows.length > 500) {
      return { labelCol: "", numericCols: [] as string[], chartType: "bar" as const, data: [] };
    }

    const { labelCol, numericCols } = classifyColumns(rows);
    if (numericCols.length === 0) {
      return { labelCol, numericCols, chartType: "bar" as const, data: [] };
    }

    const chartType = detectChartType(rows, labelCol, numericCols, hint);

    // Coerce numeric values
    const data = rows.map((row) => {
      const out: Record<string, unknown> = { [labelCol]: row[labelCol] };
      for (const col of numericCols) {
        out[col] = Number(row[col]) || 0;
      }
      return out;
    });

    return { labelCol, numericCols, chartType, data };
  }, [rows, hint]);

  if (data.length === 0 || numericCols.length === 0) return null;

  const commonProps = {
    data,
    margin: { top: 8, right: 24, left: 8, bottom: 8 },
  };

  const axisStyle = { fontSize: 11, fill: "#64748b" };

  if (chartType === "pie") {
    const col = numericCols[0];
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <ResponsiveContainer width="100%" height={height}>
          <PieChart>
            <Pie
              data={data}
              dataKey={col}
              nameKey={labelCol}
              cx="50%"
              cy="50%"
              outerRadius={height / 3}
              label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
              labelLine={false}
            >
              {data.map((_, i) => (
                <Cell key={i} fill={COLORS[i % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip formatter={(v: number) => formatValue(v)} />
            <Legend />
          </PieChart>
        </ResponsiveContainer>
      </div>
    );
  }

  if (chartType === "line") {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <ResponsiveContainer width="100%" height={height}>
          <LineChart {...commonProps}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey={labelCol} tick={axisStyle} />
            <YAxis tick={axisStyle} tickFormatter={formatValue} />
            <Tooltip formatter={(v: number) => formatValue(v)} />
            {numericCols.length > 1 && <Legend />}
            {numericCols.map((col, i) => (
              <Line
                key={col}
                type="monotone"
                dataKey={col}
                name={formatLabel(col)}
                stroke={COLORS[i % COLORS.length]}
                strokeWidth={2}
                dot={{ r: 3 }}
                activeDot={{ r: 5 }}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    );
  }

  if (chartType === "area") {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <ResponsiveContainer width="100%" height={height}>
          <AreaChart {...commonProps}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey={labelCol} tick={axisStyle} />
            <YAxis tick={axisStyle} tickFormatter={formatValue} />
            <Tooltip formatter={(v: number) => formatValue(v)} />
            {numericCols.length > 1 && <Legend />}
            {numericCols.map((col, i) => (
              <Area
                key={col}
                type="monotone"
                dataKey={col}
                name={formatLabel(col)}
                stroke={COLORS[i % COLORS.length]}
                fill={COLORS[i % COLORS.length]}
                fillOpacity={0.15}
                strokeWidth={2}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    );
  }

  // Default: bar
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <ResponsiveContainer width="100%" height={height}>
        <BarChart {...commonProps}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey={labelCol} tick={axisStyle} />
          <YAxis tick={axisStyle} tickFormatter={formatValue} />
          <Tooltip formatter={(v: number) => formatValue(v)} />
          {numericCols.length > 1 && <Legend />}
          {numericCols.map((col, i) => (
            <Bar
              key={col}
              dataKey={col}
              name={formatLabel(col)}
              fill={COLORS[i % COLORS.length]}
              radius={[4, 4, 0, 0]}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
};
