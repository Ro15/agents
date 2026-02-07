import React from "react";
import { NavLink } from "react-router-dom";
import { Button } from "./Button";
import { API_BASE } from "../lib/api";
import classNames from "../utils/classNames";

const navItemClass = ({ isActive }: { isActive: boolean }) =>
  classNames(
    "rounded-md px-3 py-1 text-sm font-medium transition-colors",
    isActive ? "bg-brand-blue/10 text-brand-blue" : "text-slate-700 hover:text-brand-blue hover:bg-slate-100"
  );

export const TopNav: React.FC = () => {
  return (
    <nav className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 sm:px-6">
        <div className="flex items-center gap-3">
          <div className="grid h-9 w-9 place-items-center rounded-lg bg-brand-blue text-sm font-bold text-white">PA</div>
          <div>
            <p className="text-sm font-semibold text-brand-blue">Plugin Analyst</p>
            <p className="text-xs text-slate-500">Sector-agnostic data co-pilot</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <NavLink to="/" className={navItemClass}>
            Dashboard
          </NavLink>
          <NavLink to="/plugins" className={navItemClass}>
            Plugins
          </NavLink>
          <NavLink to="/datasets" className={navItemClass}>
            Datasets
          </NavLink>
          <NavLink to="/chat" className={navItemClass}>
            Chat
          </NavLink>
          <NavLink to="/insights" className={navItemClass}>
            Insights
          </NavLink>
        </div>
        <div className="hidden sm:block">
          <Button variant="secondary" onClick={() => window.open(`${API_BASE}/docs`, "_blank")}>
            API Docs
          </Button>
        </div>
      </div>
    </nav>
  );
};
