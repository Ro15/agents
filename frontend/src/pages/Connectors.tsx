import React, { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useAppState } from "../state";
import { Card } from "../components/Card";
import { Button } from "../components/Button";
import { Badge } from "../components/Badge";
import { EmptyState } from "../components/EmptyState";
import { Skeleton } from "../components/Skeleton";
import { SchemaPreview } from "../components/SchemaPreview";
import { useToast } from "../components/Toast";
import { useApiData } from "../hooks/useApiData";
import {
  listConnectors, createConnector, deleteConnector, testConnector,
  getConnectorTables, syncConnectorTable,
} from "../lib/api";
import type { DataConnector, RemoteTablesResult } from "../types";

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

export const ConnectorsPage: React.FC = () => {
  const { activePlugin, upsertDatasetForPlugin, setActiveDataset } = useAppState();
  const navigate = useNavigate();
  const { push } = useToast();
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newType, setNewType] = useState("postgresql");
  const [newUrl, setNewUrl] = useState("");

  // Remote table browser state
  const [browsingId, setBrowsingId] = useState<string | null>(null);
  const [remoteTables, setRemoteTables] = useState<string[]>([]);
  const [loadingTables, setLoadingTables] = useState(false);
  const [syncing, setSyncing] = useState<string | null>(null);

  const { data: connectors, loading, setData: setConnectors, refetch } = useApiData(
    () => listConnectors(activePlugin),
    [activePlugin],
  );

  const items = connectors ?? [];

  const handleCreate = useCallback(async () => {
    if (!newName.trim()) return;
    try {
      const c = await createConnector({
        name: newName.trim(),
        connector_type: newType,
        config: newUrl.trim() ? { url: newUrl.trim() } : {},
        plugin_id: activePlugin,
      });
      setConnectors((prev) => (prev ? [c, ...prev] : [c]));
      setShowCreate(false);
      setNewName(""); setNewUrl("");
      push("Connector created!", "success");
    } catch (err: any) {
      push(err?.message || "Failed to create connector", "error");
    }
  }, [newName, newType, newUrl, activePlugin, push, setConnectors]);

  const handleTest = useCallback(async (id: string) => {
    try {
      const res = await testConnector(id);
      push(`${res.status}: ${res.message}`, res.status === "connected" ? "success" : "info");
      setConnectors((prev) =>
        prev ? prev.map((c) => (c.connector_id === id ? { ...c, status: res.status } : c)) : prev
      );
    } catch (err: any) {
      push(err?.message || "Test failed", "error");
    }
  }, [push, setConnectors]);

  const handleBrowseTables = useCallback(async (id: string) => {
    if (browsingId === id) { setBrowsingId(null); return; }
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
  }, [browsingId, push]);

  const handleSyncTable = useCallback(async (connectorId: string, tableName: string) => {
    setSyncing(tableName);
    try {
      const res = await syncConnectorTable(connectorId, tableName, activePlugin);
      push(res.message, "success");
      // Add the new dataset to state
      upsertDatasetForPlugin(activePlugin, res);
      setActiveDataset(res);
      refetch();
    } catch (err: any) {
      push(err?.message || "Sync failed", "error");
    } finally {
      setSyncing(null);
    }
  }, [activePlugin, push, refetch, upsertDatasetForPlugin, setActiveDataset]);

  const handleDelete = useCallback(async (id: string) => {
    if (!confirm("Delete this connector?")) return;
    try {
      await deleteConnector(id);
      setConnectors((prev) => prev ? prev.filter((c) => c.connector_id !== id) : prev);
      if (browsingId === id) setBrowsingId(null);
      push("Connector deleted", "success");
    } catch {
      push("Failed to delete", "error");
    }
  }, [push, setConnectors, browsingId]);

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Data Connectors</h1>
          <p className="text-sm text-slate-600">Connect to databases, APIs, cloud storage, Excel, and Google Sheets.</p>
        </div>
        <div className="flex gap-2">
          <Button onClick={() => setShowCreate(true)}>Add Connector</Button>
          <Button variant="secondary" size="sm" onClick={() => navigate("/chat")}>Back to Chat</Button>
        </div>
      </div>

      {showCreate && (
        <Card className="mb-6">
          <h3 className="text-sm font-semibold text-slate-900 mb-3">New Connector</h3>
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
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
            <input
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-blue focus:outline-none"
              placeholder="Connection URL / endpoint (optional)"
              value={newUrl}
              onChange={(e) => setNewUrl(e.target.value)}
            />
            <div className="flex gap-2">
              <Button size="sm" onClick={handleCreate}>Create</Button>
              <Button variant="ghost" size="sm" onClick={() => setShowCreate(false)}>Cancel</Button>
            </div>
          </div>
        </Card>
      )}

      {loading && (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-20 w-full rounded-xl" />
          ))}
        </div>
      )}

      {!loading && items.length === 0 && (
        <EmptyState
          title="No connectors"
          description="Add a data source connector to import data from external systems."
          actionLabel="Add Connector"
          onAction={() => setShowCreate(true)}
        />
      )}

      {!loading && (
        <div className="space-y-3">
          {items.map((c) => (
            <Card key={c.connector_id}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div>
                    <h4 className="text-sm font-semibold text-slate-900">{c.name}</h4>
                    <div className="mt-1 flex items-center gap-2">
                      <Badge tone="info">{c.connector_type}</Badge>
                      <Badge tone={statusTone(c.status)}>{c.status}</Badge>
                      {c.last_sync_at && (
                        <span className="text-xs text-slate-400">Last sync: {new Date(c.last_sync_at).toLocaleString()}</span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex gap-2">
                  <Button variant="ghost" size="sm" onClick={() => handleTest(c.connector_id)}>Test</Button>
                  {c.status === "connected" && (
                    <Button variant="secondary" size="sm" onClick={() => handleBrowseTables(c.connector_id)}>
                      {browsingId === c.connector_id ? "Hide Tables" : "Browse Tables"}
                    </Button>
                  )}
                  <button className="text-xs text-red-500 hover:text-red-700 px-2" onClick={() => handleDelete(c.connector_id)}>
                    Delete
                  </button>
                </div>
              </div>

              {/* Remote table browser */}
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
                      <p className="text-xs font-semibold text-slate-700 mb-2">
                        Available tables ({remoteTables.length})
                      </p>
                      <div className="grid gap-1 max-h-48 overflow-y-auto">
                        {remoteTables.map((tbl) => (
                          <div key={tbl} className="flex items-center justify-between rounded px-2 py-1 hover:bg-slate-50">
                            <span className="text-sm font-mono text-slate-800">{tbl}</span>
                            <Button
                              variant="secondary" size="sm"
                              disabled={syncing === tbl}
                              onClick={() => handleSyncTable(c.connector_id, tbl)}
                            >
                              {syncing === tbl ? "Syncing..." : "Import"}
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
    </div>
  );
};
