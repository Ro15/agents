import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listDatasets } from "../lib/api";
import { useAppState } from "../state";
import { Card } from "../components/Card";
import { Select } from "../components/Select";
import { Button } from "../components/Button";
import { Skeleton } from "../components/Skeleton";
import { EmptyState } from "../components/EmptyState";

interface Props {
  onOpenDatasetPicker?: () => void;
}

const PLUGIN_FILTERS = [
  { label: "All plugins", value: "all" },
  { label: "Retail", value: "retail" },
  { label: "Manufacturing", value: "manufacturing" },
  { label: "Generic", value: "generic" },
];

export const DatasetsPage: React.FC<Props> = ({ onOpenDatasetPicker }) => {
  const {
    activePlugin,
    setActivePlugin,
    setDatasetForPlugin,
    datasetListsByPlugin,
    setDatasetListForPlugin,
    deleteDatasetForPlugin,
  } = useAppState();
  const navigate = useNavigate();
  const [filter, setFilter] = useState<string>("all");
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    setFilter(activePlugin || "all");
  }, [activePlugin]);

  useEffect(() => {
    const load = async () => {
      if (filter === "all") return;
      setLoading(true);
      setStatus(null);
      try {
        const remote = await listDatasets(filter);
        if (remote.length > 0) setDatasetListForPlugin(filter, remote);
      } catch (err: any) {
        setStatus(err?.message || "Could not load datasets from API. Showing saved items.");
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [filter, setDatasetListForPlugin]);

  const rows = useMemo(() => {
    if (filter === "all") {
      return Object.entries(datasetListsByPlugin).flatMap(([plugin, list]) =>
        (list || []).map((d) => ({ ...d, plugin: d.plugin || plugin }))
      );
    }
    return (datasetListsByPlugin[filter] || []).map((d) => ({ ...d, plugin: d.plugin || filter }));
  }, [datasetListsByPlugin, filter]);

  const handleSetActive = (plugin: string, datasetId: string) => {
    const list = datasetListsByPlugin[plugin] || [];
    const meta = list.find((d) => d.dataset_id === datasetId);
    if (!meta) return;
    setActivePlugin(plugin);
    setDatasetForPlugin(plugin, meta);
  };

  const handleDelete = (plugin: string, datasetId: string) => {
    deleteDatasetForPlugin(plugin, datasetId);
  };

  const renderRows = () => {
    if (loading) {
      return (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      );
    }

    if (rows.length === 0) {
      return (
        <EmptyState
          title="No datasets found"
          description="Upload data on the Dashboard, then return here to manage it."
          actionLabel="Go to Dashboard"
          onAction={() => navigate("/")}
        />
      );
    }

    return (
      <div className="overflow-auto rounded-lg border border-slate-200">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50">
            <tr>
              <th className="px-3 py-2 text-left font-semibold text-slate-700">Dataset ID</th>
              <th className="px-3 py-2 text-left font-semibold text-slate-700">Plugin</th>
              <th className="px-3 py-2 text-left font-semibold text-slate-700">Filename</th>
              <th className="px-3 py-2 text-left font-semibold text-slate-700">Rows</th>
              <th className="px-3 py-2 text-left font-semibold text-slate-700">Ingested at</th>
              <th className="px-3 py-2 text-left font-semibold text-slate-700">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.plugin}-${row.dataset_id}`} className="odd:bg-white even:bg-slate-50">
                <td className="px-3 py-2 font-semibold text-slate-900">{row.dataset_id}</td>
                <td className="px-3 py-2 text-slate-700">{row.plugin}</td>
                <td className="px-3 py-2 text-slate-700">{row.filename ?? "n/a"}</td>
                <td className="px-3 py-2 text-slate-700">{row.row_count ?? "?"}</td>
                <td className="px-3 py-2 text-slate-700">{row.ingested_at ?? "n/a"}</td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" onClick={() => handleSetActive(row.plugin, row.dataset_id)}>
                      Set Active
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => {
                        handleSetActive(row.plugin, row.dataset_id);
                        navigate("/chat");
                      }}
                    >
                      Open Chat
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        handleSetActive(row.plugin, row.dataset_id);
                        navigate("/insights");
                      }}
                    >
                      Run Insights
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => handleDelete(row.plugin, row.dataset_id)}>
                      Delete
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  return (
    <div className="mx-auto max-w-7xl px-6 py-8 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-slate-900">Datasets</h1>
          <p className="text-sm text-slate-600">Review, activate, and clean up datasets per plugin.</p>
        </div>
        {onOpenDatasetPicker && (
          <Button variant="secondary" size="sm" onClick={onOpenDatasetPicker}>
            Open picker
          </Button>
        )}
      </div>

      <Card
        title="Filters"
        actions={
          <Button variant="ghost" size="sm" onClick={() => navigate("/")}>
            Upload new data
          </Button>
        }
      >
        <div className="flex flex-wrap items-center gap-4">
          <Select
            label="Plugin"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            options={PLUGIN_FILTERS}
          />
          {status && <p className="text-xs text-amber-600">{status}</p>}
        </div>
      </Card>

      <Card title="Datasets list">{renderRows()}</Card>
    </div>
  );
};
