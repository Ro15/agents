import React, { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAppState } from "../state";
import { Card } from "../components/Card";
import { Button } from "../components/Button";
import { Badge } from "../components/Badge";
import { Skeleton } from "../components/Skeleton";
import { EmptyState } from "../components/EmptyState";
import { UploadModal } from "../components/UploadModal";
import { useToast } from "../components/Toast";
import { useApiData } from "../hooks/useApiData";
import {
  listDatasets,
  listConnectors,
  createConnector,
  deleteConnector,
  testConnector,
  getConnectorTables,
  syncConnectorTable,
} from "../lib/api";
import type { DataConnector, DatasetMeta, RemoteTablesResult } from "../types";

const CONNECTOR_TYPES = [
  { value: "postgresql", label: "PostgreSQL" },
  { value: "mysql", label: "MySQL" },
  { value: "mssql", label: "SQL Server" },
  { value: "bigquery", label: "BigQuery" },
  { value: "snowflake", label: "Snowflake" },
  { value: "excel", label: "Excel" },
  { value: "sheets", label: "Google Sheets" },
  { value: "api", label: "REST API" },
  { value: "s3", label: "AWS S3" },
  { value: "gcs", label: "Google Cloud Storage" },
  { value: "azure", label: "Azure Blob" },
];

const statusTone = (status: string): "info" | "warning" | "critical" | "success" | "neutral" => {
  if (status === "connected") return "success";
  if (status === "error") return "critical";
  return "neutral";
};

// ── Dataset card ──────────────────────────────────────────────────────────
const DatasetCard: React.FC<{
  ds: DatasetMeta;
  isActive: boolean;
  onActivate: () => void;
  onChat: () => void;
  onInsights: () => void;
  onDelete: () => void;
}> = ({ ds, isActive, onActivate, onChat, onInsights, onDelete }) => (
  <div
    className={`flex flex-col rounded-xl border p-4 shadow-sm transition ${
      isActive ? "border-brand-blue bg-brand-blue/5" : "border-slate-200 bg-white hover:border-slate-300"
    }`}
  >
    <div className="mb-2 flex items-start justify-between gap-2">
      <div className="min-w-0">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{ds.plugin}</p>
        <h3 className="truncate text-sm font-semibold text-slate-900" title={ds.source_filename || ds.dataset_id}>
          {ds.source_filename || ds.dataset_id.slice(0, 12) + "…"}
        </h3>
      </div>
      {isActive && (
        <span className="shrink-0 rounded-full bg-brand-blue/10 px-2 py-0.5 text-[10px] font-semibold text-brand-blue">
          Active
        </span>
      )}
    </div>

    <div className="mb-3 flex flex-wrap gap-1.5 text-xs text-slate-500">
      {ds.row_count != null && <span>{ds.row_count.toLocaleString()} rows</span>}
      {ds.schema_type && (
        <>
          <span>·</span>
          <Badge tone={ds.schema_type === "dynamic" ? "info" : "neutral"}>{ds.schema_type}</Badge>
        </>
      )}
      {ds.file_format && (
        <>
          <span>·</span>
          <span className="uppercase">{ds.file_format}</span>
        </>
      )}
    </div>

    {ds.last_ingested_at && (
      <p className="mb-3 text-[11px] text-slate-400">
        Ingested {new Date(ds.last_ingested_at).toLocaleDateString()}
      </p>
    )}

    <div className="mt-auto flex flex-wrap gap-2">
      {!isActive && (
        <Button size="sm" onClick={onActivate}>
          Activate
        </Button>
      )}
      <Button size="sm" variant="secondary" onClick={onChat}>
        Chat
      </Button>
      <Button size="sm" variant="ghost" onClick={onInsights}>
        Insights
      </Button>
      <button
        className="ml-auto text-xs text-red-400 hover:text-red-600"
        onClick={onDelete}
        title="Remove from list"
      >
        Remove
      </button>
    </div>
  </div>
);

// ── Main page ─────────────────────────────────────────────────────────────
export const DataSourcesPage: React.FC = () => {
  const {
    activePlugin,
    activeDataset,
    setActivePlugin,
    setActiveDataset,
    datasetListsByPlugin,
    setDatasetListForPlugin,
    deleteDatasetForPlugin,
    upsertDatasetForPlugin,
  } = useAppState();
  const navigate = useNavigate();
  const { push } = useToast();

  // Upload modal
  const [showUpload, setShowUpload] = useState(false);

  // Connectors state (mirrors Connectors.tsx)
  const [showCreateConnector, setShowCreateConnector] = useState(false);
  const [newName, setNewName] = useState("");
  const [newType, setNewType] = useState("postgresql");
  const [newUrl, setNewUrl] = useState("");
  const [browsingId, setBrowsingId] = useState<string | null>(null);
  const [remoteTables, setRemoteTables] = useState<string[]>([]);
  const [loadingTables, setLoadingTables] = useState(false);
  const [syncing, setSyncing] = useState<string | null>(null);

  const { data: connectors, loading: loadingConnectors, setData: setConnectors, refetch: refetchConnectors } =
    useApiData(() => listConnectors(activePlugin), [activePlugin]);

  // Datasets (from global state for current plugin)
  const datasets = datasetListsByPlugin[activePlugin] || [];

  // ── Upload success ─────────────────────────────────────────────────────
  const handleUploadSuccess = useCallback(
    async (meta: DatasetMeta) => {
      upsertDatasetForPlugin(activePlugin, meta);
      setActiveDataset(meta);
      setShowUpload(false);
      // Refresh dataset list from server
      try {
        const list = await listDatasets(activePlugin);
        setDatasetListForPlugin(activePlugin, list);
      } catch {
        // Local state already updated
      }
    },
    [activePlugin, upsertDatasetForPlugin, setActiveDataset, setDatasetListForPlugin]
  );

  // ── Activate dataset ───────────────────────────────────────────────────
  const handleActivate = useCallback(
    (ds: DatasetMeta) => {
      setActivePlugin(ds.plugin);
      setActiveDataset(ds);
    },
    [setActivePlugin, setActiveDataset]
  );

  // ── Connector actions (from Connectors.tsx) ────────────────────────────
  const handleCreateConnector = useCallback(async () => {
    if (!newName.trim()) return;
    try {
      const c = await createConnector({
        name: newName.trim(),
        connector_type: newType,
        config: newUrl.trim() ? { url: newUrl.trim() } : {},
        plugin_id: activePlugin,
      });
      setConnectors((prev) => (prev ? [c, ...prev] : [c]));
      setShowCreateConnector(false);
      setNewName("");
      setNewUrl("");
      push("Connector created!", "success");
    } catch (err: any) {
      push(err?.message || "Failed to create connector", "error");
    }
  }, [newName, newType, newUrl, activePlugin, push, setConnectors]);

  const handleTestConnector = useCallback(
    async (id: string) => {
      try {
        const res = await testConnector(id);
        push(`${res.status}: ${res.message}`, res.status === "connected" ? "success" : "info");
        setConnectors((prev) =>
          prev ? prev.map((c) => (c.connector_id === id ? { ...c, status: res.status } : c)) : prev
        );
      } catch (err: any) {
        push(err?.message || "Test failed", "error");
      }
    },
    [push, setConnectors]
  );

  const handleBrowseTables = useCallback(
    async (id: string) => {
      if (browsingId === id) {
        setBrowsingId(null);
        return;
      }
      setLoadingTables(true);
      setBrowsingId(id);
      try {
        const res = await getConnectorTables(id);
        setRemoteTables(res.tables);
      } catch (err: any) {
        push(err?.message || "Failed to list tables", "error");
        setBrowsingId(null);
      } finally {
        setLoadingTables(false);
      }
    },
    [browsingId, push]
  );

  const handleSyncTable = useCallback(
    async (connectorId: string, tableName: string) => {
      setSyncing(tableName);
      try {
        const res = await syncConnectorTable(connectorId, tableName, activePlugin);
        push(res.message, "success");
        upsertDatasetForPlugin(activePlugin, res);
        setActiveDataset(res);
        refetchConnectors();
      } catch (err: any) {
        push(err?.message || "Sync failed", "error");
      } finally {
        setSyncing(null);
      }
    },
    [activePlugin, push, refetchConnectors, upsertDatasetForPlugin, setActiveDataset]
  );

  const handleDeleteConnector = useCallback(
    async (id: string) => {
      if (!confirm("Delete this connector?")) return;
      try {
        await deleteConnector(id);
        setConnectors((prev) => (prev ? prev.filter((c) => c.connector_id !== id) : prev));
        if (browsingId === id) setBrowsingId(null);
        push("Connector deleted", "success");
      } catch {
        push("Failed to delete", "error");
      }
    },
    [push, setConnectors, browsingId]
  );

  return (
    <div className="mx-auto max-w-7xl space-y-8 px-6 py-8">
      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-slate-900">Data Sources</h1>
          <p className="mt-1 text-sm text-slate-600">
            Upload files, connect to databases and APIs, and manage your datasets in one place.
          </p>
        </div>
        <Button onClick={() => setShowUpload(true)}>Upload File</Button>
      </div>

      {/* ── Section 1: File upload zone ── */}
      <section>
        <h2 className="mb-3 text-base font-semibold text-slate-800">File Upload</h2>
        <div
          className="flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed border-slate-300 bg-white px-8 py-10 text-center transition hover:border-brand-blue hover:bg-brand-blue/5"
          onClick={() => setShowUpload(true)}
        >
          <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 text-2xl">
            📁
          </div>
          <p className="text-sm font-semibold text-slate-700">Drop or click to upload</p>
          <p className="mt-1 text-xs text-slate-500">
            CSV, Excel (.xlsx/.xls), JSON, JSONL — schema auto-detected
          </p>
          <Button className="mt-4" onClick={() => setShowUpload(true)}>
            Browse Files
          </Button>
        </div>
      </section>

      {/* ── Section 2: DB / API Connectors ── */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold text-slate-800">Database & API Connectors</h2>
          <Button size="sm" onClick={() => setShowCreateConnector(true)}>
            Add Connector
          </Button>
        </div>

        {showCreateConnector && (
          <Card className="mb-4">
            <h3 className="mb-3 text-sm font-semibold text-slate-900">New Connector</h3>
            <div className="space-y-3">
              <input
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-blue focus:outline-none"
                placeholder="Connector name"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
              />
              <select
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-blue focus:outline-none"
                value={newType}
                onChange={(e) => setNewType(e.target.value)}
              >
                {CONNECTOR_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
              <input
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-blue focus:outline-none"
                placeholder="Connection URL / endpoint (optional)"
                value={newUrl}
                onChange={(e) => setNewUrl(e.target.value)}
              />
              <div className="flex gap-2">
                <Button size="sm" onClick={handleCreateConnector}>
                  Create
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setShowCreateConnector(false)}>
                  Cancel
                </Button>
              </div>
            </div>
          </Card>
        )}

        {loadingConnectors && (
          <div className="space-y-3">
            {Array.from({ length: 2 }).map((_, i) => (
              <Skeleton key={i} className="h-16 w-full rounded-xl" />
            ))}
          </div>
        )}

        {!loadingConnectors && (!connectors || connectors.length === 0) && (
          <EmptyState
            title="No connectors"
            description="Add a database or API connector to import data from external systems."
            actionLabel="Add Connector"
            onAction={() => setShowCreateConnector(true)}
          />
        )}

        {!loadingConnectors && connectors && connectors.length > 0 && (
          <div className="space-y-3">
            {connectors.map((c) => (
              <Card key={c.connector_id}>
                <div className="flex items-center justify-between">
                  <div>
                    <h4 className="text-sm font-semibold text-slate-900">{c.name}</h4>
                    <div className="mt-1 flex items-center gap-2">
                      <Badge tone="info">{c.connector_type}</Badge>
                      <Badge tone={statusTone(c.status)}>{c.status}</Badge>
                      {c.last_sync_at && (
                        <span className="text-xs text-slate-400">
                          Last sync: {new Date(c.last_sync_at).toLocaleString()}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Button variant="ghost" size="sm" onClick={() => handleTestConnector(c.connector_id)}>
                      Test
                    </Button>
                    {c.status === "connected" && (
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => handleBrowseTables(c.connector_id)}
                      >
                        {browsingId === c.connector_id ? "Hide Tables" : "Browse Tables"}
                      </Button>
                    )}
                    <button
                      className="px-2 text-xs text-red-500 hover:text-red-700"
                      onClick={() => handleDeleteConnector(c.connector_id)}
                    >
                      Delete
                    </button>
                  </div>
                </div>

                {browsingId === c.connector_id && (
                  <div className="mt-3 border-t border-slate-100 pt-3">
                    {loadingTables ? (
                      <div className="space-y-2">
                        <Skeleton className="h-6 w-full" />
                        <Skeleton className="h-6 w-full" />
                      </div>
                    ) : remoteTables.length === 0 ? (
                      <p className="text-xs text-slate-500">No tables found.</p>
                    ) : (
                      <div>
                        <p className="mb-2 text-xs font-semibold text-slate-700">
                          Available tables ({remoteTables.length})
                        </p>
                        <div className="grid max-h-48 gap-1 overflow-y-auto">
                          {remoteTables.map((tbl) => (
                            <div
                              key={tbl}
                              className="flex items-center justify-between rounded px-2 py-1 hover:bg-slate-50"
                            >
                              <span className="font-mono text-sm text-slate-800">{tbl}</span>
                              <Button
                                variant="secondary"
                                size="sm"
                                disabled={syncing === tbl}
                                onClick={() => handleSyncTable(c.connector_id, tbl)}
                              >
                                {syncing === tbl ? "Syncing…" : "Import"}
                              </Button>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </Card>
            ))}
          </div>
        )}
      </section>

      {/* ── Section 3: Existing datasets ── */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold text-slate-800">
            Datasets
            {datasets.length > 0 && (
              <span className="ml-2 text-sm font-normal text-slate-500">({datasets.length})</span>
            )}
          </h2>
        </div>

        {datasets.length === 0 ? (
          <EmptyState
            title="No datasets yet"
            description="Upload a file or sync a connector table to create your first dataset."
            actionLabel="Upload File"
            onAction={() => setShowUpload(true)}
          />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {datasets.map((ds) => (
              <DatasetCard
                key={ds.dataset_id}
                ds={ds}
                isActive={activeDataset?.dataset_id === ds.dataset_id}
                onActivate={() => handleActivate(ds)}
                onChat={() => {
                  handleActivate(ds);
                  navigate("/chat");
                }}
                onInsights={() => {
                  handleActivate(ds);
                  navigate("/insights");
                }}
                onDelete={() => deleteDatasetForPlugin(activePlugin, ds.dataset_id)}
              />
            ))}
          </div>
        )}
      </section>

      <UploadModal
        open={showUpload}
        onClose={() => setShowUpload(false)}
        onSuccess={handleUploadSuccess}
      />
    </div>
  );
};
