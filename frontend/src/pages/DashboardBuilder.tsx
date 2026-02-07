import React, { useState, useCallback } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useAppState } from "../state";
import { Card } from "../components/Card";
import { Button } from "../components/Button";
import { Badge } from "../components/Badge";
import { EmptyState } from "../components/EmptyState";
import { Skeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { useApiData } from "../hooks/useApiData";
import {
  listDashboards,
  createDashboard,
  getDashboard,
  deleteDashboard,
  addWidget,
  deleteWidget,
} from "../lib/api";
import type { CustomDashboard } from "../types";

// ── Dashboard List View ──────────────────────────────────────────

export const DashboardListPage: React.FC = () => {
  const { activePlugin } = useAppState();
  const navigate = useNavigate();
  const { push } = useToast();
  const [showCreate, setShowCreate] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newDesc, setNewDesc] = useState("");

  const { data: dashboards, loading, setData: setDashboards } = useApiData(
    () => listDashboards(activePlugin),
    [activePlugin],
  );

  const handleCreate = useCallback(async () => {
    if (!newTitle.trim()) return;
    try {
      const d = await createDashboard(newTitle.trim(), activePlugin, newDesc.trim() || undefined);
      setDashboards((prev) => (prev ? [d, ...prev] : [d]));
      setShowCreate(false);
      setNewTitle("");
      setNewDesc("");
      push("Dashboard created!", "success");
    } catch (err: any) {
      push(err?.message || "Failed to create dashboard", "error");
    }
  }, [newTitle, newDesc, activePlugin, push, setDashboards]);

  const handleDelete = useCallback(async (id: string) => {
    if (!confirm("Delete this dashboard?")) return;
    try {
      await deleteDashboard(id);
      setDashboards((prev) => prev ? prev.filter((d) => d.dashboard_id !== id) : prev);
      push("Dashboard deleted", "success");
    } catch {
      push("Failed to delete", "error");
    }
  }, [push, setDashboards]);

  const items = dashboards ?? [];

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">My Dashboards</h1>
          <p className="text-sm text-slate-600">Create custom dashboards and pin query results as widgets.</p>
        </div>
        <div className="flex gap-2">
          <Button onClick={() => setShowCreate(true)}>New Dashboard</Button>
          <Button variant="secondary" size="sm" onClick={() => navigate("/chat")}>
            Back to Chat
          </Button>
        </div>
      </div>

      {showCreate && (
        <Card className="mb-6">
          <h3 className="text-sm font-semibold text-slate-900 mb-3">Create Dashboard</h3>
          <div className="space-y-3">
            <input
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-blue focus:outline-none"
              placeholder="Dashboard title"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
            />
            <input
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-blue focus:outline-none"
              placeholder="Description (optional)"
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
            />
            <div className="flex gap-2">
              <Button size="sm" onClick={handleCreate}>Create</Button>
              <Button variant="ghost" size="sm" onClick={() => setShowCreate(false)}>Cancel</Button>
            </div>
          </div>
        </Card>
      )}

      {loading && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-32 w-full rounded-xl" />
          ))}
        </div>
      )}

      {!loading && items.length === 0 && (
        <EmptyState
          title="No dashboards yet"
          description="Create a dashboard and pin chat answers as widgets."
          actionLabel="Create Dashboard"
          onAction={() => setShowCreate(true)}
        />
      )}

      {!loading && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((d) => (
            <Card key={d.dashboard_id} className="cursor-pointer hover:shadow-md transition-shadow">
              <div onClick={() => navigate(`/dashboards/${d.dashboard_id}`)}>
                <h3 className="text-sm font-semibold text-slate-900">{d.title}</h3>
                {d.description && <p className="mt-1 text-xs text-slate-600">{d.description}</p>}
                <div className="mt-2 flex items-center gap-2">
                  <Badge tone="info">{d.widgets.length} widgets</Badge>
                  <span className="text-xs text-slate-400">
                    {d.updated_at ? new Date(d.updated_at).toLocaleDateString() : ""}
                  </span>
                </div>
              </div>
              <button
                className="mt-2 text-xs text-red-500 hover:text-red-700"
                onClick={(e) => { e.stopPropagation(); handleDelete(d.dashboard_id); }}
              >
                Delete
              </button>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
};

// ── Dashboard Detail / Editor View ───────────────────────────────

export const DashboardDetailPage: React.FC = () => {
  const { dashboardId } = useParams<{ dashboardId: string }>();
  const navigate = useNavigate();
  const { push } = useToast();
  const [showAddWidget, setShowAddWidget] = useState(false);
  const [widgetTitle, setWidgetTitle] = useState("");
  const [widgetQuery, setWidgetQuery] = useState("");
  const [widgetType, setWidgetType] = useState<"chart" | "kpi" | "table">("chart");

  const { data: dashboard, loading, setData: setDashboard } = useApiData(
    () => getDashboard(dashboardId!),
    [dashboardId],
    { skip: !dashboardId },
  );

  const handleAddWidget = useCallback(async () => {
    if (!dashboardId || !widgetTitle.trim()) return;
    try {
      const w = await addWidget(dashboardId, {
        title: widgetTitle.trim(),
        widget_type: widgetType,
        query_text: widgetQuery.trim() || undefined,
      });
      setDashboard((prev) => (prev ? { ...prev, widgets: [...prev.widgets, w] } : prev));
      setShowAddWidget(false);
      setWidgetTitle("");
      setWidgetQuery("");
      push("Widget added!", "success");
    } catch (err: any) {
      push(err?.message || "Failed to add widget", "error");
    }
  }, [dashboardId, widgetTitle, widgetType, widgetQuery, push, setDashboard]);

  const handleDeleteWidget = useCallback(async (widgetId: string) => {
    if (!dashboardId) return;
    try {
      await deleteWidget(dashboardId, widgetId);
      setDashboard((prev) =>
        prev ? { ...prev, widgets: prev.widgets.filter((w) => w.widget_id !== widgetId) } : prev
      );
      push("Widget removed", "success");
    } catch {
      push("Failed to remove widget", "error");
    }
  }, [dashboardId, push, setDashboard]);

  if (loading) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-8 space-y-4">
        <Skeleton className="h-10 w-64" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-40 w-full rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  if (!dashboard) return <div className="mx-auto max-w-5xl px-6 py-8 text-sm text-slate-500">Dashboard not found</div>;

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">{dashboard.title}</h1>
          {dashboard.description && <p className="text-sm text-slate-600">{dashboard.description}</p>}
        </div>
        <div className="flex gap-2">
          <Button onClick={() => setShowAddWidget(true)}>Add Widget</Button>
          <Button variant="secondary" size="sm" onClick={() => navigate("/dashboards")}>All Dashboards</Button>
        </div>
      </div>

      {showAddWidget && (
        <Card className="mb-6">
          <h3 className="text-sm font-semibold text-slate-900 mb-3">Add Widget</h3>
          <div className="space-y-3">
            <input
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-blue focus:outline-none"
              placeholder="Widget title"
              value={widgetTitle}
              onChange={(e) => setWidgetTitle(e.target.value)}
            />
            <input
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-blue focus:outline-none"
              placeholder="Natural language query (optional)"
              value={widgetQuery}
              onChange={(e) => setWidgetQuery(e.target.value)}
            />
            <div className="flex gap-2">
              {(["chart", "kpi", "table"] as const).map((t) => (
                <button
                  key={t}
                  className={`rounded-md px-3 py-1 text-xs font-medium transition ${
                    widgetType === t ? "bg-brand-blue text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                  }`}
                  onClick={() => setWidgetType(t)}
                >
                  {t.toUpperCase()}
                </button>
              ))}
            </div>
            <div className="flex gap-2">
              <Button size="sm" onClick={handleAddWidget}>Add</Button>
              <Button variant="ghost" size="sm" onClick={() => setShowAddWidget(false)}>Cancel</Button>
            </div>
          </div>
        </Card>
      )}

      {dashboard.widgets.length === 0 && (
        <EmptyState
          title="No widgets yet"
          description="Add widgets from chat answers or create them here."
          actionLabel="Add Widget"
          onAction={() => setShowAddWidget(true)}
        />
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {dashboard.widgets.map((w) => (
          <Card key={w.widget_id}>
            <div className="flex items-start justify-between">
              <div>
                <h4 className="text-sm font-semibold text-slate-900">{w.title}</h4>
                <Badge tone="neutral" className="mt-1">{w.widget_type}</Badge>
              </div>
              <button className="text-xs text-red-500 hover:text-red-700" onClick={() => handleDeleteWidget(w.widget_id)}>
                Remove
              </button>
            </div>
            {w.query_text && <p className="mt-2 text-xs text-slate-600 italic">"{w.query_text}"</p>}
            {w.sql && (
              <details className="mt-2">
                <summary className="cursor-pointer text-xs text-slate-500 hover:text-brand-blue">SQL</summary>
                <pre className="mt-1 overflow-x-auto rounded bg-slate-50 p-2 text-xs text-slate-700">{w.sql}</pre>
              </details>
            )}
            <div className="mt-2 rounded bg-slate-50 p-6 text-center text-xs text-slate-400">
              Widget visualization area
              {w.chart_hint && <span className="block mt-1">Chart: {w.chart_hint}</span>}
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
};
