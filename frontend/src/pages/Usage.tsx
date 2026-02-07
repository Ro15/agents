import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAppState } from "../state";
import { Card } from "../components/Card";
import { Button } from "../components/Button";
import { KPICard } from "../components/KPICard";
import { Skeleton } from "../components/Skeleton";
import { useApiData } from "../hooks/useApiData";
import { getUsageCosts, getRateLimitStatus } from "../lib/api";

export const UsagePage: React.FC = () => {
  const { activePlugin } = useAppState();
  const navigate = useNavigate();
  const [days, setDays] = useState(30);

  const { data: costs, loading: loadingCosts } = useApiData(
    () => getUsageCosts(activePlugin, days),
    [activePlugin, days],
  );

  const { data: rateLimit, loading: loadingRL } = useApiData(
    () => getRateLimitStatus(),
    [],
  );

  const loading = loadingCosts || loadingRL;

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Usage & Costs</h1>
          <p className="text-sm text-slate-600">LLM cost tracking and rate limit status.</p>
        </div>
        <div className="flex items-center gap-3">
          <select
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
          >
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
            <option value={365}>Last year</option>
          </select>
          <Button variant="secondary" size="sm" onClick={() => navigate("/chat")}>Back to Chat</Button>
        </div>
      </div>

      {loading && (
        <div className="space-y-4">
          <Skeleton className="h-24 w-full rounded-xl" />
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-20 w-full rounded-xl" />
            ))}
          </div>
        </div>
      )}

      {/* Rate Limit Status */}
      {!loading && rateLimit && (
        <Card className="mb-6">
          <h3 className="text-sm font-semibold text-slate-900 mb-3">Rate Limit Status</h3>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div>
              <p className="text-xs text-slate-500">Your IP</p>
              <p className="text-sm font-medium text-slate-900 font-mono">{rateLimit.client_ip}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Requests (window)</p>
              <p className="text-sm font-medium text-slate-900">{rateLimit.requests_in_window} / {rateLimit.max_requests}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Remaining</p>
              <p className="text-sm font-medium text-slate-900">{rateLimit.remaining}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Window</p>
              <p className="text-sm font-medium text-slate-900">{rateLimit.window_seconds}s</p>
            </div>
          </div>
        </Card>
      )}

      {/* Cost Summary */}
      {!loading && costs && (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <KPICard title="Total LLM Calls" value={costs.total_calls.toLocaleString()} />
            <KPICard title="Input Tokens" value={costs.total_input_tokens.toLocaleString()} />
            <KPICard title="Output Tokens" value={costs.total_output_tokens.toLocaleString()} />
            <KPICard title="Est. Cost (USD)" value={`$${costs.total_estimated_cost_usd.toFixed(4)}`} />
          </div>

          <Card>
            <h3 className="text-sm font-semibold text-slate-900 mb-3">Cost by Model ({days} days)</h3>
            {Object.keys(costs.by_model).length === 0 ? (
              <p className="text-xs text-slate-500">No LLM usage data yet.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-slate-50 text-xs uppercase text-slate-600">
                    <tr>
                      <th className="px-4 py-2">Model</th>
                      <th className="px-4 py-2">Calls</th>
                      <th className="px-4 py-2">Input Tokens</th>
                      <th className="px-4 py-2">Output Tokens</th>
                      <th className="px-4 py-2">Est. Cost</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {Object.entries(costs.by_model).map(([model, data]) => (
                      <tr key={model} className="hover:bg-slate-50">
                        <td className="px-4 py-2 font-mono text-slate-900">{model}</td>
                        <td className="px-4 py-2 text-slate-600">{data.calls}</td>
                        <td className="px-4 py-2 text-slate-600">{data.input_tokens.toLocaleString()}</td>
                        <td className="px-4 py-2 text-slate-600">{data.output_tokens.toLocaleString()}</td>
                        <td className="px-4 py-2 text-slate-900">${data.cost.toFixed(4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
};
