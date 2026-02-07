import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getPluginQuestions, getPlugins } from "../lib/api";
import type { PluginMeta, QuestionPack } from "../types";
import { useAppState } from "../state";
import { Card } from "../components/Card";
import { Badge } from "../components/Badge";
import { Button } from "../components/Button";
import { Skeleton } from "../components/Skeleton";
import { EmptyState } from "../components/EmptyState";

export const PluginDetailPage: React.FC = () => {
  const { pluginId } = useParams();
  const navigate = useNavigate();
  const { setActivePlugin, activeDataset } = useAppState();
  const [plugin, setPlugin] = useState<PluginMeta | null>(null);
  const [packs, setPacks] = useState<QuestionPack[]>([]);
  const [loadingMeta, setLoadingMeta] = useState(true);
  const [loadingPacks, setLoadingPacks] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!pluginId) return;
    setActivePlugin(pluginId);
    const loadMeta = async () => {
      setLoadingMeta(true);
      setError(null);
      try {
        const all = await getPlugins();
        const match = all.find((p) => p.id === pluginId) || null;
        if (!match) setError("Plugin not found");
        setPlugin(match);
      } catch (err: any) {
        setError(err?.message || "Failed to load plugin metadata");
      } finally {
        setLoadingMeta(false);
      }
    };
    loadMeta();
  }, [pluginId, setActivePlugin]);

  useEffect(() => {
    if (!pluginId) return;
    const loadPacks = async () => {
      setLoadingPacks(true);
      try {
        const data = await getPluginQuestions(pluginId);
        setPacks(data);
      } catch {
        setPacks([]);
      } finally {
        setLoadingPacks(false);
      }
    };
    loadPacks();
  }, [pluginId]);

  const fallbackQuestions = useMemo<QuestionPack[]>(() => {
    if (!pluginId) return [];
    return [
      {
        id: "starter",
        title: "Starter questions",
        questions: [
          "What are the top 5 products by revenue this week?",
          "How did revenue change vs previous period?",
          "Which region shows the highest growth?",
          "What is the defect rate trend over the last 30 days?",
          "Which SKUs are low on inventory?",
          "Show on-time delivery rate by plant.",
          "Highlight anomalies in sales yesterday.",
          "Which stores need restocking this week?",
        ],
      },
    ];
  }, [pluginId]);

  const questionPacks = packs.length > 0 ? packs : fallbackQuestions;

  const handleTryQuestion = (q: string) => {
    navigate("/chat", { state: { prefill: q } });
  };

  if (!pluginId) {
    return (
      <div className="mx-auto max-w-7xl px-6 py-8">
        <EmptyState title="No plugin specified" description="Use the catalog to choose a plugin first." actionLabel="Back to catalog" onAction={() => navigate("/plugins")} />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl px-6 py-8 space-y-6">
      {loadingMeta && (
        <Card>
          <div className="space-y-3">
            <Skeleton className="h-7 w-1/3" />
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        </Card>
      )}

      {!loadingMeta && error && (
        <EmptyState title="Plugin unavailable" description={error} actionLabel="Back to catalog" onAction={() => navigate("/plugins")} />
      )}

      {!loadingMeta && plugin && (
        <>
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-sm font-semibold text-brand-blue">Plugin detail</p>
              <h1 className="text-3xl font-bold text-slate-900">{plugin.name}</h1>
              <p className="text-sm text-slate-700">{plugin.description}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {plugin.domains.map((d) => (
                  <Badge key={d} tone="neutral">
                    {d}
                  </Badge>
                ))}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => navigate("/")}>Upload data</Button>
              <Button variant="secondary" onClick={() => navigate("/chat")}>
                Go to Chat
              </Button>
              <Button variant="ghost" onClick={() => navigate("/insights")}>
                Go to Insights
              </Button>
            </div>
          </div>

          <Card title="Overview" className="border-slate-200">
            <div className="space-y-2 text-sm text-slate-700">
              <p>This plugin expects a clean CSV for the selected domain. Required fields are listed below.</p>
              <div className="flex flex-wrap gap-2">
                {(plugin.required_columns?.length ?? 0) > 0 ? (
                  plugin.required_columns!.map((col) => (
                    <Badge key={col} tone="neutral">
                      {col}
                    </Badge>
                  ))
                ) : (
                  <p className="text-xs text-slate-500">No required column metadata provided.</p>
                )}
              </div>
              {plugin.sample_csv_url && (
                <Button as="a" href={plugin.sample_csv_url} variant="secondary" className="mt-2" download>
                  Download sample CSV
                </Button>
              )}
            </div>
          </Card>

          <Card title="Question Packs">
            {loadingPacks && (
              <div className="grid gap-4 md:grid-cols-2">
                {Array.from({ length: 2 }).map((_, i) => (
                  <Card key={i} className="border-slate-100">
                    <div className="space-y-2">
                      <Skeleton className="h-5 w-1/2" />
                      {Array.from({ length: 4 }).map((__, j) => (
                        <Skeleton key={j} className="h-3 w-full" />
                      ))}
                    </div>
                  </Card>
                ))}
              </div>
            )}
            {!loadingPacks && (
              <div className="grid gap-4 md:grid-cols-2">
                {questionPacks.map((pack) => (
                  <Card key={pack.id} title={pack.title}>
                    <ol className="space-y-2 text-sm text-slate-800">
                      {pack.questions.map((q, idx) => (
                        <li key={idx} className="flex items-start justify-between gap-3">
                          <span className="flex-1">{q}</span>
                          <Button variant="ghost" size="sm" onClick={() => handleTryQuestion(q)}>
                            Try in Chat
                          </Button>
                        </li>
                      ))}
                    </ol>
                  </Card>
                ))}
              </div>
            )}
          </Card>

          <Card
            title="Data Requirements"
            actions={
              plugin.sample_csv_url ? (
                <Button variant="secondary" as="a" href={plugin.sample_csv_url} download>
                  Download sample CSV
                </Button>
              ) : null
            }
          >
            <div className="space-y-2 text-sm text-slate-700">
              <p>Ensure your CSV includes the following columns:</p>
              <ul className="grid gap-2 md:grid-cols-2">
                {(plugin.required_columns?.length ?? 0) > 0 ? (
                  plugin.required_columns!.map((col) => (
                    <li key={col} className="flex items-center gap-2 text-sm">
                      <span className="h-2 w-2 rounded-full bg-emerald-500" />
                      {col}
                    </li>
                  ))
                ) : (
                  <li className="text-xs text-slate-500">No required columns listed.</li>
                )}
              </ul>
            </div>
          </Card>

          <div className="flex flex-wrap gap-3">
            <Button onClick={() => navigate("/")}>Upload data</Button>
            <Button variant="secondary" onClick={() => navigate("/chat")}>
              Go to Chat
            </Button>
            <Button variant="ghost" onClick={() => navigate("/insights")}>
              Go to Insights
            </Button>
            {activeDataset && (
              <Badge tone="success" className="self-center">
                Active dataset: {activeDataset.dataset_id}
              </Badge>
            )}
          </div>
        </>
      )}
    </div>
  );
};
