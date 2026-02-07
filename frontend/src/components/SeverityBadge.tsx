import React from "react";
import { Badge } from "./Badge";

export const SeverityBadge: React.FC<{ severity: "info" | "warning" | "critical" }> = ({ severity }) => {
  const tone = severity === "critical" ? "critical" : severity === "warning" ? "warning" : "info";
  return <Badge tone={tone}>{severity}</Badge>;
};
