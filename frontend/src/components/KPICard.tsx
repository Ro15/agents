import React from "react";
import classNames from "../utils/classNames";

interface Props {
  title: string;
  value: string | number;
  subtitle?: string;
  trend?: { value: number; label?: string };
  icon?: React.ReactNode;
  className?: string;
}

export const KPICard: React.FC<Props> = ({ title, value, subtitle, trend, icon, className }) => {
  const trendUp = trend && trend.value > 0;
  const trendDown = trend && trend.value < 0;
  const trendFlat = trend && trend.value === 0;

  return (
    <div
      className={classNames(
        "relative overflow-hidden rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition-shadow hover:shadow-md",
        className
      )}
    >
      <div className="flex items-start justify-between">
        <div className="space-y-1">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{title}</p>
          <p className="text-2xl font-bold text-slate-900">{value}</p>
          {subtitle && <p className="text-xs text-slate-500">{subtitle}</p>}
        </div>
        {icon && (
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-blue/10 text-brand-blue">
            {icon}
          </div>
        )}
      </div>
      {trend && (
        <div className="mt-3 flex items-center gap-1.5 text-xs font-medium">
          {trendUp && (
            <>
              <span className="flex items-center gap-0.5 text-emerald-600">
                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 19.5l15-15m0 0H8.25m11.25 0v11.25" />
                </svg>
                +{Math.abs(trend.value).toFixed(1)}%
              </span>
              <span className="text-slate-500">{trend.label || "vs previous period"}</span>
            </>
          )}
          {trendDown && (
            <>
              <span className="flex items-center gap-0.5 text-red-600">
                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 4.5l15 15m0 0V8.25m0 11.25H8.25" />
                </svg>
                {Math.abs(trend.value).toFixed(1)}%
              </span>
              <span className="text-slate-500">{trend.label || "vs previous period"}</span>
            </>
          )}
          {trendFlat && <span className="text-slate-500">No change {trend.label || "vs previous period"}</span>}
        </div>
      )}
      {/* Decorative gradient */}
      <div className="pointer-events-none absolute -right-6 -top-6 h-20 w-20 rounded-full bg-brand-blue/5" />
    </div>
  );
};
