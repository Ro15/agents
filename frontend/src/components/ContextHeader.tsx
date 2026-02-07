import React from "react";
import { useNavigate } from "react-router-dom";
import { useAppState } from "../state";
import { Button } from "./Button";
import { Badge } from "./Badge";

interface Props {
  onChangeDataset: () => void;
}

export const ContextHeader: React.FC<Props> = ({ onChangeDataset }) => {
  const { activePlugin, activeDataset } = useAppState();
  const navigate = useNavigate();

  return (
    <div className="border-b border-slate-200 bg-slate-900 text-slate-50">
      <div className="mx-auto flex max-w-7xl flex-col gap-3 px-4 py-3 sm:px-6 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-4">
          <div className="rounded-lg bg-white/10 px-3 py-2">
            <p className="text-[11px] uppercase tracking-wide text-slate-200">Active Plugin</p>
            <div className="text-sm font-semibold text-white">{activePlugin || "None"}</div>
          </div>
          <div className="rounded-lg bg-white/10 px-3 py-2">
            <p className="text-[11px] uppercase tracking-wide text-slate-200">Active Dataset</p>
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-white">
                {activeDataset?.dataset_id ?? "None selected"}
              </span>
              {activeDataset?.row_count !== undefined && <Badge tone="neutral">{activeDataset.row_count} rows</Badge>}
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="ghost" className="bg-white/10 text-white hover:bg-white/20" onClick={() => navigate("/plugins")}>
            Switch Plugin
          </Button>
          <Button variant="secondary" onClick={onChangeDataset}>
            Change Dataset
          </Button>
          <Button onClick={() => navigate("/chat")}>Go to Chat</Button>
        </div>
      </div>
    </div>
  );
};
