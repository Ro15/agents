import React from "react";
import classNames from "../utils/classNames";

type Tone = "info" | "warning" | "critical" | "success" | "neutral";

const toneStyles: Record<Tone, string> = {
  info: "bg-blue-50 text-blue-700 border-blue-200",
  warning: "bg-amber-50 text-amber-700 border-amber-200",
  critical: "bg-red-50 text-red-700 border-red-200",
  success: "bg-emerald-50 text-emerald-700 border-emerald-200",
  neutral: "bg-slate-100 text-slate-700 border-slate-200",
};

export const Badge: React.FC<{ tone?: Tone; children: React.ReactNode; className?: string }> = ({
  tone = "neutral",
  children,
  className,
}) => {
  return (
    <span
      className={classNames(
        "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold",
        toneStyles[tone],
        className
      )}
    >
      {children}
    </span>
  );
};
