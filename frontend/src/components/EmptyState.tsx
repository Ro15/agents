import React from "react";
import { Button } from "./Button";

interface Props {
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
}

export const EmptyState: React.FC<Props> = ({ title, description, actionLabel, onAction }) => (
  <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-slate-300 bg-white px-6 py-8 text-center">
    <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
    <p className="max-w-md text-sm text-slate-600">{description}</p>
    {actionLabel && onAction && (
      <Button className="mt-2" onClick={onAction}>
        {actionLabel}
      </Button>
    )}
  </div>
);
