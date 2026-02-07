import React from "react";
import { useNavigate } from "react-router-dom";
import type { DatasetMeta } from "../types";
import { Button } from "./Button";

interface Props {
  open: boolean;
  onClose: () => void;
  plugin: string;
  datasets: DatasetMeta[];
  activeDatasetId?: string | null;
  onSelect: (meta: DatasetMeta | null) => void;
}

export const DatasetPickerModal: React.FC<Props> = ({ open, onClose, plugin, datasets, activeDatasetId, onSelect }) => {
  const navigate = useNavigate();
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
      <div className="w-full max-w-2xl rounded-xl bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <div>
            <p className="text-xs uppercase tracking-wide text-slate-500">Change dataset</p>
            <h3 className="text-lg font-semibold text-slate-900">Datasets for {plugin}</h3>
          </div>
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
        </div>
        <div className="max-h-[60vh] overflow-y-auto px-5 py-4">
          {datasets.length === 0 && (
            <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-center text-sm text-slate-600">
              No datasets saved for this plugin yet. Upload one from Dashboard.
            </div>
          )}
          {datasets.length > 0 && (
            <ul className="divide-y divide-slate-200">
              {datasets.map((ds) => (
                <li key={ds.dataset_id} className="flex items-center justify-between gap-3 py-3">
                  <div>
                    <div className="text-sm font-semibold text-slate-900">{ds.dataset_id}</div>
                    <div className="text-xs text-slate-500">
                      {ds.filename && <span>{ds.filename} · </span>}
                      {ds.row_count !== undefined && <span>{ds.row_count} rows · </span>}
                      {ds.ingested_at && <span>{ds.ingested_at}</span>}
                    </div>
                  </div>
                  <Button
                    variant={ds.dataset_id === activeDatasetId ? "secondary" : "primary"}
                    onClick={() => {
                      onSelect(ds);
                      onClose();
                    }}
                  >
                    {ds.dataset_id === activeDatasetId ? "Active" : "Set Active"}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="flex items-center justify-between border-t border-slate-200 px-5 py-3">
          <Button variant="ghost" onClick={() => navigate("/datasets")}>
            Manage datasets
          </Button>
          <Button variant="secondary" onClick={() => onSelect(null)}>
            Clear selection
          </Button>
        </div>
      </div>
    </div>
  );
};
