import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getPlugins } from "../lib/api";
import { useAppState } from "../state";
import type { PluginMeta } from "../types";
import { Card } from "../components/Card";
import { Badge } from "../components/Badge";
import { Button } from "../components/Button";
import { Skeleton } from "../components/Skeleton";
import { EmptyState } from "../components/EmptyState";

export const PluginCatalogPage: React.FC = () => {
  const [plugins, setPlugins] = useState<PluginMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { setActivePlugin } = useAppState();
  const navigate = useNavigate();

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await getPlugins();
        setPlugins(data);
      } catch (err: any) {
        setError(err?.message || "Failed to load plugins");
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  const handleSelect = (id: string) => {
    setActivePlugin(id);
    navigate(`/plugins/${id}`);
  };

  return (
    <div className="mx-auto max-w-7xl px-6 py-8 space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-sm font-semibold text-brand-blue">Plugin Catalog</p>
          <h1 className="text-3xl font-bold text-slate-900">Discover available plugins</h1>
          <p className="text-sm text-slate-600">
            See what each plugin can do before you upload data. Select one to view questions, schemas, and sample CSVs.
          </p>
        </div>
        <Button variant="secondary" onClick={() => navigate("/")}>
          Back to Dashboard
        </Button>
      </div>

      {loading && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Card key={i}>
              <div className="space-y-3">
                <Skeleton className="h-6 w-1/2" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-3/4" />
                <div className="flex gap-2">
                  <Skeleton className="h-6 w-16" />
                  <Skeleton className="h-6 w-20" />
                </div>
                <Skeleton className="h-9 w-full" />
              </div>
            </Card>
          ))}
        </div>
      )}

      {!loading && error && (
        <EmptyState title="Could not load plugins" description={error} actionLabel="Retry" onAction={() => window.location.reload()} />
      )}

      {!loading && !error && plugins.length === 0 && (
        <EmptyState title="No plugins available" description="Add plugin metadata to public/plugins to populate this catalog." />
      )}

      {!loading && !error && plugins.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {plugins.map((plugin) => (
            <Card
              key={plugin.id}
              title={plugin.name}
              actions={
                <Button size="sm" onClick={() => handleSelect(plugin.id)}>
                  Select plugin
                </Button>
              }
            >
              <p className="text-sm text-slate-700">{plugin.description}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {plugin.domains.map((d) => (
                  <Badge key={d} tone="neutral">
                    {d}
                  </Badge>
                ))}
              </div>
              <div className="mt-4 flex gap-2">
                <Button variant="secondary" onClick={() => navigate(`/plugins/${plugin.id}`)}>
                  View details
                </Button>
                <Button variant="ghost" onClick={() => handleSelect(plugin.id)}>
                  Activate
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
};
