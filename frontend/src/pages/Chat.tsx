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
import {
  chat,
  getPluginQuestions,
  createConversation,
  submitFeedback,
  listConversations,
  getConversation,
  getConversationMemory,
  updateConversation,
  deleteConversation,
} from "../lib/api";
import type { ChatResponse, ConversationMemoryItem, ConversationThread } from "../types";
import { useToast } from "../components/Toast";
import { Skeleton } from "../components/Skeleton";

type ChatMessage =
  | { role: "user"; content: string; createdAt: string }
  | { role: "assistant"; content: ChatResponse; createdAt: string };

export const ChatPage: React.FC = () => {
  const { activePlugin, activeDataset, setActiveDataset, upsertDatasetForPlugin } = useAppState();
  const navigate = useNavigate();
  const location = useLocation();
  const { push } = useToast();

  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [threads, setThreads] = useState<ConversationThread[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [loadingThreads, setLoadingThreads] = useState(false);
  const [loadingThreadMessages, setLoadingThreadMessages] = useState(false);
  const [threadFilter, setThreadFilter] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [loadingMemory, setLoadingMemory] = useState(false);
  const [threadMemory, setThreadMemory] = useState<ConversationMemoryItem[]>([]);

  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [autoSend, setAutoSend] = useState(false);
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);
  const [showSuggestionsPanel, setShowSuggestionsPanel] = useState(true);
  const [feedbackGiven, setFeedbackGiven] = useState<Record<number, 1 | -1>>({});
  const [chartView, setChartView] = useState<Record<number, "chart" | "table">>({});

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

  const filteredThreads = useMemo(() => {
    const q = threadFilter.trim().toLowerCase();
    if (!q) return threads;
    return threads.filter(
      (t) =>
        (t.title || "").toLowerCase().includes(q) ||
        (t.last_message_preview || "").toLowerCase().includes(q)
    );
  }, [threadFilter, threads]);

  const buildConversationHistory = () => {
    return messages.slice(-10).map((m) => ({
      role: m.role,
      content:
        m.role === "user"
          ? m.content
          : (m.content as ChatResponse).summary ||
            (m.content as ChatResponse).narrative ||
            String((m.content as ChatResponse).answer).slice(0, 300),
    }));
  };

  const normalizeAssistantPayload = (raw: any): ChatResponse => {
    if (raw && typeof raw === "object" && raw.answer_type) {
      return raw as ChatResponse;
    }
    return {
      answer_type: "text",
      answer: typeof raw === "string" ? raw : JSON.stringify(raw ?? ""),
      explanation: "Loaded from conversation history.",
      sql: null,
      confidence: "medium",
      plugin: activePlugin,
      summary: typeof raw === "string" ? raw : "",
    };
  };

  const loadThreadMessages = async (threadId: string) => {
    setLoadingThreadMessages(true);
    setLoadingMemory(true);
    try {
      const [thread, memory] = await Promise.all([
        getConversation(threadId),
        getConversationMemory(threadId),
      ]);
      const mapped: ChatMessage[] = (thread.messages || []).map((m: any) => {
        if (m.role === "user") {
          return {
            role: "user",
            content: m.content || "",
            createdAt: m.created_at || new Date().toISOString(),
          };
        }
        return {
          role: "assistant",
          content: normalizeAssistantPayload(m.payload || m.content),
          createdAt: m.created_at || new Date().toISOString(),
        };
      });
      setMessages(mapped);
      setConversationId(threadId);
      setFeedbackGiven({});
      setChartView({});
      setThreadMemory(memory || []);
    } catch (err: any) {
      push(err?.message || "Failed to load conversation", "error");
      setThreadMemory([]);
    } finally {
      setLoadingThreadMessages(false);
      setLoadingMemory(false);
    }
  };

  const refreshThreads = async (
    preferredThreadId?: string | null,
    opts?: { loadMessages?: boolean }
  ) => {
    if (!activeDataset?.dataset_id) {
      setThreads([]);
      return;
    }
    const shouldLoadMessages = opts?.loadMessages !== false;
    setLoadingThreads(true);
    try {
      const list = await listConversations(activePlugin, activeDataset.dataset_id, {
        include_archived: showArchived,
      });
      setThreads(list);
      const preferred = preferredThreadId || conversationId;
      if (shouldLoadMessages && preferred && list.find((t) => t.thread_id === preferred)) {
        if (preferred !== conversationId || messages.length === 0) {
          await loadThreadMessages(preferred);
        }
      } else if (shouldLoadMessages && list.length > 0) {
        await loadThreadMessages(list[0].thread_id);
      } else if (shouldLoadMessages) {
        setConversationId(null);
        setMessages([]);
        setThreadMemory([]);
      }
    } catch (err: any) {
      push(err?.message || "Failed to load chat sessions", "error");
    } finally {
      setLoadingThreads(false);
    }
  };

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

  useEffect(() => {
    setMessages([]);
    setConversationId(null);
    setFeedbackGiven({});
    setThreadMemory([]);
    if (!activeDataset?.dataset_id) {
      setThreads([]);
      return;
    }
    refreshThreads(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activePlugin, activeDataset?.dataset_id, showArchived]);

  const handleNewConversation = async () => {
    if (!activeDataset?.dataset_id) return;
    try {
      const thread = await createConversation(activePlugin, activeDataset.dataset_id, "New conversation");
      setThreads((prev) => [thread, ...prev.filter((t) => t.thread_id !== thread.thread_id)]);
      setConversationId(thread.thread_id);
      setMessages([]);
      setFeedbackGiven({});
      setChartView({});
      setThreadMemory([]);
      setInput("");
    } catch (err: any) {
      push(err?.message || "Failed to create conversation", "error");
    }
  };

  const handleRenameConversation = async (thread: ConversationThread) => {
    const nextTitle = window.prompt("Rename chat", thread.title || "New conversation");
    if (nextTitle === null) return;
    try {
      const updated = await updateConversation(thread.thread_id, { title: nextTitle });
      setThreads((prev) => prev.map((t) => (t.thread_id === updated.thread_id ? updated : t)));
    } catch (err: any) {
      push(err?.message || "Rename failed", "error");
    }
  };

  const handleTogglePinConversation = async (thread: ConversationThread) => {
    try {
      const updated = await updateConversation(thread.thread_id, { is_pinned: !thread.is_pinned });
      setThreads((prev) =>
        prev
          .map((t) => (t.thread_id === updated.thread_id ? updated : t))
          .sort((a, b) => {
            const pinDiff = Number(!!b.is_pinned) - Number(!!a.is_pinned);
            if (pinDiff !== 0) return pinDiff;
            return new Date(b.updated_at || 0).getTime() - new Date(a.updated_at || 0).getTime();
          })
      );
    } catch (err: any) {
      push(err?.message || "Pin update failed", "error");
    }
  };

  const handleToggleArchiveConversation = async (thread: ConversationThread) => {
    try {
      await updateConversation(thread.thread_id, { archived: !thread.archived });
      await refreshThreads(conversationId);
    } catch (err: any) {
      push(err?.message || "Archive update failed", "error");
    }
  };

  const handleDeleteConversation = async (thread: ConversationThread) => {
    const ok = window.confirm(`Delete "${thread.title || "conversation"}"?`);
    if (!ok) return;
    try {
      await deleteConversation(thread.thread_id);
      const next = threads.filter((t) => t.thread_id !== thread.thread_id);
      setThreads(next);
      if (conversationId === thread.thread_id) {
        if (next.length > 0) {
          await loadThreadMessages(next[0].thread_id);
        } else {
          setConversationId(null);
          setMessages([]);
          setThreadMemory([]);
        }
      }
    } catch (err: any) {
      push(err?.message || "Delete failed", "error");
    }
  };

  const sendMessage = async (override?: string) => {
    const text = (override ?? input).trim();
    if (!text || !canChat) return;

    let threadId = conversationId;
    if (!threadId) {
      try {
        const thread = await createConversation(activePlugin, activeDataset?.dataset_id, text.slice(0, 60));
        threadId = thread.thread_id;
        setConversationId(threadId);
        setThreads((prev) => [thread, ...prev.filter((t) => t.thread_id !== thread.thread_id)]);
      } catch (err: any) {
        push(err?.message || "Failed to create conversation", "error");
        return;
      }
    }

    const userMsg: ChatMessage = { role: "user", content: text, createdAt: new Date().toISOString() };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);
    try {
      const history = buildConversationHistory();
      const resp = await chat(activePlugin, activeDataset?.dataset_id || null, text, threadId, history);
      const assistantMsg: ChatMessage = {
        role: "assistant",
        content: resp,
        createdAt: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, assistantMsg]);

      if (resp.conversation_id) {
        setConversationId(resp.conversation_id);
      }
      const targetThreadId = resp.conversation_id || threadId;
      await refreshThreads(targetThreadId, { loadMessages: false });
      if (targetThreadId) {
        await loadThreadMessages(targetThreadId);
      }
    } catch (err: any) {
      push(err?.message || "Chat failed", "error");
    } finally {
      setLoading(false);
    }
  };

  const handleUploadSuccess = (meta: import("../types").DatasetMeta) => {
    upsertDatasetForPlugin(activePlugin, meta);
    setActiveDataset(meta);
    setMessages([]);
    setConversationId(null);
    setFeedbackGiven({});
    setInput("");
    setShowUpload(false);
  };

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

  const renderAnswer = (resp: ChatResponse, msgIdx: number) => {
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
                view === "chart" ? "bg-brand-blue text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              }`}
              onClick={() => setChartView((p) => ({ ...p, [msgIdx]: "chart" }))}
            >
              Chart
            </button>
            <button
              className={`rounded-md px-3 py-1 text-xs font-medium transition ${
                view === "table" ? "bg-brand-blue text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
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

    if (Array.isArray(resp.answer)) {
      const objectRows = resp.answer.filter((r) => r && typeof r === "object");
      if (objectRows.length === resp.answer.length && objectRows.length > 0) {
        return (
          <div className="space-y-2">
            {resp.narrative && <p className="text-sm text-slate-700 italic">{resp.narrative}</p>}
            {!resp.narrative && resp.summary && <p className="text-sm text-slate-700">{resp.summary}</p>}
            <DataTable rows={objectRows as Record<string, unknown>[]} />
          </div>
        );
      }
    }

    if (resp.answer && typeof resp.answer === "object") {
      return (
        <div>
          <pre className="max-h-80 overflow-auto rounded-md bg-slate-50 p-3 text-xs text-slate-700">
            {JSON.stringify(resp.answer, null, 2)}
          </pre>
          {resp.narrative && <p className="mt-1 text-sm text-slate-700 italic">{resp.narrative}</p>}
          {!resp.narrative && resp.summary && <p className="mt-1 text-xs text-slate-500">{resp.summary}</p>}
        </div>
      );
    }

    return (
      <div>
        <p className="text-sm text-slate-800 whitespace-pre-wrap">{String(resp.answer ?? "")}</p>
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

      <div className="grid gap-6 lg:grid-cols-[280px,1fr,280px]">
        <div className="space-y-3">
          <Card
            title="Chat Sessions"
            actions={
              <Button size="sm" onClick={handleNewConversation} disabled={!canChat}>
                New
              </Button>
            }
          >
            <div className="space-y-2">
              <input
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-blue focus:outline-none focus:ring-2 focus:ring-brand-blue/20"
                placeholder="Search chats..."
                value={threadFilter}
                onChange={(e) => setThreadFilter(e.target.value)}
              />
              <label className="flex items-center gap-2 text-xs text-slate-600">
                <input
                  type="checkbox"
                  checked={showArchived}
                  onChange={(e) => setShowArchived(e.target.checked)}
                  className="h-4 w-4 rounded border-slate-300 text-brand-blue focus:ring-brand-blue"
                />
                Show archived
              </label>
              {loadingThreads ? (
                <div className="space-y-2">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Skeleton key={i} className="h-10 w-full" />
                  ))}
                </div>
              ) : filteredThreads.length === 0 ? (
                <p className="text-xs text-slate-500">
                  {canChat ? "No chat sessions yet. Start a new one." : "Select a dataset to enable chat sessions."}
                </p>
              ) : (
                <ul className="space-y-1">
                  {filteredThreads.map((t) => (
                    <li key={t.thread_id}>
                      <button
                        className={`w-full rounded-md border px-3 py-2 text-left transition ${
                          conversationId === t.thread_id
                            ? "border-brand-blue bg-brand-blue/5"
                            : "border-slate-200 hover:border-slate-300"
                        }`}
                        onClick={() => loadThreadMessages(t.thread_id)}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate text-sm font-semibold text-slate-800">{t.title || "New conversation"}</span>
                          <div className="flex items-center gap-1">
                            <button
                              className="rounded px-1.5 py-0.5 text-[11px] text-slate-500 hover:bg-slate-100"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleTogglePinConversation(t);
                              }}
                              title={t.is_pinned ? "Unpin" : "Pin"}
                            >
                              {t.is_pinned ? "Unpin" : "Pin"}
                            </button>
                            <button
                              className="rounded px-1.5 py-0.5 text-[11px] text-slate-500 hover:bg-slate-100"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleToggleArchiveConversation(t);
                              }}
                              title={t.archived ? "Unarchive" : "Archive"}
                            >
                              {t.archived ? "Unarchive" : "Archive"}
                            </button>
                            <button
                              className="rounded px-1.5 py-0.5 text-[11px] text-slate-500 hover:bg-slate-100"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleRenameConversation(t);
                              }}
                              title="Rename"
                            >
                              Rename
                            </button>
                            <button
                              className="rounded px-1.5 py-0.5 text-[11px] text-red-500 hover:bg-red-50"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleDeleteConversation(t);
                              }}
                              title="Delete"
                            >
                              Delete
                            </button>
                          </div>
                        </div>
                        <div className="mt-1 flex items-center gap-2">
                          {t.is_pinned && (
                            <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium text-blue-700">
                              Pinned
                            </span>
                          )}
                          {t.archived && (
                            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
                              Archived
                            </span>
                          )}
                        </div>
                        {t.last_message_preview && (
                          <p className="mt-1 line-clamp-2 text-xs text-slate-500">{t.last_message_preview}</p>
                        )}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </Card>

          <Card title="Context">
            <p className="text-sm text-slate-600">Plugin: {activePlugin}</p>
            <p className="text-sm text-slate-600">Dataset: {activeDataset?.dataset_id ?? "none"}</p>
            {activeDataset?.ingested_at && <p className="text-xs text-slate-500">Ingested: {activeDataset.ingested_at}</p>}
            {activeDataset?.row_count !== undefined && <p className="text-xs text-slate-500">Rows: {activeDataset.row_count}</p>}
            {conversationId && (
              <p className="mt-1 truncate text-xs text-slate-500" title={conversationId}>
                Thread: {conversationId.slice(0, 8)}...
              </p>
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
            <p className="text-sm text-slate-600">
              Session-based chat history with SQL trace, confidence, and context memory.
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
                    placeholder="Ask a question (follow-ups use session memory)..."
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        sendMessage();
                      }
                    }}
                  />
                  <Button onClick={() => sendMessage()} disabled={loading || loadingThreadMessages}>
                    {loading ? "Thinking..." : "Send"}
                  </Button>
                </div>
                <div className="text-xs text-slate-500">
                  Enter to send. Follow-up questions use saved session context and memory.
                </div>
              </div>

              {loadingThreadMessages ? (
                <div className="space-y-3">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <Skeleton key={i} className="h-28 w-full" />
                  ))}
                </div>
              ) : (
                <div className="space-y-4">
                  {messages.map((m, idx) => (
                    <div key={idx} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                        {m.role === "user" ? "You" : "Assistant"}
                      </div>
                      {m.role === "user" ? (
                        <p className="whitespace-pre-wrap text-sm text-slate-800">{m.content}</p>
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
                          <div className="mt-3 flex items-center gap-2 border-t border-slate-100 pt-2">
                            {feedbackGiven[idx] ? (
                              <span className="text-xs text-slate-500">
                                {feedbackGiven[idx] === 1 ? "Rated helpful" : "Rated not helpful"}
                              </span>
                            ) : (
                              <>
                                <button
                                  className="rounded px-2 py-1 text-xs text-slate-500 transition hover:bg-green-50 hover:text-green-700"
                                  onClick={() => handleFeedback(idx, 1, m.content as ChatResponse)}
                                  title="This answer was helpful"
                                >
                                  Helpful
                                </button>
                                <button
                                  className="rounded px-2 py-1 text-xs text-slate-500 transition hover:bg-red-50 hover:text-red-700"
                                  onClick={() => handleFeedback(idx, -1, m.content as ChatResponse)}
                                  title="This answer was not helpful"
                                >
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
                            <button
                              className="text-brand-blue hover:underline"
                              onClick={() => {
                                if (autoSend) sendMessage(s);
                                else setInput(s);
                              }}
                            >
                              {s}
                            </button>
                          </li>
                        ))}
                      </ul>
                    </Card>
                  )}
                </div>
              )}
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
                    <li key={q}>
                      <button
                        className="w-full text-left text-brand-blue hover:underline"
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
                Sessions are stored in the database. Follow-ups use both recent turns and session memory.
              </p>
            </Card>
            <Card title="Session Memory">
              {!conversationId ? (
                <p className="text-xs text-slate-500">Open a chat session to view learned memory.</p>
              ) : loadingMemory ? (
                <div className="space-y-2">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <Skeleton key={i} className="h-10 w-full" />
                  ))}
                </div>
              ) : threadMemory.length === 0 ? (
                <p className="text-xs text-slate-500">No memory extracted yet for this session.</p>
              ) : (
                <ul className="space-y-2">
                  {threadMemory.map((m) => (
                    <li key={m.memory_id} className="rounded border border-slate-200 bg-slate-50 p-2">
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                        {m.memory_type.replace(/_/g, " ")}
                      </p>
                      <p className="mt-1 text-xs text-slate-700 whitespace-pre-wrap">{m.content}</p>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </aside>
        )}
      </div>

      <UploadModal open={showUpload} onClose={() => setShowUpload(false)} onSuccess={handleUploadSuccess} />
    </div>
  );
};
