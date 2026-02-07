import React, { useState } from "react";
import classNames from "../utils/classNames";

interface Props {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}

export const Collapsible: React.FC<Props> = ({ title, defaultOpen = false, children }) => {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <button
        className="flex w-full items-center justify-between px-3 py-2 text-left text-sm font-semibold text-slate-800"
        onClick={() => setOpen((o) => !o)}
      >
        <span>{title}</span>
        <span className={classNames("transition-transform", open ? "rotate-90" : "")}>›</span>
      </button>
      {open && <div className="border-t border-slate-100 px-3 py-2 text-sm text-slate-700">{children}</div>}
    </div>
  );
};
