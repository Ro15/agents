import React from "react";
import classNames from "../utils/classNames";

export const Skeleton: React.FC<{ className?: string }> = ({ className }) => {
  return <div className={classNames("animate-pulse rounded-md bg-slate-200/80", className)} />;
};
