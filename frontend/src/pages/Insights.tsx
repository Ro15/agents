import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
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
  }, [activePlugin, datasetId]);

  const handleRun = async (windowKey?: string, windowLabel?: string) => {
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
    <div className="mx-auto max-w-6xl px-6 py-8 space-y-4">
      <div className="flex flex-col gap-2">
        <p className="text-sm text-slate-600">Plugin: {activePlugin}</p>
        <h1 className="text-3xl font-bold text-slate-900">Automated Insights</h1>
        <p className="text-sm text-slate-600">Run rules and review evidence-backed insights.</p>
        {lastWindowLabel && (
          <p className="text-xs text-slate-500">Requested window: {lastWindowLabel}</p>
        )}
        {controls}
      </div>

      {datasetId && (
        <Card title="Quick windows & filters">
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

      {datasetId && filteredInsights.length > 0 && (
        <div className="space-y-4">
          {filteredInsights.map((insight) => (
            <div key={insight.insight_id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h3 className="text-lg font-semibold text-slate-900">{insight.title}</h3>
                  <p className="text-sm text-slate-700">{insight.summary}</p>
                </div>
                <SeverityBadge severity={insight.severity} />
              </div>

              <div className="mt-3 space-y-2 text-xs text-slate-600">
                {insight.data_window && <div>Data window: {insight.data_window}</div>}
                {insight.generated_at && <div>Generated at: {insight.generated_at}</div>}
                {insight.confidence && <div>Confidence: {insight.confidence}</div>}
              </div>

              <div className="mt-3 space-y-3">
                {insight.details && (
                  <Collapsible title="Details" defaultOpen={true}>
                    {insight.details}
                  </Collapsible>
                )}
                <Collapsible title="Metrics" defaultOpen={false}>
                  <pre className="whitespace-pre-wrap break-words text-xs text-slate-800">
                    {JSON.stringify(insight.metrics, null, 2)}
                  </pre>
                </Collapsible>
                <Collapsible title="SQL" defaultOpen={false}>
                  <SqlBlock sql={insight.sql as any} />
                </Collapsible>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
