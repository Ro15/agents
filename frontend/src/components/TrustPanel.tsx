import React from "react";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { SqlBlock } from "./SqlBlock";

interface Props {
  confidence?: string;
  dataLastUpdated?: string | null;
  sql: string | string[] | Record<string, string> | null;
}

export const TrustPanel: React.FC<Props> = ({ confidence, dataLastUpdated, sql }) => {
  return (
    <div className="mt-3 space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
      <div className="flex items-center gap-2">
        <ConfidenceBadge confidence={confidence} />
        {dataLastUpdated && <span>Data last updated: {dataLastUpdated}</span>}
      </div>
      <SqlBlock sql={sql} />
    </div>
  );
};
