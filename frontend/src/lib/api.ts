import type {
  ChatResponse,
  DashboardStats,
  DatasetMeta,
  Insight,
  PluginMeta,
  QuestionPack,
  GlossaryTerm,
  RAGKnowledgeDocument,
  RAGReviewItem,
  AgentProfile,
  AgentGoal,
  AgentGoalStep,
  AgentAutomation,
  AgentMetrics,
  JobStatus,
  ConversationThread,
  ConversationMemoryItem,
  QueryHistoryItem,
  FeedbackPayload,
  FeedbackItem,
  FeedbackStats,
  CustomDashboard,
  DashboardWidget,
  ScheduledReport,
  DataConnector,
  ColumnProfileInfo,
  UsageCosts,
  RateLimitStatus,
  UploadResult,
  ConnectorSyncResult,
  RemoteTablesResult,
  RemoteSchemaResult,
} from "../types";

export class ApiError extends Error {
  status: number;
  body?: any;
  constructor(message: string, status: number, body?: any) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    /* ignore */
  }
  if (!res.ok) {
    throw new ApiError(data?.detail || data?.message || text || "Request failed", res.status, data);
  }
  return data as T;
}

// ── Plugins ──────────────────────────────────────────────────────
export const getPlugins = async (): Promise<PluginMeta[]> => {
  const data = await request<{ plugins: PluginMeta[]; active_plugin?: string }>("/plugins");
  return data.plugins ?? [];
};
export const getPlugin = (pluginId: string) => request<any>(`/plugins/${pluginId}`);
export const getPluginQuestions = (pluginId: string) => request<QuestionPack[]>(`/plugins/${pluginId}/questions`);
export const getPluginGlossary = (pluginId: string) => request<{ plugin: string; glossary: GlossaryTerm[] }>(`/plugins/${pluginId}/glossary`);
export const runRagEval = (pluginId: string, datasetId?: string) =>
  request<any>(`/rag/eval?plugin_id=${encodeURIComponent(pluginId)}${datasetId ? `&dataset_id=${encodeURIComponent(datasetId)}` : ""}`);
export const getPluginViews = async (pluginId: string) => {
  try {
    const res = await request<any>(`/plugins/${pluginId}/views`);
    return res?.views || [];
  } catch {
    return [];
  }
};

// ── Datasets ─────────────────────────────────────────────────────
export const listDatasets = (pluginId?: string) =>
  request<DatasetMeta[]>(`/datasets${pluginId ? `?plugin_id=${encodeURIComponent(pluginId)}` : ""}`);
export const getDataset = (datasetId: string) => request<DatasetMeta>(`/datasets/${datasetId}`);
export const deleteDataset = (datasetId: string) => request<{ status: string }>(`/datasets/${datasetId}`, { method: "DELETE" });

// ── Upload (sync) ────────────────────────────────────────────────
export async function uploadSalesSync(plugin: string, file: File, datasetName?: string): Promise<DatasetMeta> {
  const form = new FormData();
  form.append("file", file);
  if (datasetName) form.append("dataset_name", datasetName);
  return request<DatasetMeta>("/upload/sales", { method: "POST", body: form, headers: { "x-plugin": plugin } });
}

// ── Universal Upload (flexible schema) ──────────────────────────
export async function uploadUniversal(
  file: File,
  pluginId: string = "default",
  datasetName?: string,
  sheetName?: string,
): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);
  let qs = `?plugin_id=${encodeURIComponent(pluginId)}`;
  if (datasetName) qs += `&dataset_name=${encodeURIComponent(datasetName)}`;
  if (sheetName) qs += `&sheet_name=${encodeURIComponent(sheetName)}`;
  return request<UploadResult>(`/upload${qs}`, { method: "POST", body: form });
}

// ── Upload (async – uses universal endpoint) ──────────────────────────────────
export async function uploadSalesAsync(plugin: string, file: File, datasetName?: string): Promise<{ job_id: string }> {
  const res = await uploadUniversal(file, plugin, datasetName);
  return { job_id: (res as any).job_id || (res as any).dataset_id || "" };
}

// ── Auto upload with fallback ────────────────────────────────────
export async function uploadSalesAuto(plugin: string, file: File, datasetName?: string): Promise<{ asyncUsed: boolean; job_id?: string; dataset?: DatasetMeta }> {
  // Prefer universal upload, fall back to legacy
  try {
    const res = await uploadUniversal(file, plugin, datasetName);
    return { asyncUsed: false, dataset: res };
  } catch {
    const syncRes = await uploadSalesSync(plugin, file, datasetName);
    return { asyncUsed: false, dataset: syncRes };
  }
}

// ── Connector remote browsing ────────────────────────────────────
export const getConnectorTables = (connectorId: string) =>
  request<RemoteTablesResult>(`/connectors/${connectorId}/tables`);

export const getConnectorSchema = (connectorId: string, tableName: string) =>
  request<RemoteSchemaResult>(`/connectors/${connectorId}/schema/${encodeURIComponent(tableName)}`);

export const syncConnectorTable = (
  connectorId: string,
  tableName?: string,
  pluginId?: string,
  limit?: number,
) => {
  let qs = "?";
  if (tableName) qs += `table_name=${encodeURIComponent(tableName)}&`;
  if (pluginId) qs += `plugin_id=${encodeURIComponent(pluginId)}&`;
  if (limit) qs += `limit=${limit}&`;
  return request<ConnectorSyncResult>(`/connectors/${connectorId}/sync${qs.replace(/&$/, "")}`, { method: "POST" });
};

// ── Chat (with multi-turn support) ──────────────────────────────
export const chat = (
  plugin: string,
  dataset_id: string | null,
  message: string,
  conversation_id?: string | null,
  conversation_history?: { role: string; content: string }[],
  options?: { user_id?: string; confirm_action?: boolean },
) =>
  request<ChatResponse>("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      plugin,
      dataset_id,
      query: message,
      conversation_id: conversation_id || undefined,
      conversation_history: conversation_history || undefined,
      user_id: options?.user_id || undefined,
      confirm_action: options?.confirm_action || undefined,
    }),
  });

// ── Insights ─────────────────────────────────────────────────────
export const runInsightsSync = (plugin: string, dataset_id: string, limit = 20) =>
  request<any>("/insights/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plugin, dataset_id, limit }),
  }).then(normalizeInsightsResponse);

export const runInsightsAsync = (plugin: string, dataset_id: string, limit = 20) =>
  request<{ job_id: string }>("/insights/run/async", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plugin, dataset_id, limit }),
  });

export const getLatestInsights = (plugin: string, dataset_id: string, limit = 20) => {
  const params = new URLSearchParams({ plugin, dataset_id, limit: String(limit) });
  return request<any>(`/insights/latest?${params.toString()}`).then(normalizeInsightsResponse);
};

function normalizeInsightsResponse(data: any): Insight[] {
  if (!data) return [];
  if (Array.isArray(data)) return data as Insight[];
  if (Array.isArray(data.insights)) return data.insights as Insight[];
  return [];
}

// ── Dashboard stats ──────────────────────────────────────────────
export const getDashboardStats = (plugin: string, datasetId?: string) => {
  const params = new URLSearchParams({ plugin });
  if (datasetId) params.set("dataset_id", datasetId);
  return request<DashboardStats>(`/dashboard/stats?${params.toString()}`);
};

// ── Jobs ─────────────────────────────────────────────────────────
export const getJob = (jobId: string) => request<JobStatus>(`/jobs/${jobId}`);
export const listJobs = (pluginId?: string, datasetId?: string, status?: string) => {
  const params = new URLSearchParams();
  if (pluginId) params.set("plugin_id", pluginId);
  if (datasetId) params.set("dataset_id", datasetId);
  if (status) params.set("status", status);
  const q = params.toString();
  return request<JobStatus[]>(`/jobs${q ? `?${q}` : ""}`);
};

// ═════════════════════════════════════════════════════════════════
// NEW FEATURE APIS
// ═════════════════════════════════════════════════════════════════

// ── Conversations (multi-turn) ───────────────────────────────────
export const createConversation = (plugin_id: string, dataset_id?: string | null, title?: string) =>
  request<ConversationThread>("/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plugin_id, dataset_id, title }),
  });

export const listConversations = (
  plugin_id?: string,
  dataset_id?: string,
  opts?: { search?: string; include_archived?: boolean; limit?: number }
) => {
  const params = new URLSearchParams();
  if (plugin_id) params.set("plugin_id", plugin_id);
  if (dataset_id) params.set("dataset_id", dataset_id);
  if (opts?.search) params.set("search", opts.search);
  if (opts?.include_archived) params.set("include_archived", "true");
  if (opts?.limit) params.set("limit", String(opts.limit));
  const q = params.toString();
  return request<ConversationThread[]>(`/conversations${q ? `?${q}` : ""}`);
};

export const getConversation = (threadId: string) =>
  request<ConversationThread & { messages: any[] }>(`/conversations/${threadId}`);

export const updateConversation = (
  threadId: string,
  data: { title?: string; is_pinned?: boolean; archived?: boolean }
) =>
  request<ConversationThread>(`/conversations/${threadId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });

export const getConversationMemory = (threadId: string) =>
  request<ConversationMemoryItem[]>(`/conversations/${threadId}/memory`);

export const deleteConversation = (threadId: string) =>
  request<{ status: string }>(`/conversations/${threadId}`, { method: "DELETE" });

// ── RAG Knowledge & Review ───────────────────────────────────────────
export const ingestKnowledgeDoc = (payload: {
  plugin_id: string;
  dataset_id?: string | null;
  title: string;
  content: string;
  source_type?: string;
  source_uri?: string | null;
  metadata_json?: Record<string, any>;
}) =>
  request<RAGKnowledgeDocument>("/rag/kb", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

export const listKnowledgeDocs = (pluginId?: string, datasetId?: string) => {
  const params = new URLSearchParams();
  if (pluginId) params.set("plugin_id", pluginId);
  if (datasetId) params.set("dataset_id", datasetId);
  return request<RAGKnowledgeDocument[]>(`/rag/kb${params.toString() ? `?${params.toString()}` : ""}`);
};

export const searchKnowledge = (pluginId: string, question: string, datasetId?: string, limit = 8) => {
  const params = new URLSearchParams({
    plugin_id: pluginId,
    question,
    limit: String(limit),
  });
  if (datasetId) params.set("dataset_id", datasetId);
  return request<any[]>(`/rag/kb/search?${params.toString()}`);
};

export const getRagReviewQueue = (pluginId?: string, status = "open", limit = 100) => {
  const params = new URLSearchParams({ status, limit: String(limit) });
  if (pluginId) params.set("plugin_id", pluginId);
  return request<RAGReviewItem[]>(`/rag/review?${params.toString()}`);
};

export const resolveRagReview = (
  reviewId: string,
  payload: { status: "approved" | "rejected" | "resolved"; resolution_notes?: string; resolved_sql?: string; resolved_by?: string }
) =>
  request<{ status: string; review_id: string; new_status: string }>(`/rag/review/${reviewId}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

// ── Agent APIs ─────────────────────────────────────────────────────────
export const getAgentProfile = (userId: string, pluginId: string) =>
  request<AgentProfile>(`/agent/profile?user_id=${encodeURIComponent(userId)}&plugin_id=${encodeURIComponent(pluginId)}`);

export const updateAgentProfile = (payload: {
  user_id: string;
  plugin_id: string;
  response_style?: string;
  preferred_chart_types?: string[];
  preferred_kpis?: string[];
  timezone?: string;
  notes?: string;
}) =>
  request<AgentProfile>("/agent/profile", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

export const inferAgentProfile = (userId: string, pluginId: string, textValue: string) =>
  request<AgentProfile>(
    `/agent/profile/infer?user_id=${encodeURIComponent(userId)}&plugin_id=${encodeURIComponent(pluginId)}&text_value=${encodeURIComponent(textValue)}`
  );

export const createAgentGoal = (payload: {
  plugin_id: string;
  dataset_id?: string;
  user_id?: string;
  thread_id?: string;
  goal_text: string;
  priority?: "low" | "normal" | "high";
}) =>
  request<{ goal: AgentGoal; steps: AgentGoalStep[] }>("/agent/goals", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

export const listAgentGoals = (opts?: { plugin_id?: string; user_id?: string; status?: string; limit?: number }) => {
  const p = new URLSearchParams();
  if (opts?.plugin_id) p.set("plugin_id", opts.plugin_id);
  if (opts?.user_id) p.set("user_id", opts.user_id);
  if (opts?.status) p.set("status", opts.status);
  if (opts?.limit) p.set("limit", String(opts.limit));
  return request<AgentGoal[]>(`/agent/goals${p.toString() ? `?${p.toString()}` : ""}`);
};

export const getAgentGoal = (goalId: string) =>
  request<{ goal: AgentGoal; steps: AgentGoalStep[] }>(`/agent/goals/${goalId}`);

export const runAgentGoal = (
  goalId: string,
  payload?: { auto_approve?: boolean; max_steps?: number; approval_token?: string }
) =>
  request<{ run: any; goal: AgentGoal; steps: AgentGoalStep[] }>(`/agent/goals/${goalId}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });

export const approveAgentGoal = (goalId: string, approvalToken: string) =>
  request<{ status: string; run: any }>(`/agent/goals/${goalId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approval_token: approvalToken }),
  });

export const createAgentAutomation = (payload: {
  plugin_id: string;
  dataset_id?: string;
  user_id?: string;
  title: string;
  goal_text: string;
  task_type?: string;
  schedule_cron?: string;
  config?: Record<string, any>;
}) =>
  request<AgentAutomation>("/agent/automations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

export const listAgentAutomations = (opts?: { plugin_id?: string; user_id?: string; enabled?: boolean; limit?: number }) => {
  const p = new URLSearchParams();
  if (opts?.plugin_id) p.set("plugin_id", opts.plugin_id);
  if (opts?.user_id) p.set("user_id", opts.user_id);
  if (opts?.enabled !== undefined) p.set("enabled", String(opts.enabled));
  if (opts?.limit) p.set("limit", String(opts.limit));
  return request<AgentAutomation[]>(`/agent/automations${p.toString() ? `?${p.toString()}` : ""}`);
};

export const updateAgentAutomation = (automationId: string, payload: Partial<AgentAutomation>) =>
  request<AgentAutomation>(`/agent/automations/${automationId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

export const deleteAgentAutomation = (automationId: string) =>
  request<{ status: string; automation_id: string }>(`/agent/automations/${automationId}`, { method: "DELETE" });

export const runAutomationNow = (automationId: string) =>
  request<{ automation: AgentAutomation; goal_id: string; run: any }>(`/agent/automations/${automationId}/run-now`, { method: "POST" });

export const runDueAutomations = (pluginId?: string, limit = 10) =>
  request<{ triggered: number; runs: any[]; run_at: string }>(
    `/agent/automations/run-due?${new URLSearchParams({
      ...(pluginId ? { plugin_id: pluginId } : {}),
      limit: String(limit),
    }).toString()}`
  , { method: "POST" });

export const getAgentMetrics = (pluginId?: string, days = 30) =>
  request<AgentMetrics>(
    `/agent/metrics?${new URLSearchParams({
      ...(pluginId ? { plugin_id: pluginId } : {}),
      days: String(days),
    }).toString()}`
  );

// ── Query history ────────────────────────────────────────────────
export const getQueryHistory = (opts?: { plugin_id?: string; dataset_id?: string; favorites_only?: boolean; limit?: number; offset?: number }) => {
  const params = new URLSearchParams();
  if (opts?.plugin_id) params.set("plugin_id", opts.plugin_id);
  if (opts?.dataset_id) params.set("dataset_id", opts.dataset_id);
  if (opts?.favorites_only) params.set("favorites_only", "true");
  if (opts?.limit) params.set("limit", String(opts.limit));
  if (opts?.offset) params.set("offset", String(opts.offset));
  return request<{ total: number; items: QueryHistoryItem[] }>(`/history?${params.toString()}`);
};

export const toggleFavorite = (entryId: string) =>
  request<{ id: string; is_favorite: boolean }>(`/history/${entryId}/favorite`, { method: "POST" });

export const createShareLink = (entryId: string) =>
  request<{ id: string; share_token: string }>(`/history/${entryId}/share`, { method: "POST" });

export const getSharedQuery = (token: string) =>
  request<QueryHistoryItem>(`/history/shared/${token}`);

// ── Feedback ─────────────────────────────────────────────────────
export const submitFeedback = (payload: FeedbackPayload) =>
  request<{ id: string; status: string }>("/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

export const listFeedback = (plugin_id?: string, rating?: number) => {
  const params = new URLSearchParams();
  if (plugin_id) params.set("plugin_id", plugin_id);
  if (rating !== undefined) params.set("rating", String(rating));
  return request<FeedbackItem[]>(`/feedback?${params.toString()}`);
};

export const getFeedbackStats = (plugin_id?: string) => {
  const params = new URLSearchParams();
  if (plugin_id) params.set("plugin_id", plugin_id);
  return request<FeedbackStats>(`/feedback/stats?${params.toString()}`);
};

// ── Custom dashboards ────────────────────────────────────────────
export const createDashboard = (title: string, plugin_id: string, description?: string) =>
  request<CustomDashboard>("/dashboards", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, plugin_id, description }),
  });

export const listDashboards = (plugin_id?: string) => {
  const params = new URLSearchParams();
  if (plugin_id) params.set("plugin_id", plugin_id);
  return request<CustomDashboard[]>(`/dashboards?${params.toString()}`);
};

export const getDashboard = (dashboardId: string) =>
  request<CustomDashboard>(`/dashboards/${dashboardId}`);

export const updateDashboard = (dashboardId: string, data: { title?: string; description?: string; layout?: any }) =>
  request<CustomDashboard>(`/dashboards/${dashboardId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });

export const deleteDashboard = (dashboardId: string) =>
  request<{ status: string }>(`/dashboards/${dashboardId}`, { method: "DELETE" });

export const addWidget = (dashboardId: string, widget: { title: string; widget_type?: string; query_text?: string; sql?: string; chart_hint?: string; config?: any; position?: any }) =>
  request<DashboardWidget>(`/dashboards/${dashboardId}/widgets`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(widget),
  });

export const updateWidget = (dashboardId: string, widgetId: string, data: Partial<DashboardWidget>) =>
  request<DashboardWidget>(`/dashboards/${dashboardId}/widgets/${widgetId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });

export const deleteWidget = (dashboardId: string, widgetId: string) =>
  request<{ status: string }>(`/dashboards/${dashboardId}/widgets/${widgetId}`, { method: "DELETE" });

// ── Scheduled reports ────────────────────────────────────────────
export const createSchedule = (data: { title: string; plugin_id: string; dataset_id?: string; schedule_cron?: string; report_type?: string; config?: any; delivery?: any }) =>
  request<ScheduledReport>("/schedules", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });

export const listSchedules = (plugin_id?: string, enabled?: boolean) => {
  const params = new URLSearchParams();
  if (plugin_id) params.set("plugin_id", plugin_id);
  if (enabled !== undefined) params.set("enabled", String(enabled));
  return request<ScheduledReport[]>(`/schedules?${params.toString()}`);
};

export const getSchedule = (reportId: string) =>
  request<ScheduledReport>(`/schedules/${reportId}`);

export const updateSchedule = (reportId: string, data: Partial<ScheduledReport>) =>
  request<ScheduledReport>(`/schedules/${reportId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });

export const deleteSchedule = (reportId: string) =>
  request<{ status: string }>(`/schedules/${reportId}`, { method: "DELETE" });

export const runScheduleNow = (reportId: string) =>
  request<{ status: string; report_id: string; run_at: string }>(`/schedules/${reportId}/run-now`, { method: "POST" });

// ── Data connectors ──────────────────────────────────────────────
export const createConnector = (data: { name: string; connector_type: string; config?: any; plugin_id?: string }) =>
  request<DataConnector>("/connectors", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });

export const listConnectors = (plugin_id?: string) => {
  const params = new URLSearchParams();
  if (plugin_id) params.set("plugin_id", plugin_id);
  return request<DataConnector[]>(`/connectors?${params.toString()}`);
};

export const getConnector = (connectorId: string) =>
  request<DataConnector>(`/connectors/${connectorId}`);

export const updateConnector = (connectorId: string, data: Partial<DataConnector>) =>
  request<DataConnector>(`/connectors/${connectorId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });

export const deleteConnector = (connectorId: string) =>
  request<{ status: string }>(`/connectors/${connectorId}`, { method: "DELETE" });

export const testConnector = (connectorId: string) =>
  request<{ connector_id: string; status: string; message: string }>(`/connectors/${connectorId}/test`, { method: "POST" });

export const syncConnector = (connectorId: string) =>
  request<{ connector_id: string; status: string; message: string }>(`/connectors/${connectorId}/sync`, { method: "POST" });

// ── Data catalog ─────────────────────────────────────────────────
export const profileDataset = (datasetId: string) =>
  request<{ dataset_id: string; columns_profiled: number; profiles: ColumnProfileInfo[] }>(`/catalog/profile/${datasetId}`, { method: "POST" });

export const getDataCatalog = (datasetId: string) =>
  request<{ dataset_id: string; columns: ColumnProfileInfo[] }>(`/catalog/${datasetId}`);

export const updateColumnDescription = (datasetId: string, columnName: string, description: string) =>
  request<{ dataset_id: string; column_name: string; description: string }>(
    `/catalog/${datasetId}/columns/${columnName}?description=${encodeURIComponent(description)}`,
    { method: "PUT" }
  );

// ── Usage / rate limiting ────────────────────────────────────────
export const getUsageCosts = (plugin_id?: string, days?: number) => {
  const params = new URLSearchParams();
  if (plugin_id) params.set("plugin_id", plugin_id);
  if (days) params.set("days", String(days));
  return request<UsageCosts>(`/usage/costs?${params.toString()}`);
};

export const getRateLimitStatus = () =>
  request<RateLimitStatus>("/usage/limits");
