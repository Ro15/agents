import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  PieChart,
  Pie,
  Cell,
} from "recharts";
import { useAppState } from "../state";
import { Button } from "../components/Button";
import { runInsightsSync, getLatestInsights } from "../lib/api";
import type { Insight } from "../types";
import { SeverityBadge } from "../components/SeverityBadge";
import { Collapsible } from "../components/Collapsible";
import { SqlBlock } from "../components/SqlBlock";
import { EmptyState } from "../components/EmptyState";
import { useToast } from "../components/Toast";
import { Skeleton } from "../components/Skeleton";
import { Card } from "../components/Card";
import { KPICard } from "../components/KPICard";

const SEVERITY_COLORS: Record<string, string> = {
  critical: "#ef4444",
  warning: "#f59e0b",
  info: "#3b82f6",
};

/** Render insight metrics as a mini bar chart if possible, else formatted list */
const MetricsDisplay: React.FC<{ metrics: Record<string, unknown> }> = ({ metrics }) => {
  const entries = Object.entries(metrics);
  if (entries.length === 0) return <p className="text-xs text-slate-500">No metrics</p>;

  // If all values are numeric, render as horizontal bar chart
  const numericEntries = entries.filter(([, v]) => typeof v === "number");
  if (numericEntries.length >= 2) {
    const data = numericEntries.map(([k, v]) => ({
      name: k.replace(/_/g, " "),
      value: v as number,
    }));
    return (
      <ResponsiveContainer width="100%" height={Math.max(numericEntries.length * 32, 120)}>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis type="number" tick={{ fontSize: 10, fill: "#64748b" }} />
          <YAxis type="category" dataKey="name" width={120} tick={{ fontSize: 10, fill: "#64748b" }} />
          <Tooltip />
          <Bar dataKey="value" fill="#0F4C81" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    );
  }

  // Fallback: formatted key-value list
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {entries.map(([k, v]) => (
        <div key={k} className="flex items-center justify-between rounded-md border border-slate-100 bg-slate-50 px-3 py-1.5">
          <span className="text-xs text-slate-600">{k.replace(/_/g, " ")}</span>
          <span className="text-xs font-semibold text-slate-900">
            {typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : String(v)}
          </span>
        </div>
      ))}
    </div>
  );
};

export const InsightsPage: React.FC = () => {
  const { activePlugin, activeDataset } = useAppState();
  const navigate = useNavigate();
  const { push } = useToast();
  const [insights, setInsights] = useState<Insight[]>([]);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [lastWindowLabel, setLastWindowLabel] = useState<string | null>(null);

  const datasetId = activeDataset?.dataset_id || null;

  const loadLatest = async () => {
    if (!datasetId) return;
    setLoading(true);
    setLastWindowLabel(null);
    try {
      const data = await getLatestInsights(activePlugin, datasetId);
      setInsights(data);
    } catch (err: any) {
      push(err?.message || "Failed to load insights", "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (datasetId) loadLatest();
    else setInsights([]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activePlugin, datasetId]);

  const handleRun = async (_windowKey?: string, windowLabel?: string) => {
    if (!datasetId) return;
    setRunning(true);
    try {
      const data = await runInsightsSync(activePlugin, datasetId, 20);
      const withWindow = data.map((insight) => ({
        ...insight,
        data_window: insight.data_window || windowLabel || insight.data_window,
      }));
      setInsights(withWindow);
      setLastWindowLabel(windowLabel || null);
      push("Insights generated", "success");
    } catch (err: any) {
      push(err?.message || "Failed to run insights", "error");
    } finally {
      setRunning(false);
    }
  };

  const filteredInsights = useMemo(() => {
    if (!searchTerm) return insights;
    const term = searchTerm.toLowerCase();
    return insights.filter(
      (insight) =>
        insight.title.toLowerCase().includes(term) ||
        (insight.severity && insight.severity.toLowerCase().includes(term))
    );
  }, [insights, searchTerm]);

  // Severity distribution for overview
  const severityDist = useMemo(() => {
    const counts: Record<string, number> = { critical: 0, warning: 0, info: 0 };
    for (const i of insights) {
      counts[i.severity] = (counts[i.severity] || 0) + 1;
    }
    return Object.entries(counts)
      .filter(([, v]) => v > 0)
      .map(([name, value]) => ({ name, value }));
  }, [insights]);

  const exportJson = () => {
    const blob = new Blob([JSON.stringify(insights, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${activePlugin}-${datasetId ?? "dataset"}-insights.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const windowPresets = [
    { id: "last_7_vs_prev_7", label: "Last 7 vs previous 7" },
    { id: "last_14_vs_prev_14", label: "Last 14 vs previous 14" },
  ];

  const controls = (
    <div className="flex flex-wrap gap-3">
      <Button onClick={() => handleRun(undefined, undefined)} disabled={!datasetId || running}>
        {running ? "Running..." : "Run Insights"}
      </Button>
      <Button variant="secondary" onClick={loadLatest} disabled={!datasetId || loading}>
        {loading ? "Refreshing..." : "Refresh Latest"}
      </Button>
      <Button variant="ghost" onClick={exportJson} disabled={insights.length === 0}>
        Export JSON
      </Button>
      <Button variant="ghost" onClick={() => navigate("/")}>
        Change Plugin/Dataset
      </Button>
    </div>
  );

  return (
    <div className="mx-auto max-w-7xl px-6 py-8 space-y-5">
      {/* Header */}
      <div className="flex flex-col gap-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-brand-teal">
          {activePlugin} · Insights
        </p>
        <h1 className="text-3xl font-bold text-slate-900">Automated Insights</h1>
        <p className="text-sm text-slate-600">
          AI-generated findings backed by SQL evidence. Run analysis to detect trends, anomalies, and key metrics.
        </p>
        {lastWindowLabel && (
          <p className="text-xs text-slate-500">Window: {lastWindowLabel}</p>
        )}
        {controls}
      </div>

      {/* Overview KPIs + severity chart */}
      {insights.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <KPICard
            title="Total Insights"
            value={insights.length}
            subtitle={`From ${activePlugin} plugin`}
          />
          <KPICard
            title="Critical"
            value={insights.filter((i) => i.severity === "critical").length}
            subtitle="Require attention"
          />
          <KPICard
            title="Warnings"
            value={insights.filter((i) => i.severity === "warning").length}
            subtitle="Worth reviewing"
          />
          <div className="flex items-center justify-center rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
            {severityDist.length > 0 ? (
              <ResponsiveContainer width="100%" height={100}>
                <PieChart>
                  <Pie
                    data={severityDist}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    outerRadius={40}
                    innerRadius={20}
                    label={({ name, value }) => `${name} ${value}`}
                    labelLine={false}
                  >
                    {severityDist.map((entry) => (
                      <Cell key={entry.name} fill={SEVERITY_COLORS[entry.name] || "#94a3b8"} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-xs text-slate-500">No data</p>
            )}
          </div>
        </div>
      )}

      {/* Filters */}
      {datasetId && (
        <Card title="Windows & Filters">
          <div className="flex flex-wrap items-center gap-3">
            {windowPresets.map((preset) => (
              <Button
                key={preset.id}
                variant="secondary"
                size="sm"
                onClick={() => handleRun(preset.id, preset.label)}
                disabled={running}
              >
                {preset.label}
              </Button>
            ))}
            <input
              className="flex-1 min-w-[220px] rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-blue focus:outline-none focus:ring-2 focus:ring-brand-blue/20"
              placeholder="Search insights by title or severity..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>
        </Card>
      )}

      {/* Empty states */}
      {!datasetId && (
        <EmptyState
          title="No dataset selected"
          description="Upload or select a dataset for this plugin to generate insights."
          actionLabel="Go to Dashboard"
          onAction={() => navigate("/")}
        />
      )}

      {datasetId && insights.length === 0 && !loading && !running && (
        <EmptyState
          title="No insights yet"
          description="Run insights to generate the latest findings for this dataset."
          actionLabel="Run Insights"
          onAction={() => handleRun(undefined, undefined)}
        />
      )}

      {datasetId && (loading || running) && (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <Skeleton className="h-5 w-1/2" />
              <Skeleton className="mt-2 h-4 w-full" />
              <Skeleton className="mt-2 h-4 w-2/3" />
            </div>
          ))}
        </div>
      )}

      {datasetId && insights.length > 0 && filteredInsights.length === 0 && !loading && !running && (
        <EmptyState
          title="No insights match your search"
          description="Try a different keyword or clear the filter to see all insights."
        />
      )}

      {/* Insight cards */}
      {datasetId && filteredInsights.length > 0 && (
        <div className="space-y-4">
          {filteredInsights.map((insight) => (
            <div key={insight.insight_id} className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
              {/* Header strip with severity color */}
              <div
                className="h-1"
                style={{ backgroundColor: SEVERITY_COLORS[insight.severity] || "#94a3b8" }}
              />
              <div className="p-5">
                <div className="flex items-start justify-between gap-2">
                  <div className="space-y-1">
                    <h3 className="text-lg font-semibold text-slate-900">{insight.title}</h3>
                    <p className="text-sm text-slate-700">{insight.summary}</p>
                  </div>
                  <SeverityBadge severity={insight.severity} />
                </div>

                <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-500">
                  {insight.data_window && (
                    <span className="rounded-md bg-slate-100 px-2 py-0.5">Window: {insight.data_window}</span>
                  )}
                  {insight.generated_at && (
                    <span className="rounded-md bg-slate-100 px-2 py-0.5">Generated: {insight.generated_at}</span>
                  )}
                  {insight.confidence && (
                    <span className="rounded-md bg-slate-100 px-2 py-0.5">Confidence: {insight.confidence}</span>
                  )}
                </div>

                <div className="mt-4 space-y-3">
                  {insight.details && (
                    <Collapsible title="Details" defaultOpen={true}>
                      <p className="text-sm text-slate-700 whitespace-pre-wrap">{insight.details}</p>
                    </Collapsible>
                  )}
                  <Collapsible title="Metrics" defaultOpen={true}>
                    <MetricsDisplay metrics={insight.metrics} />
                  </Collapsible>
                  <Collapsible title="SQL Evidence" defaultOpen={false}>
                    <SqlBlock sql={insight.sql as any} />
                  </Collapsible>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
