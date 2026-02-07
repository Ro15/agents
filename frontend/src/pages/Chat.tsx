import React, { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAppState } from "../state";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { DataTable } from "../components/DataTable";
import { TrustPanel } from "../components/TrustPanel";
import { EmptyState } from "../components/EmptyState";
import { UploadModal } from "../components/UploadModal";
import { chat, getPluginQuestions, uploadSalesCSV } from "../lib/api";
import type { ChatResponse } from "../types";
import { useToast } from "../components/Toast";
import { useLocalChats } from "../hooks/useLocalChats";
import { Skeleton } from "../components/Skeleton";

export const ChatPage: React.FC = () => {
  const { activePlugin, activeDataset, setActiveDataset, upsertDatasetForPlugin } = useAppState();
  const navigate = useNavigate();
  const location = useLocation();
  const { push } = useToast();
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  const { messages, setMessages } = useLocalChats(activePlugin, activeDataset?.dataset_id || null);
  const [uploading, setUploading] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [autoSend, setAutoSend] = useState(false);
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);
  const [showSuggestionsPanel, setShowSuggestionsPanel] = useState(true);

  const canChat = !!activeDataset;

  const fallbackSuggestions = useMemo(
    () => [
      "Show revenue by category this week",
      "Top 5 items by revenue last 7 days",
      "Show defect rate by line for the last week",
      "Total sales today",
      "Which region is performing best?",
      "Highlight anomalies for the last 7 days",
      "What changed most vs previous period?",
      "Show inventory risk for next 7 days",
      "Which entity has highest growth?",
      "Summarize key drivers this week",
    ],
    []
  );

  useEffect(() => {
    const prefill = (location.state as any)?.prefill;
    if (prefill) setInput(prefill);
  }, [location.state]);

  useEffect(() => {
    const loadSuggestions = async () => {
      setLoadingSuggestions(true);
      try {
        const packs = await getPluginQuestions(activePlugin);
        const qs = packs.flatMap((p) => p.questions).slice(0, 20);
        setSuggestions(qs.length > 0 ? qs : fallbackSuggestions);
      } catch {
        setSuggestions(fallbackSuggestions);
      } finally {
        setLoadingSuggestions(false);
      }
    };
    loadSuggestions();
  }, [activePlugin, fallbackSuggestions]);

  const sendMessage = async (override?: string) => {
    const text = (override ?? input).trim();
    if (!text || !canChat) return;
    const userMsg = { role: "user" as const, content: text, createdAt: new Date().toISOString() };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);
    try {
      const resp = await chat(activePlugin, activeDataset?.dataset_id || null, userMsg.content);
      const assistantMsg = { role: "assistant" as const, content: resp, createdAt: new Date().toISOString() };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err: any) {
      push(err?.message || "Chat failed", "error");
    } finally {
      setLoading(false);
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const meta = await uploadSalesCSV(activePlugin, file);
      upsertDatasetForPlugin(activePlugin, meta);
      setMessages([]); // reset history for new dataset
      push("Upload complete", "success");
      setShowUpload(false);
      setInput("");
      if (meta) setActiveDataset(meta);
    } catch (err: any) {
      push(err?.message || "Upload failed", "error");
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  };

  const renderAnswer = (resp: ChatResponse) => {
    if (resp.answer_type === "number") {
      return <div className="text-4xl font-bold text-slate-900">{resp.answer}</div>;
    }
    if (resp.answer_type === "table" && Array.isArray(resp.answer)) {
      return <DataTable rows={resp.answer} />;
    }
    return <p className="text-sm text-slate-800 whitespace-pre-wrap">{resp.answer}</p>;
  };

  return (
    <div className="mx-auto max-w-7xl px-6 py-8">
      <div className="mb-2 flex items-center justify-end lg:hidden">
        <Button variant="ghost" size="sm" onClick={() => setShowSuggestionsPanel((v) => !v)}>
          {showSuggestionsPanel ? "Hide suggestions" : "Show suggestions"}
        </Button>
      </div>

      <div className="grid gap-6 lg:grid-cols-[220px,1fr,280px]">
        <div className="space-y-3">
          <Card title="Context">
            <p className="text-sm text-slate-600">Plugin: {activePlugin}</p>
            <p className="text-sm text-slate-600">Dataset: {activeDataset?.dataset_id ?? "none"}</p>
            {activeDataset?.ingested_at && (
              <p className="text-xs text-slate-500">Ingested: {activeDataset.ingested_at}</p>
            )}
            {activeDataset?.row_count !== undefined && (
              <p className="text-xs text-slate-500">Rows: {activeDataset.row_count}</p>
            )}
          </Card>
          <div className="flex flex-col gap-2">
            <Button variant="secondary" onClick={() => navigate("/")}>
              Change Plugin/Dataset
            </Button>
            <Button onClick={() => setShowUpload(true)}>Upload New Dataset</Button>
          </div>
        </div>

        <div className="space-y-4">
          <header>
            <h1 className="text-2xl font-bold text-slate-900">Chat with your data</h1>
            <p className="text-sm text-slate-600">SQL trace, freshness, and confidence are shown for every answer.</p>
          </header>

          {!canChat && (
            <EmptyState
              title="No dataset selected"
              description="Upload or select a dataset for this plugin to start chatting."
              actionLabel="Go to Dashboard"
              onAction={() => navigate("/")}
            />
          )}

          {canChat && (
            <>
              <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4">
                <div className="flex gap-2">
                  <input
                    className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-blue focus:outline-none focus:ring-2 focus:ring-brand-blue/20"
                    placeholder="Ask a question..."
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        sendMessage();
                      }
                    }}
                  />
                  <Button onClick={() => sendMessage()} disabled={loading}>
                    {loading ? "Thinking..." : "Send"}
                  </Button>
                </div>
                <div className="text-xs text-slate-500">Enter to send. Your queries are constrained to plugin schema.</div>
              </div>

              <div className="space-y-4">
                {messages.map((m, idx) => (
                  <div key={idx} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                    <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                      {m.role === "user" ? "You" : "Assistant"}
                    </div>
                    {m.role === "user" ? (
                      <p className="text-sm text-slate-800 whitespace-pre-wrap">{m.content}</p>
                    ) : (
                      <>
                        {renderAnswer(m.content as ChatResponse)}
                        <TrustPanel
                          confidence={(m.content as ChatResponse).confidence}
                          dataLastUpdated={(m.content as ChatResponse).data_last_updated}
                          sql={(m.content as ChatResponse).sql}
                        />
                        {m.content.answer_type === "text" && (
                          <p className="mt-2 text-xs text-slate-500">{(m.content as ChatResponse).explanation}</p>
                        )}
                      </>
                    )}
                  </div>
                ))}
                {messages.length === 0 && (
                  <Card title="Suggested questions">
                    <ul className="list-disc space-y-1 pl-4 text-sm text-slate-700">
                      {suggestions.map((s) => (
                        <li key={s}>
                          <button className="text-brand-blue hover:underline" onClick={() => sendMessage(s)}>
                            {s}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </Card>
                )}
              </div>
            </>
          )}
        </div>

        {showSuggestionsPanel && (
          <aside className="space-y-3">
            <Card title="Suggested Questions">
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-500">Tap to fill. Auto-send?</span>
                <label className="flex items-center gap-2 text-xs text-slate-600">
                  <input
                    type="checkbox"
                    checked={autoSend}
                    onChange={(e) => setAutoSend(e.target.checked)}
                    className="h-4 w-4 rounded border-slate-300 text-brand-blue focus:ring-brand-blue"
                  />
                  Auto-send
                </label>
              </div>
              {loadingSuggestions ? (
                <div className="space-y-2">
                  {Array.from({ length: 6 }).map((_, i) => (
                    <Skeleton key={i} className="h-4 w-full" />
                  ))}
                </div>
              ) : (
                <ul className="space-y-2 text-sm text-slate-800">
                  {suggestions.slice(0, 12).map((q) => (
                    <li key={q} className="flex items-start gap-2">
                      <button
                        className="flex-1 text-left text-brand-blue hover:underline"
                        onClick={() => {
                          if (autoSend) sendMessage(q);
                          else setInput(q);
                        }}
                      >
                        {q}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card>
              <p className="text-xs text-slate-600">
                Suggestions come from plugin question packs when available. Otherwise we fall back to generic top questions.
              </p>
            </Card>
          </aside>
        )}
      </div>

      <UploadModal open={showUpload} onClose={() => setShowUpload(false)} onUpload={handleUpload} uploading={uploading} />
    </div>
  );
};
