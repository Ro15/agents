import React, { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";
import { listDatasets, uploadSalesAuto, getDashboardStats, chat } from "../lib/api";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { Select } from "../components/Select";
import { KPICard } from "../components/KPICard";
import { SmartChart } from "../components/SmartChart";
import { useAppState } from "../state";
import { UploadModal } from "../components/UploadModal";
import { Skeleton } from "../components/Skeleton";
import { EmptyState } from "../components/EmptyState";
import type { DashboardStats } from "../types";

const PLUGIN_OPTIONS = [
  { label: "Retail", value: "retail" },
  { label: "Manufacturing", value: "manufacturing" },
  { label: "Generic", value: "generic" },
];

interface Props {
  onOpenDatasetPicker?: () => void;
}

/** SVG icon helpers */
const IconDB = () => (
  <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75" />
  </svg>
);
const IconChat = () => (
  <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.087.16 2.185.283 3.293.369V21l4.076-4.076a1.526 1.526 0 011.037-.443 48.282 48.282 0 005.68-.494c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
  </svg>
);
const IconTrend = () => (
  <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 18L9 11.25l4.306 4.307a11.95 11.95 0 015.814-5.519l2.74-1.22m0 0l-5.94-2.28m5.94 2.28l-2.28 5.941" />
  </svg>
);
const IconShield = () => (
  <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
  </svg>
);

export const Dashboard: React.FC<Props> = ({ onOpenDatasetPicker }) => {
  const {
    activePlugin,
    setActivePlugin,
    activeDataset,
    setActiveDataset,
    setActiveDatasetId,
    datasetListsByPlugin,
    setDatasetListForPlugin,
    upsertDatasetForPlugin,
  } = useAppState();
  const [uploading, setUploading] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [loadingList, setLoadingList] = useState(false);
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loadingStats, setLoadingStats] = useState(false);
  const [quickAnswer, setQuickAnswer] = useState<{ q: string; a: string } | null>(null);
  const [quickLoading, setQuickLoading] = useState(false);
  const navigate = useNavigate();

  const pluginDatasets = datasetListsByPlugin[activePlugin] || [];

  // Load datasets list
  useEffect(() => {
    const load = async () => {
      setLoadingList(true);
      try {
        const remote = await listDatasets(activePlugin);
        if (remote.length > 0) setDatasetListForPlugin(activePlugin, remote);
      } catch (err: any) {
        setStatus(err?.message || "Could not refresh datasets from API, using saved list.");
      } finally {
        setLoadingList(false);
      }
    };
    load();
  }, [activePlugin, setDatasetListForPlugin]);

  // Load dashboard stats when dataset is active
  useEffect(() => {
    if (!activeDataset) {
      setStats(null);
      return;
    }
    const load = async () => {
      setLoadingStats(true);
      try {
        const s = await getDashboardStats(activePlugin, activeDataset.dataset_id);
        setStats(s);
      } catch {
        // Stats endpoint may not exist yet — that's fine, we degrade gracefully
        setStats(null);
      } finally {
        setLoadingStats(false);
      }
    };
    load();
  }, [activePlugin, activeDataset]);

  // Quick question handler
  const askQuick = useCallback(
    async (question: string) => {
      if (!activeDataset || quickLoading) return;
      setQuickLoading(true);
      setQuickAnswer(null);
      try {
        const resp = await chat(activePlugin, activeDataset.dataset_id, question);
        const a =
          resp.answer_type === "number"
            ? String(resp.answer)
            : resp.summary || resp.explanation || String(resp.answer).slice(0, 200);
        setQuickAnswer({ q: question, a });
      } catch {
        setQuickAnswer({ q: question, a: "Could not get answer." });
      } finally {
        setQuickLoading(false);
      }
    },
    [activePlugin, activeDataset, quickLoading]
  );

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setStatus(null);
    try {
      const res = await uploadSalesAuto(activePlugin, file);
      if (res.asyncUsed && res.job_id) {
        setStatus(`Upload queued (job ${res.job_id}). Track progress in Jobs/Datasets.`);
      } else if (res.dataset) {
        upsertDatasetForPlugin(activePlugin, res.dataset);
        setActiveDataset(res.dataset);
        setStatus(`Uploaded ${file.name}`);
        listDatasets(activePlugin).then((remote) => setDatasetListForPlugin(activePlugin, remote)).catch(() => {});
      }
    } catch (err: any) {
      setStatus(err?.message || "Upload failed");
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  };

  const handleLoadSample = async () => {
    const samplePath = `/sample_data/${activePlugin}_sample.csv`;
    setUploading(true);
    setStatus("Loading sample data...");
    try {
      const sampleFetch = await fetch(samplePath);
      if (!sampleFetch.ok) throw new Error("Sample file not found in /public/sample_data");
      const blob = await sampleFetch.blob();
      const file = new File([blob], `${activePlugin}_sample.csv`, { type: "text/csv" });
      const uploadRes = await uploadSalesAuto(activePlugin, file);
      if (!uploadRes.asyncUsed && uploadRes.dataset) {
        upsertDatasetForPlugin(activePlugin, uploadRes.dataset);
        setActiveDataset(uploadRes.dataset);
        setStatus("Sample data uploaded.");
        listDatasets(activePlugin).then((remote) => setDatasetListForPlugin(activePlugin, remote)).catch(() => {});
      } else {
        setStatus("Sample upload queued.");
      }
    } catch (err: any) {
      setStatus(err?.message || "Sample data unavailable. Upload your own CSV.");
    } finally {
      setUploading(false);
    }
  };

  const quickQuestions = [
    "What is total revenue?",
    "Show sales trend over time",
    "Top 5 items by revenue",
    "Average order value",
  ];

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6 px-6 py-8">
      {/* Header */}
      <header className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-brand-teal">Analytics Platform</p>
          <h1 className="text-3xl font-bold text-slate-900">Dashboard</h1>
          <p className="text-sm text-slate-600">
            Ask questions in natural language and get instant analytics, charts, and insights.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => navigate("/chat")}>
            <span className="flex items-center gap-1.5">
              <IconChat /> Chat
            </span>
          </Button>
          <Button onClick={() => navigate("/insights")}>
            <span className="flex items-center gap-1.5">
              <IconTrend /> Insights
            </span>
          </Button>
        </div>
      </header>

      {/* Setup row — plugin + dataset */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Plugin">
          <Select
            label="Select plugin"
            value={activePlugin}
            onChange={(e) => setActivePlugin(e.target.value)}
            options={PLUGIN_OPTIONS}
          />
          <div className="mt-3 flex gap-2">
            <Button variant="ghost" size="sm" onClick={() => navigate(`/plugins/${activePlugin}`)}>
              Plugin details
            </Button>
          </div>
        </Card>

        <Card
          title="Dataset"
          actions={
            <div className="flex gap-2">
              {onOpenDatasetPicker && (
                <Button variant="secondary" size="sm" onClick={onOpenDatasetPicker}>
                  Switch
                </Button>
              )}
              <Button size="sm" onClick={() => setShowUploadModal(true)} disabled={uploading}>
                {uploading ? "Uploading..." : "Upload CSV"}
              </Button>
            </div>
          }
        >
          {activeDataset ? (
            <div className="space-y-1 text-sm text-slate-700">
              <div className="font-semibold text-slate-900">
                {activeDataset.filename || activeDataset.dataset_id}
              </div>
              <div className="text-xs text-slate-500">
                {activeDataset.row_count !== undefined && <span>{activeDataset.row_count.toLocaleString()} rows</span>}
                {activeDataset.last_ingested_at && <span> · {activeDataset.last_ingested_at}</span>}
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              <p className="text-sm text-slate-500">No dataset — upload a CSV or load sample data to begin.</p>
              <Button variant="ghost" size="sm" onClick={handleLoadSample} disabled={uploading}>
                Load sample data
              </Button>
            </div>
          )}
          {status && <p className="mt-2 text-xs text-slate-600">{status}</p>}
        </Card>
      </div>

      {/* KPI cards (from stats or dataset meta) */}
      {activeDataset && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <KPICard
            title="Total Rows"
            value={activeDataset.row_count?.toLocaleString() ?? "—"}
            subtitle="In active dataset"
            icon={<IconDB />}
          />
          <KPICard
            title="Queries Made"
            value={stats?.total_queries?.toLocaleString() ?? "—"}
            subtitle="On this dataset"
            icon={<IconChat />}
            trend={stats?.total_queries ? { value: 0, label: "all time" } : undefined}
          />
          <KPICard
            title="Avg Confidence"
            value={stats?.avg_confidence ?? "—"}
            subtitle="Across all queries"
            icon={<IconShield />}
          />
          <KPICard
            title="Data Version"
            value={activeDataset.version ?? 1}
            subtitle={`Plugin: ${activePlugin}`}
            icon={<IconTrend />}
          />
        </div>
      )}

      {/* Charts from stats */}
      {stats && (
        <div className="grid gap-4 lg:grid-cols-2">
          {stats.recent_trend && stats.recent_trend.length > 1 && (
            <Card title="Revenue Trend">
              <ResponsiveContainer width="100%" height={240}>
                <AreaChart data={stats.recent_trend} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
                  <defs>
                    <linearGradient id="gradTeal" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#1F9AAD" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#1F9AAD" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#64748b" }} />
                  <YAxis tick={{ fontSize: 11, fill: "#64748b" }} tickFormatter={(v) => (v >= 1000 ? `${(v / 1000).toFixed(0)}K` : v)} />
                  <Tooltip />
                  <Area type="monotone" dataKey="value" stroke="#1F9AAD" fill="url(#gradTeal)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </Card>
          )}

          {stats.top_categories && stats.top_categories.length > 0 && (
            <Card title="Top Categories">
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={stats.top_categories} margin={{ top: 8, right: 16, left: 8, bottom: 8 }} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis type="number" tick={{ fontSize: 11, fill: "#64748b" }} tickFormatter={(v) => (v >= 1000 ? `${(v / 1000).toFixed(0)}K` : v)} />
                  <YAxis type="category" dataKey="name" width={100} tick={{ fontSize: 11, fill: "#64748b" }} />
                  <Tooltip />
                  <Bar dataKey="value" fill="#0F4C81" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </Card>
          )}
        </div>
      )}

      {/* Quick questions */}
      {activeDataset && (
        <Card title="Quick Ask" actions={<Button variant="ghost" size="sm" onClick={() => navigate("/chat")}>Open full chat</Button>}>
          <div className="flex flex-wrap gap-2">
            {quickQuestions.map((q) => (
              <button
                key={q}
                onClick={() => askQuick(q)}
                disabled={quickLoading}
                className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:border-brand-teal hover:bg-brand-teal/5 hover:text-brand-teal disabled:opacity-50"
              >
                {q}
              </button>
            ))}
          </div>
          {quickLoading && <Skeleton className="mt-3 h-12 w-full" />}
          {quickAnswer && (
            <div className="mt-3 rounded-lg border border-brand-teal/20 bg-brand-teal/5 p-3">
              <p className="text-xs font-medium text-slate-500">{quickAnswer.q}</p>
              <p className="mt-1 text-sm font-semibold text-slate-900">{quickAnswer.a}</p>
            </div>
          )}
        </Card>
      )}

      {/* Recent datasets */}
      <Card
        title="Recent Datasets"
        actions={
          <Button variant="ghost" size="sm" onClick={() => navigate("/datasets")}>
            Manage datasets
          </Button>
        }
      >
        {loadingList ? (
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : pluginDatasets.length === 0 ? (
          <EmptyState
            title="No datasets yet"
            description="Upload a CSV or load sample data to get started."
            actionLabel="Upload CSV"
            onAction={() => setShowUploadModal(true)}
          />
        ) : (
          <ul className="divide-y divide-slate-200">
            {pluginDatasets.slice(0, 5).map((ds) => (
              <li key={ds.dataset_id} className="flex items-center justify-between py-2.5 text-sm">
                <div>
                  <div className="font-semibold text-slate-900">{ds.filename || ds.dataset_id}</div>
                  <div className="text-xs text-slate-500">
                    {ds.row_count?.toLocaleString() ?? "?"} rows
                    {ds.last_ingested_at && <span> · {ds.last_ingested_at}</span>}
                  </div>
                </div>
                <Button
                  variant={activeDataset?.dataset_id === ds.dataset_id ? "ghost" : "secondary"}
                  size="sm"
                  onClick={() => setActiveDataset(ds)}
                >
                  {activeDataset?.dataset_id === ds.dataset_id ? "Active" : "Set Active"}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {/* Getting started */}
      {!activeDataset && (
        <Card title="Getting Started">
          <ol className="list-decimal space-y-2 pl-4 text-sm text-slate-700">
            <li>Select a plugin above (Retail, Manufacturing, or Generic).</li>
            <li>Upload a CSV dataset or click "Load sample data" to start quickly.</li>
            <li>
              Open <strong>Chat</strong> and ask questions in plain English — the AI converts them to SQL queries.
            </li>
            <li>
              Run <strong>Insights</strong> for automated analysis of trends, anomalies, and key metrics.
            </li>
          </ol>
        </Card>
      )}

      <UploadModal
        open={showUploadModal}
        onClose={() => setShowUploadModal(false)}
        onSuccess={(meta) => {
          upsertDatasetForPlugin(activePlugin, meta);
          setActiveDataset(meta);
          setStatus(`Uploaded ${meta.filename || meta.dataset_id}`);
        }}
      />
    </div>
  );
};
