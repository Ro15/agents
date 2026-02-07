import React from "react";
import { Button } from "./Button";
import { Collapsible } from "./Collapsible";
import { useToast } from "./Toast";

export const SqlBlock: React.FC<{ sql: string | string[] | Record<string, string> | null }> = ({ sql }) => {
  const { push } = useToast();
  if (!sql) return null;

  const sqlList: { label: string; value: string }[] = Array.isArray(sql)
    ? sql.map((s, i) => ({ label: `Query ${i + 1}`, value: s }))
    : typeof sql === "string"
    ? [{ label: "SQL", value: sql }]
    : Object.entries(sql).map(([k, v]) => ({ label: k, value: v }));

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      push("SQL copied", "success");
    } catch {
      push("Failed to copy", "error");
    }
  };

  return (
    <div className="space-y-2">
      {sqlList.map((item) => (
        <Collapsible key={item.label} title={`${item.label} (show/hide)`} defaultOpen={false}>
          <div className="mb-2 flex justify-end">
            <Button variant="ghost" onClick={() => copy(item.value)}>
              Copy SQL
            </Button>
          </div>
          <pre className="overflow-x-auto whitespace-pre-wrap rounded-lg bg-slate-900 p-3 text-xs text-slate-100">
            {item.value}
          </pre>
        </Collapsible>
      ))}
    </div>
  );
};
