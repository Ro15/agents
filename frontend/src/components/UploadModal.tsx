import React, { useEffect, useMemo, useState } from "react";
import { Button } from "./Button";
import { Select } from "./Select";
import { useToast } from "./Toast";
import { useAppState } from "../state";
import { uploadSalesAuto, getJob, listDatasets } from "../lib/api";

interface Props {
  open: boolean;
  onClose: () => void;
}

type UploadMode = "auto" | "sync";

export const UploadModal: React.FC<Props> = ({ open, onClose }) => {
  const { activePlugin, setActivePlugin, setDatasetListForPlugin, setActiveDatasetId } = useAppState();
  const { push } = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [datasetName, setDatasetName] = useState("");
  const [mode, setMode] = useState<UploadMode>("auto");
  const [uploading, setUploading] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setFile(null);
      setDatasetName("");
      setMode("auto");
      setJobId(null);
      setJobStatus(null);
      setFailure(null);
    }
  }, [open]);

  // Poll job if async
  useEffect(() => {
    if (!jobId) return;
    const timer = setInterval(async () => {
      try {
        const job = await getJob(jobId);
        setJobStatus(job.status);
        if (job.status === "SUCCEEDED" && job.result?.dataset_id) {
          const dsId = job.result.dataset_id;
          const list = await listDatasets(activePlugin);
          setDatasetListForPlugin(activePlugin, list);
          setActiveDatasetId(dsId);
          push("Upload completed", "success");
          clearInterval(timer);
        } else if (job.status === "FAILED") {
          setFailure(job.failure_reason || "Job failed");
          push("Async upload failed", "error");
          clearInterval(timer);
        }
        if (job.status === "SUCCEEDED" || job.status === "FAILED") {
          setJobId(null);
        }
      } catch (err: any) {
        // ignore transient polling errors
      }
    }, 1500);
    return () => clearInterval(timer);
  }, [jobId, activePlugin, setDatasetListForPlugin, setActiveDatasetId, push]);

  const canSubmit = useMemo(() => !!file && !!activePlugin && !uploading, [file, activePlugin, uploading]);

  const handleUpload = async () => {
    if (!file) return;
    setUploading(true);
    setFailure(null);
    try {
      const res = await uploadSalesAuto(activePlugin, file, datasetName || undefined);
      if (res.asyncUsed && res.job_id) {
        setJobId(res.job_id);
        setJobStatus("QUEUED");
        push("Upload queued (async)", "info");
      } else if (res.dataset) {
        const list = await listDatasets(activePlugin);
        setDatasetListForPlugin(activePlugin, list);
        setActiveDatasetId(res.dataset.dataset_id);
        push("Upload complete (sync)", "success");
        onClose();
      }
    } catch (err: any) {
      setFailure(err?.message || "Upload failed");
      push(err?.message || "Upload failed", "error");
    } finally {
      setUploading(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/30 px-4">
      <div className="w-full max-w-lg rounded-xl bg-white p-6 shadow-2xl space-y-4">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="text-lg font-semibold text-slate-900">Upload CSV</h3>
            <p className="text-sm text-slate-600">Choose a CSV that matches the selected plugin schema.</p>
          </div>
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
        </div>

        <div className="grid gap-3">
          <label className="text-xs font-semibold text-slate-700">Plugin</label>
          <Select
            label=""
            value={activePlugin}
            onChange={(e) => setActivePlugin(e.target.value)}
            options={[
              { label: "Retail", value: "retail" },
              { label: "Manufacturing", value: "manufacturing" },
              { label: "Generic", value: "generic" },
            ]}
          />
        </div>

        <div className="grid gap-2">
          <label className="text-xs font-semibold text-slate-700">Dataset name (optional)</label>
          <input
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
            value={datasetName}
            onChange={(e) => setDatasetName(e.target.value)}
            placeholder="e.g., jan_sales"
          />
        </div>

        <div className="grid gap-2">
          <label className="text-xs font-semibold text-slate-700">CSV file</label>
          <input
            type="file"
            accept=".csv"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            disabled={uploading}
            className="text-sm"
          />
          {file && <p className="text-xs text-slate-500">Selected: {file.name}</p>}
        </div>

        <div className="grid gap-2">
          <label className="text-xs font-semibold text-slate-700">Upload mode</label>
          <div className="flex gap-3">
            <label className="flex items-center gap-2 text-sm">
              <input type="radio" value="auto" checked={mode === "auto"} onChange={() => setMode("auto")} />
              Auto (prefer async)
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="radio" value="sync" checked={mode === "sync"} onChange={() => setMode("sync")} />
              Sync only
            </label>
          </div>
        </div>

        {failure && <div className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{failure}</div>}
        {jobStatus && (
          <div className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-700">
            Job {jobId}: {jobStatus}
          </div>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={handleUpload} disabled={!canSubmit}>
            {uploading ? "Uploading..." : mode === "sync" ? "Upload (sync)" : "Upload"}
          </Button>
        </div>
      </div>
    </div>
  );
};
