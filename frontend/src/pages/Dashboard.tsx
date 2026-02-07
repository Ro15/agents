import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listDatasets, uploadSalesAuto } from "../lib/api";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { Select } from "../components/Select";
import { useAppState } from "../state";
import { UploadModal } from "../components/UploadModal";
import { Skeleton } from "../components/Skeleton";
import { EmptyState } from "../components/EmptyState";

const PLUGIN_OPTIONS = [
  { label: "Retail", value: "retail" },
  { label: "Manufacturing", value: "manufacturing" },
  { label: "Generic", value: "generic" },
];

interface Props {
  onOpenDatasetPicker?: () => void;
}

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
  const navigate = useNavigate();

  const pluginDatasets = datasetListsByPlugin[activePlugin] || [];

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
        // ensure the new dataset is in the local list immediately, then activate it
        upsertDatasetForPlugin(activePlugin, res.dataset);
        setActiveDataset(res.dataset);
        setStatus(`Uploaded ${file.name}`);
        // refresh list in background so we pick up any server-side metadata
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
        // ensure the new dataset is in the local list immediately, then activate it
        upsertDatasetForPlugin(activePlugin, uploadRes.dataset);
        setActiveDataset(uploadRes.dataset);
        setStatus("Sample data uploaded.");
        // refresh list in background so we pick up any server-side metadata
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

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6 px-6 py-8">
      <header className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-brand-blue">Plugin Analyst</p>
          <h1 className="text-3xl font-bold text-slate-900">Dashboard</h1>
          <p className="text-sm text-slate-600">Pick a plugin, upload a dataset, then chat or run insights.</p>
        </div>
        <div className="flex gap-3">
          <Button variant="secondary" onClick={() => navigate("/chat")}>
            Go to Chat
          </Button>
          <Button onClick={() => navigate("/insights")}>Go to Insights</Button>
        </div>
      </header>

      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Active Plugin">
          <Select
            label="Select plugin"
            value={activePlugin}
            onChange={(e) => setActivePlugin(e.target.value)}
            options={PLUGIN_OPTIONS}
          />
          <Button variant="ghost" className="mt-3" onClick={() => navigate(`/plugins/${activePlugin}`)}>
            View plugin details
          </Button>
        </Card>

        <Card
          title="Active Dataset"
          actions={
            onOpenDatasetPicker && (
              <Button variant="secondary" size="sm" onClick={onOpenDatasetPicker}>
                Change dataset
              </Button>
            )
          }
        >
          {activeDataset ? (
            <div className="space-y-1 text-sm text-slate-700">
              <div className="font-semibold text-slate-900">{activeDataset.dataset_id}</div>
              <div className="text-xs text-slate-500">
                {activeDataset.filename && <span>{activeDataset.filename} · </span>}
                {activeDataset.row_count !== undefined && <span>{activeDataset.row_count} rows · </span>}
                {activeDataset.ingested_at && <span>{activeDataset.ingested_at}</span>}
              </div>
            </div>
          ) : (
            <EmptyState
              title="No dataset selected"
              description="Upload a CSV or pick from saved datasets."
              actionLabel="Open picker"
              onAction={onOpenDatasetPicker}
            />
          )}
        </Card>
      </div>

      <Card
        title="Upload CSV"
        actions={
          <div className="flex gap-2">
            <Button variant="ghost" onClick={handleLoadSample} disabled={uploading}>
              Load sample data
            </Button>
            <Button onClick={() => setShowUploadModal(true)} disabled={uploading}>
              {uploading ? "Uploading..." : "Upload CSV"}
            </Button>
          </div>
        }
      >
        <p className="text-sm text-slate-600">
          CSV should match the active plugin schema. The upload is bound to the selected plugin.
        </p>
        {status && <p className="mt-3 text-sm text-slate-700">{status}</p>}
      </Card>

      <Card title="Recent datasets" actions={<Button variant="ghost" size="sm" onClick={() => navigate("/datasets")}>Manage datasets</Button>}>
        {loadingList ? (
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : pluginDatasets.length === 0 ? (
          <EmptyState title="No datasets yet" description="Upload a CSV or load a sample to see it here." actionLabel="Upload CSV" onAction={() => setShowUploadModal(true)} />
        ) : (
          <ul className="divide-y divide-slate-200">
            {pluginDatasets.slice(0, 5).map((ds) => (
              <li key={ds.dataset_id} className="flex items-center justify-between py-2 text-sm">
                <div>
                  <div className="font-semibold text-slate-900">{ds.dataset_id}</div>
                  <div className="text-xs text-slate-500">
                    {ds.row_count ?? "?"} rows · {ds.ingested_at ?? "no ingest time"}
                  </div>
                </div>
                <Button variant="secondary" size="sm" onClick={() => setActiveDataset(ds)}>
                  Set Active
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <UploadModal
        open={showUploadModal}
        onClose={() => setShowUploadModal(false)}
        onSuccess={(meta) => {
          upsertDatasetForPlugin(activePlugin, meta);
          setActiveDataset(meta);
          setStatus(`Uploaded ${meta.filename || meta.dataset_id}`);
        }}
      />

      <Card title="Demo flow">
        <ol className="list-decimal space-y-2 pl-4 text-sm text-slate-700">
          <li>Select a plugin in the header.</li>
          <li>Upload a CSV or load a sample to bind a dataset.</li>
          <li>Open Chat and click a suggested question to see SQL + trust signals.</li>
          <li>Run Insights to generate findings for the active dataset.</li>
          <li>Return here anytime to switch plugins or datasets.</li>
        </ol>
      </Card>
    </div>
  );
};
