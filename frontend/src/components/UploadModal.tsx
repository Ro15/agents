import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "./Button";
import { Badge } from "./Badge";
import { useToast } from "./Toast";
import { useAppState } from "../state";
import { uploadUniversal, uploadSalesSync, listDatasets } from "../lib/api";
import { SchemaPreview } from "./SchemaPreview";
import type { DatasetMeta, UploadResult } from "../types";

interface Props {
  open: boolean;
  onClose: () => void;
  onSuccess?: (meta: DatasetMeta) => void;
}

const ACCEPTED_EXTENSIONS = ".csv,.tsv,.xlsx,.xls,.json,.jsonl,.ndjson";

export const UploadModal: React.FC<Props> = ({ open, onClose, onSuccess }) => {
  const { activePlugin, setDatasetListForPlugin, setActiveDatasetId } = useAppState();
  const { push } = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [datasetName, setDatasetName] = useState("");
  const [sheetName, setSheetName] = useState("");
  const [uploading, setUploading] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);

  useEffect(() => {
    if (!open) {
      setFile(null);
      setDatasetName("");
      setSheetName("");
      setFailure(null);
      setResult(null);
    }
  }, [open]);

  const fileExt = file ? file.name.split(".").pop()?.toLowerCase() : null;
  const isExcel = fileExt === "xlsx" || fileExt === "xls";
  const canSubmit = useMemo(() => !!file && !!activePlugin && !uploading, [file, activePlugin, uploading]);

  const handleUpload = useCallback(async () => {
    if (!file) return;
    setUploading(true);
    setFailure(null);
    setResult(null);
    try {
      const res = await uploadUniversal(
        file,
        activePlugin,
        datasetName || undefined,
        sheetName || undefined,
      );
      setResult(res);
      const list = await listDatasets(activePlugin);
      setDatasetListForPlugin(activePlugin, list);
      setActiveDatasetId(res.dataset_id);
      push(res.message || "Upload complete!", "success");
      onSuccess?.(res);
    } catch (err: any) {
      setFailure(err?.message || "Upload failed");
      push(err?.message || "Upload failed", "error");
    } finally {
      setUploading(false);
    }
  }, [file, activePlugin, datasetName, sheetName, push, onSuccess, setDatasetListForPlugin, setActiveDatasetId]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/30 px-4">
      <div className="w-full max-w-xl rounded-xl bg-white p-6 shadow-2xl space-y-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="text-lg font-semibold text-slate-900">Upload Data File</h3>
            <p className="text-sm text-slate-600">
              Supports CSV, Excel (.xlsx/.xls), JSON, and JSONL. Schema is auto-detected.
            </p>
          </div>
          <Button variant="ghost" onClick={onClose}>Close</Button>
        </div>

        {/* File picker */}
        <div className="grid gap-2">
          <label className="text-xs font-semibold text-slate-700">File</label>
          <input
            type="file"
            accept={ACCEPTED_EXTENSIONS}
            onChange={(e) => { setFile(e.target.files?.[0] || null); setResult(null); }}
            disabled={uploading}
            className="text-sm"
          />
          {file && (
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <span>{file.name}</span>
              <Badge tone="info">{fileExt?.toUpperCase()}</Badge>
              <span>{(file.size / 1024).toFixed(0)} KB</span>
            </div>
          )}
        </div>

        {/* Dataset name */}
        <div className="grid gap-2">
          <label className="text-xs font-semibold text-slate-700">Dataset name (optional)</label>
          <input
            className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-blue focus:outline-none"
            value={datasetName}
            onChange={(e) => setDatasetName(e.target.value)}
            placeholder="e.g., jan_sales"
          />
        </div>

        {/* Sheet name (Excel only) */}
        {isExcel && (
          <div className="grid gap-2">
            <label className="text-xs font-semibold text-slate-700">Sheet name or index (optional)</label>
            <input
              className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-blue focus:outline-none"
              value={sheetName}
              onChange={(e) => setSheetName(e.target.value)}
              placeholder="Sheet1 or 0 (first sheet)"
            />
          </div>
        )}

        {/* Error */}
        {failure && (
          <div className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{failure}</div>
        )}

        {/* Upload result & schema preview */}
        {result && (
          <div className="space-y-3">
            <div className="rounded-md bg-green-50 px-3 py-2 text-xs text-green-800">
              {result.message}
            </div>
            <div className="flex flex-wrap gap-2 text-xs">
              <Badge tone="success">{result.row_count} rows</Badge>
              {result.column_count && <Badge tone="info">{result.column_count} columns</Badge>}
              {result.table_name && <Badge tone="neutral">Table: {result.table_name}</Badge>}
              {result.load_errors ? <Badge tone="warning">{result.load_errors} errors</Badge> : null}
            </div>
            {result.schema && result.schema.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-slate-700 mb-1">Detected Schema</p>
                <SchemaPreview columns={result.schema} />
              </div>
            )}
          </div>
        )}

        {/* Actions */}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            {result ? "Done" : "Cancel"}
          </Button>
          {!result && (
            <Button onClick={handleUpload} disabled={!canSubmit}>
              {uploading ? "Uploading..." : "Upload & Ingest"}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
};
