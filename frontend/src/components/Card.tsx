import React from "react";
import classNames from "../utils/classNames";

interface CardProps {
  title?: string;
  children: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}

export const Card: React.FC<CardProps> = ({ title, actions, children, className }) => {
  return (
    <div className={classNames("rounded-xl border border-slate-200 bg-white shadow-sm", className)}>
      {(title || actions) && (
        <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
          {title && <h3 className="text-sm font-semibold text-slate-800">{title}</h3>}
          {actions}
        </div>
      )}
      <div className="p-4">{children}</div>
    </div>
  );
};
