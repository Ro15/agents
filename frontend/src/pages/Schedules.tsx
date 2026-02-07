import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAppState } from "../state";
import { Card } from "../components/Card";
import { Button } from "../components/Button";
import { Badge } from "../components/Badge";
import { EmptyState } from "../components/EmptyState";
import { useToast } from "../components/Toast";
import { listSchedules, createSchedule, deleteSchedule, updateSchedule, runScheduleNow } from "../lib/api";
import type { ScheduledReport } from "../types";

export const SchedulesPage: React.FC = () => {
  const { activePlugin, activeDataset } = useAppState();
  const navigate = useNavigate();
  const { push } = useToast();
  const [schedules, setSchedules] = useState<ScheduledReport[]>([]);
  const [loading, setLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [title, setTitle] = useState("");
  const [cron, setCron] = useState("0 8 * * MON");
  const [reportType, setReportType] = useState<"insights" | "query" | "dashboard">("insights");
  const [deliveryMethod, setDeliveryMethod] = useState("email");
  const [deliveryTarget, setDeliveryTarget] = useState("");

  const fetchSchedules = async () => {
    setLoading(true);
    try {
      const data = await listSchedules(activePlugin);
      setSchedules(data);
    } catch (err: any) {
      push(err?.message || "Failed to load schedules", "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSchedules();
  }, [activePlugin]);

  const handleCreate = async () => {
    if (!title.trim()) return;
    try {
      const s = await createSchedule({
        title: title.trim(),
        plugin_id: activePlugin,
        dataset_id: activeDataset?.dataset_id,
        schedule_cron: cron,
        report_type: reportType,
        delivery: deliveryTarget.trim()
          ? { method: deliveryMethod, target: deliveryTarget.trim() }
          : undefined,
      });
      setSchedules((prev) => [s, ...prev]);
      setShowCreate(false);
      setTitle("");
      setDeliveryTarget("");
      push("Schedule created!", "success");
    } catch (err: any) {
      push(err?.message || "Failed to create schedule", "error");
    }
  };

  const handleToggleEnabled = async (s: ScheduledReport) => {
    try {
      const updated = await updateSchedule(s.report_id, { enabled: !s.enabled } as any);
      setSchedules((prev) =>
        prev.map((x) => (x.report_id === s.report_id ? updated : x))
      );
    } catch {
      push("Failed to update", "error");
    }
  };

  const handleRunNow = async (id: string) => {
    try {
      const res = await runScheduleNow(id);
      push(`Report triggered at ${res.run_at}`, "success");
      fetchSchedules();
    } catch (err: any) {
      push(err?.message || "Failed to trigger", "error");
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Delete this schedule?")) return;
    try {
      await deleteSchedule(id);
      setSchedules((prev) => prev.filter((s) => s.report_id !== id));
      push("Schedule deleted", "success");
    } catch {
      push("Failed to delete", "error");
    }
  };

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Scheduled Reports</h1>
          <p className="text-sm text-slate-600">
            Set up recurring insight runs, queries, and alerts delivered via email, Slack, or webhooks.
          </p>
        </div>
        <div className="flex gap-2">
          <Button onClick={() => setShowCreate(true)}>New Schedule</Button>
          <Button variant="secondary" size="sm" onClick={() => navigate("/chat")}>
            Back to Chat
          </Button>
        </div>
      </div>

      {showCreate && (
        <Card className="mb-6">
          <h3 className="text-sm font-semibold text-slate-900 mb-3">New Scheduled Report</h3>
          <div className="space-y-3">
            <input
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-blue focus:outline-none"
              placeholder="Report title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-slate-600 mb-1">Schedule (cron)</label>
                <input
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-blue focus:outline-none"
                  value={cron}
                  onChange={(e) => setCron(e.target.value)}
                />
              </div>
              <div>
                <label className="block text-xs text-slate-600 mb-1">Report type</label>
                <select
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                  value={reportType}
                  onChange={(e) => setReportType(e.target.value as any)}
                >
                  <option value="insights">Insights</option>
                  <option value="query">Query</option>
                  <option value="dashboard">Dashboard</option>
                </select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-slate-600 mb-1">Delivery method</label>
                <select
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                  value={deliveryMethod}
                  onChange={(e) => setDeliveryMethod(e.target.value)}
                >
                  <option value="email">Email</option>
                  <option value="slack">Slack</option>
                  <option value="webhook">Webhook</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-slate-600 mb-1">Target (email/URL)</label>
                <input
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-blue focus:outline-none"
                  placeholder="user@example.com"
                  value={deliveryTarget}
                  onChange={(e) => setDeliveryTarget(e.target.value)}
                />
              </div>
            </div>
            <div className="flex gap-2">
              <Button size="sm" onClick={handleCreate}>
                Create
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setShowCreate(false)}>
                Cancel
              </Button>
            </div>
          </div>
        </Card>
      )}

      {loading && <p className="text-sm text-slate-500">Loading...</p>}

      {!loading && schedules.length === 0 && (
        <EmptyState
          title="No schedules"
          description="Create a scheduled report to receive automated insights."
          actionLabel="New Schedule"
          onAction={() => setShowCreate(true)}
        />
      )}

      <div className="space-y-3">
        {schedules.map((s) => (
          <Card key={s.report_id}>
            <div className="flex items-center justify-between">
              <div>
                <h4 className="text-sm font-semibold text-slate-900">{s.title}</h4>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <Badge tone="info">{s.report_type}</Badge>
                  <Badge tone={s.enabled ? "success" : "neutral"}>
                    {s.enabled ? "Active" : "Paused"}
                  </Badge>
                  <span className="text-xs text-slate-500 font-mono">{s.schedule_cron}</span>
                  {s.delivery && (
                    <span className="text-xs text-slate-500">
                      via {s.delivery.method} → {s.delivery.target}
                    </span>
                  )}
                </div>
                {s.last_run_at && (
                  <p className="mt-1 text-xs text-slate-400">
                    Last run: {new Date(s.last_run_at).toLocaleString()}
                  </p>
                )}
              </div>
              <div className="flex gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleToggleEnabled(s)}
                >
                  {s.enabled ? "Pause" : "Enable"}
                </Button>
                <Button variant="secondary" size="sm" onClick={() => handleRunNow(s.report_id)}>
                  Run Now
                </Button>
                <button
                  className="text-xs text-red-500 hover:text-red-700 px-2"
                  onClick={() => handleDelete(s.report_id)}
                >
                  Delete
                </button>
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
};
