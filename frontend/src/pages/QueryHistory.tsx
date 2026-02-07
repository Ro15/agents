import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAppState } from "../state";
import { Card } from "../components/Card";
import { Button } from "../components/Button";
import { Badge } from "../components/Badge";
import { EmptyState } from "../components/EmptyState";
import { useToast } from "../components/Toast";
import { getQueryHistory, toggleFavorite, createShareLink } from "../lib/api";
import type { QueryHistoryItem } from "../types";

export const QueryHistoryPage: React.FC = () => {
  const { activePlugin } = useAppState();
  const navigate = useNavigate();
  const { push } = useToast();
  const [items, setItems] = useState<QueryHistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [favOnly, setFavOnly] = useState(false);
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 20;

  const fetchHistory = async () => {
    setLoading(true);
    try {
      const res = await getQueryHistory({
        plugin_id: activePlugin,
        favorites_only: favOnly,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      });
      setItems(res.items);
      setTotal(res.total);
    } catch (err: any) {
      push(err?.message || "Failed to load history", "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchHistory();
  }, [activePlugin, favOnly, page]);

  const handleToggleFavorite = async (id: string) => {
    try {
      const res = await toggleFavorite(id);
      setItems((prev) => prev.map((i) => (i.id === id ? { ...i, is_favorite: res.is_favorite } : i)));
    } catch {
      push("Failed to toggle favorite", "error");
    }
  };

  const handleShare = async (id: string) => {
    try {
      const res = await createShareLink(id);
      const url = `${window.location.origin}/shared/${res.share_token}`;
      await navigator.clipboard.writeText(url);
      push("Share link copied to clipboard!", "success");
    } catch {
      push("Failed to create share link", "error");
    }
  };

  const handleRerun = (question: string) => {
    navigate("/chat", { state: { prefill: question } });
  };

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Query History</h1>
          <p className="text-sm text-slate-600">
            Browse, favorite, and share your past queries. {total} total queries.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-slate-600">
            <input
              type="checkbox"
              checked={favOnly}
              onChange={(e) => {
                setFavOnly(e.target.checked);
                setPage(0);
              }}
              className="h-4 w-4 rounded border-slate-300 text-brand-blue focus:ring-brand-blue"
            />
            Favorites only
          </label>
          <Button variant="secondary" size="sm" onClick={() => navigate("/chat")}>
            Back to Chat
          </Button>
        </div>
      </div>

      {loading && <p className="text-sm text-slate-500">Loading...</p>}

      {!loading && items.length === 0 && (
        <EmptyState
          title="No queries yet"
          description={favOnly ? "No favorite queries found." : "Start chatting to build your history."}
          actionLabel="Go to Chat"
          onAction={() => navigate("/chat")}
        />
      )}

      <div className="space-y-3">
        {items.map((item) => (
          <Card key={item.id}>
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-slate-900 truncate">{item.question}</p>
                {item.answer_summary && (
                  <p className="mt-1 text-xs text-slate-600 line-clamp-2">{item.answer_summary}</p>
                )}
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  {item.confidence && <Badge tone="info">{item.confidence}</Badge>}
                  {item.answer_type && <Badge tone="neutral">{item.answer_type}</Badge>}
                  <span className="text-xs text-slate-400">
                    {item.created_at ? new Date(item.created_at).toLocaleString() : ""}
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-1 flex-shrink-0">
                <button
                  className={`rounded p-1.5 transition ${
                    item.is_favorite
                      ? "text-amber-500 hover:bg-amber-50"
                      : "text-slate-400 hover:bg-slate-100 hover:text-amber-500"
                  }`}
                  title={item.is_favorite ? "Remove favorite" : "Add favorite"}
                  onClick={() => handleToggleFavorite(item.id)}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                    <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
                  </svg>
                </button>
                <button
                  className="rounded p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-brand-blue"
                  title="Share"
                  onClick={() => handleShare(item.id)}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                    <path d="M15 8a3 3 0 10-2.977-2.63l-4.94 2.47a3 3 0 100 4.319l4.94 2.47a3 3 0 10.895-1.789l-4.94-2.47a3.027 3.027 0 000-.74l4.94-2.47C13.456 7.68 14.19 8 15 8z" />
                  </svg>
                </button>
                <button
                  className="rounded p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-brand-blue"
                  title="Re-run in chat"
                  onClick={() => handleRerun(item.question)}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clipRule="evenodd" />
                  </svg>
                </button>
              </div>
            </div>
            {item.sql && (
              <details className="mt-2">
                <summary className="cursor-pointer text-xs text-slate-500 hover:text-brand-blue">View SQL</summary>
                <pre className="mt-1 overflow-x-auto rounded bg-slate-50 p-2 text-xs text-slate-700">{item.sql}</pre>
              </details>
            )}
          </Card>
        ))}
      </div>

      {/* Pagination */}
      {total > PAGE_SIZE && (
        <div className="mt-6 flex items-center justify-center gap-4">
          <Button variant="ghost" size="sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
            Previous
          </Button>
          <span className="text-sm text-slate-600">
            Page {page + 1} of {Math.ceil(total / PAGE_SIZE)}
          </span>
          <Button variant="ghost" size="sm" disabled={(page + 1) * PAGE_SIZE >= total} onClick={() => setPage((p) => p + 1)}>
            Next
          </Button>
        </div>
      )}
    </div>
  );
};
