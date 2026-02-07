import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAppState } from "../state";
import { Card } from "../components/Card";
import { Button } from "../components/Button";
import { Badge } from "../components/Badge";
import { EmptyState } from "../components/EmptyState";
import { useToast } from "../components/Toast";
import { profileDataset, getDataCatalog, updateColumnDescription } from "../lib/api";
import type { ColumnProfileInfo } from "../types";

export const DataCatalogPage: React.FC = () => {
  const { activePlugin, activeDataset } = useAppState();
  const navigate = useNavigate();
  const { push } = useToast();
  const [columns, setColumns] = useState<ColumnProfileInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [profiling, setProfiling] = useState(false);
  const [editingCol, setEditingCol] = useState<string | null>(null);
  const [descDraft, setDescDraft] = useState("");

  const datasetId = activeDataset?.dataset_id;

  const fetchCatalog = async () => {
    if (!datasetId) return;
    setLoading(true);
    try {
      const res = await getDataCatalog(datasetId);
      setColumns(res.columns);
    } catch {
      setColumns([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCatalog();
  }, [datasetId]);

  const handleProfile = async () => {
    if (!datasetId) return;
    setProfiling(true);
    try {
      const res = await profileDataset(datasetId);
      setColumns(res.profiles);
      push(`Profiled ${res.columns_profiled} columns`, "success");
    } catch (err: any) {
      push(err?.message || "Profiling failed", "error");
    } finally {
      setProfiling(false);
    }
  };

  const handleSaveDescription = async (columnName: string) => {
    if (!datasetId) return;
    try {
      await updateColumnDescription(datasetId, columnName, descDraft);
      setColumns((prev) =>
        prev.map((c) => (c.column_name === columnName ? { ...c, description: descDraft } : c))
      );
      setEditingCol(null);
      push("Description saved", "success");
    } catch (err: any) {
      push(err?.message || "Failed to save", "error");
    }
  };

  if (!datasetId) {
    return (
      <div className="mx-auto max-w-5xl px-6 py-8">
        <EmptyState
          title="No dataset selected"
          description="Select a dataset to view and manage its data catalog."
          actionLabel="Go to Dashboard"
          onAction={() => navigate("/")}
        />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Data Catalog</h1>
          <p className="text-sm text-slate-600">
            Auto-profiled column statistics and descriptions for dataset{" "}
            <span className="font-mono">{datasetId.slice(0, 8)}...</span>
          </p>
        </div>
        <div className="flex gap-2">
          <Button onClick={handleProfile} disabled={profiling}>
            {profiling ? "Profiling..." : "Run Profiling"}
          </Button>
          <Button variant="secondary" size="sm" onClick={() => navigate("/chat")}>
            Back to Chat
          </Button>
        </div>
      </div>

      {loading && <p className="text-sm text-slate-500">Loading catalog...</p>}

      {!loading && columns.length === 0 && (
        <EmptyState
          title="No column profiles"
          description="Run profiling to generate column statistics for this dataset."
          actionLabel="Run Profiling"
          onAction={handleProfile}
        />
      )}

      {columns.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-600">
              <tr>
                <th className="px-4 py-3">Column</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Nulls</th>
                <th className="px-4 py-3">Distinct</th>
                <th className="px-4 py-3">Min</th>
                <th className="px-4 py-3">Max</th>
                <th className="px-4 py-3">Mean</th>
                <th className="px-4 py-3">Samples</th>
                <th className="px-4 py-3">Description</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {columns.map((col) => (
                <tr key={col.column_name} className="hover:bg-slate-50">
                  <td className="px-4 py-2 font-medium text-slate-900">{col.column_name}</td>
                  <td className="px-4 py-2">
                    <Badge tone="neutral">{col.data_type || "?"}</Badge>
                  </td>
                  <td className="px-4 py-2 text-slate-600">{col.null_count ?? "-"}</td>
                  <td className="px-4 py-2 text-slate-600">{col.distinct_count ?? "-"}</td>
                  <td className="px-4 py-2 text-slate-600 truncate max-w-[100px]" title={col.min_value || ""}>
                    {col.min_value || "-"}
                  </td>
                  <td className="px-4 py-2 text-slate-600 truncate max-w-[100px]" title={col.max_value || ""}>
                    {col.max_value || "-"}
                  </td>
                  <td className="px-4 py-2 text-slate-600">
                    {col.mean_value !== null && col.mean_value !== undefined
                      ? col.mean_value.toLocaleString(undefined, { maximumFractionDigits: 2 })
                      : "-"}
                  </td>
                  <td className="px-4 py-2 text-xs text-slate-500">
                    {col.sample_values?.slice(0, 3).join(", ") || "-"}
                  </td>
                  <td className="px-4 py-2">
                    {editingCol === col.column_name ? (
                      <div className="flex gap-1">
                        <input
                          className="rounded border border-slate-300 px-2 py-1 text-xs w-32 focus:border-brand-blue focus:outline-none"
                          value={descDraft}
                          onChange={(e) => setDescDraft(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") handleSaveDescription(col.column_name);
                            if (e.key === "Escape") setEditingCol(null);
                          }}
                          autoFocus
                        />
                        <button
                          className="text-xs text-brand-blue hover:underline"
                          onClick={() => handleSaveDescription(col.column_name)}
                        >
                          Save
                        </button>
                      </div>
                    ) : (
                      <button
                        className="text-xs text-slate-500 hover:text-brand-blue"
                        onClick={() => {
                          setEditingCol(col.column_name);
                          setDescDraft(col.description || "");
                        }}
                      >
                        {col.description || "Add description..."}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
