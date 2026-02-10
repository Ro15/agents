import React, { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAppState } from "../state";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { DataTable } from "../components/DataTable";
import { SmartChart } from "../components/SmartChart";
import { TrustPanel } from "../components/TrustPanel";
import { EmptyState } from "../components/EmptyState";
import { UploadModal } from "../components/UploadModal";
import { chat, getPluginQuestions, createConversation, submitFeedback } from "../lib/api";
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
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [autoSend, setAutoSend] = useState(false);
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);
  const [showSuggestionsPanel, setShowSuggestionsPanel] = useState(true);

  // Multi-turn conversation state
  const [conversationId, setConversationId] = useState<string | null>(null);

  // Feedback state: tracks which messages have been rated
  const [feedbackGiven, setFeedbackGiven] = useState<Record<number, 1 | -1>>({});

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

  // Build conversation history for multi-turn context
  const buildConversationHistory = () => {
    return messages.slice(-10).map((m) => ({
      role: m.role,
      content:
        m.role === "user"
          ? (m.content as string)
          : (m.content as ChatResponse).summary ||
            (m.content as ChatResponse).narrative ||
            String((m.content as ChatResponse).answer).slice(0, 300),
    }));
  };

  const sendMessage = async (override?: string) => {
    const text = (override ?? input).trim();
    if (!text || !canChat) return;
    const userMsg = { role: "user" as const, content: text, createdAt: new Date().toISOString() };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);
    try {
      // Auto-create a conversation thread if none exists
      let threadId = conversationId;
      if (!threadId) {
        try {
          const thread = await createConversation(activePlugin, activeDataset?.dataset_id, text.slice(0, 60));
          threadId = thread.thread_id;
          setConversationId(threadId);
        } catch {
          // Non-critical; continue without thread
        }
      }

      const history = buildConversationHistory();
      const resp = await chat(activePlugin, activeDataset?.dataset_id || null, userMsg.content, threadId, history);

      // Update conversation_id if returned
      if (resp.conversation_id && !conversationId) {
        setConversationId(resp.conversation_id);
      }

      const assistantMsg = { role: "assistant" as const, content: resp, createdAt: new Date().toISOString() };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err: any) {
      push(err?.message || "Chat failed", "error");
    } finally {
      setLoading(false);
    }
  };

  const handleUploadSuccess = (meta: import("../types").DatasetMeta) => {
    upsertDatasetForPlugin(activePlugin, meta);
    setActiveDataset(meta);
    setMessages([]); // reset chat history for the new dataset
    setConversationId(null); // reset conversation thread
    setFeedbackGiven({});
    setInput("");
    setShowUpload(false);
  };

  const handleNewConversation = () => {
    setMessages([]);
    setConversationId(null);
    setFeedbackGiven({});
    setInput("");
  };

  // Feedback handler
  const handleFeedback = async (msgIdx: number, rating: 1 | -1, resp: ChatResponse) => {
    try {
      await submitFeedback({
        plugin_id: activePlugin,
        question: msgIdx > 0 && messages[msgIdx - 1]?.role === "user" ? (messages[msgIdx - 1].content as string) : "",
        original_sql: resp.sql,
        rating,
        query_history_id: resp.history_id,
      });
      setFeedbackGiven((prev) => ({ ...prev, [msgIdx]: rating }));
      push(rating === 1 ? "Thanks for the feedback!" : "Feedback recorded. We'll improve.", "success");
    } catch {
      push("Failed to submit feedback", "error");
    }
  };

  const [chartView, setChartView] = useState<Record<number, "chart" | "table">>({});

  const renderAnswer = (resp: ChatResponse, msgIdx: number) => {
    // Number answer -- big stat with context
    if (resp.answer_type === "number") {
      const formatted =
        typeof resp.answer === "number"
          ? resp.answer.toLocaleString(undefined, { maximumFractionDigits: 2 })
          : resp.answer;
      return (
        <div className="flex flex-col items-start gap-1">
          <div className="text-4xl font-bold text-brand-blue">{formatted}</div>
          {resp.narrative && <p className="text-sm text-slate-700 italic">{resp.narrative}</p>}
          {!resp.narrative && resp.summary && <p className="text-sm text-slate-600">{resp.summary}</p>}
          {resp.assumptions && resp.assumptions.length > 0 && (
            <p className="text-xs text-slate-500 italic">{resp.assumptions.join(". ")}</p>
          )}
        </div>
      );
    }

    // Table answer -- chart + table toggle
    if (resp.answer_type === "table" && Array.isArray(resp.answer) && resp.answer.length > 0) {
      const view = chartView[msgIdx] || "chart";
      const showChart = view === "chart" && resp.answer.length >= 2 && resp.answer.length <= 500;
      return (
        <div className="space-y-3">
          {resp.narrative && <p className="text-sm text-slate-700 italic">{resp.narrative}</p>}
          {!resp.narrative && resp.summary && <p className="text-sm text-slate-700">{resp.summary}</p>}
          <div className="flex items-center gap-2">
            <button
              className={`rounded-md px-3 py-1 text-xs font-medium transition ${
                view === "chart"
                  ? "bg-brand-blue text-white"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              }`}
              onClick={() => setChartView((p) => ({ ...p, [msgIdx]: "chart" }))}
            >
              Chart
            </button>
            <button
              className={`rounded-md px-3 py-1 text-xs font-medium transition ${
                view === "table"
                  ? "bg-brand-blue text-white"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              }`}
              onClick={() => setChartView((p) => ({ ...p, [msgIdx]: "table" }))}
            >
              Table
            </button>
            <span className="text-xs text-slate-500">{resp.answer.length} rows</span>
          </div>
          {showChart && <SmartChart rows={resp.answer} hint={resp.chart_hint} />}
          {view === "table" && <DataTable rows={resp.answer} />}
        </div>
      );
    }

    // Text / fallback
    return (
      <div>
        <p className="text-sm text-slate-800 whitespace-pre-wrap">{resp.answer}</p>
        {resp.narrative && resp.narrative !== String(resp.answer) && (
          <p className="mt-1 text-sm text-slate-700 italic">{resp.narrative}</p>
        )}
        {!resp.narrative && resp.summary && resp.summary !== String(resp.answer) && (
          <p className="mt-1 text-xs text-slate-500">{resp.summary}</p>
        )}
      </div>
    );
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
            {conversationId && (
              <p className="text-xs text-slate-500 mt-1 truncate" title={conversationId}>
                Thread: {conversationId.slice(0, 8)}...
              </p>
            )}
          </Card>
          <div className="flex flex-col gap-2">
            <Button variant="secondary" onClick={() => navigate("/")}>
              Change Plugin/Dataset
            </Button>
            <Button onClick={() => setShowUpload(true)}>Upload New Dataset</Button>
            <Button variant="ghost" onClick={handleNewConversation}>
              New Conversation
            </Button>
          </div>

        </div>

        <div className="space-y-4">
          <header>
            <h1 className="text-2xl font-bold text-slate-900">Chat with your data</h1>
            <p className="text-sm text-slate-600">
              Multi-turn conversations with SQL trace, freshness, confidence, and AI narratives.
            </p>
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
                    placeholder="Ask a question (follow-ups work!)..."
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
                <div className="text-xs text-slate-500">
                  Enter to send. Follow-up questions use conversation context. Your queries are constrained to plugin schema.
                </div>
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
                        {renderAnswer(m.content as ChatResponse, idx)}
                        <TrustPanel
                          confidence={(m.content as ChatResponse).confidence}
                          dataLastUpdated={(m.content as ChatResponse).data_last_updated}
                          sql={(m.content as ChatResponse).sql}
                        />
                        {(m.content as ChatResponse).answer_type === "text" && (
                          <p className="mt-2 text-xs text-slate-500">{(m.content as ChatResponse).explanation}</p>
                        )}

                        {/* Feedback buttons */}
                        <div className="mt-3 flex items-center gap-2 border-t border-slate-100 pt-2">
                          {feedbackGiven[idx] ? (
                            <span className="text-xs text-slate-500">
                              {feedbackGiven[idx] === 1 ? "Rated helpful" : "Rated not helpful"}
                            </span>
                          ) : (
                            <>
                              <button
                                className="flex items-center gap-1 rounded px-2 py-1 text-xs text-slate-500 hover:bg-green-50 hover:text-green-700 transition"
                                onClick={() => handleFeedback(idx, 1, m.content as ChatResponse)}
                                title="This answer was helpful"
                              >
                                <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                                  <path d="M2 10.5a1.5 1.5 0 113 0v6a1.5 1.5 0 01-3 0v-6zM6 10.333v5.43a2 2 0 001.106 1.79l.05.025A4 4 0 008.943 18h5.416a2 2 0 001.962-1.608l1.2-6A2 2 0 0015.56 8H12V4a2 2 0 00-2-2 1 1 0 00-1 1v.667a4 4 0 01-.8 2.4L6.8 7.933a4 4 0 00-.8 2.4z" />
                                </svg>
                                Helpful
                              </button>
                              <button
                                className="flex items-center gap-1 rounded px-2 py-1 text-xs text-slate-500 hover:bg-red-50 hover:text-red-700 transition"
                                onClick={() => handleFeedback(idx, -1, m.content as ChatResponse)}
                                title="This answer was not helpful"
                              >
                                <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 rotate-180" viewBox="0 0 20 20" fill="currentColor">
                                  <path d="M2 10.5a1.5 1.5 0 113 0v6a1.5 1.5 0 01-3 0v-6zM6 10.333v5.43a2 2 0 001.106 1.79l.05.025A4 4 0 008.943 18h5.416a2 2 0 001.962-1.608l1.2-6A2 2 0 0015.56 8H12V4a2 2 0 00-2-2 1 1 0 00-1 1v.667a4 4 0 01-.8 2.4L6.8 7.933a4 4 0 00-.8 2.4z" />
                                </svg>
                                Not helpful
                              </button>
                            </>
                          )}
                        </div>
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

      <UploadModal open={showUpload} onClose={() => setShowUpload(false)} onSuccess={handleUploadSuccess} />
    </div>
  );
};
