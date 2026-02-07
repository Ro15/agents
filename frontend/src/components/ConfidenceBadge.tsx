import React from "react";
import { Badge } from "./Badge";

export const ConfidenceBadge: React.FC<{ confidence?: string }> = ({ confidence }) => {
  if (!confidence) return null;
  const tone = confidence === "high" ? "success" : confidence === "medium" ? "warning" : "critical";
  return <Badge tone={tone}>{`Confidence: ${confidence}`}</Badge>;
};
