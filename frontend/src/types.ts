export type Confidence = "high" | "medium" | "low";

export type AnswerType = "number" | "table" | "text" | "insights";

export type ChartHint = "line" | "bar" | "pie" | "area" | "none";

export interface ChatResponse {
  answer_type: AnswerType;
  answer: any;
  explanation: string;
  sql: string | null;
  data_last_updated?: string | null;
  confidence: Confidence;
  plugin: string;
  summary?: string;
  narrative?: string;
  chart_hint?: ChartHint;
  assumptions?: string[];
  sanity_warnings?: string[];
  requires_clarification?: boolean;
  grounding?: {
    citations?: RAGContextCitation[];
    retrieval_counts?: { kb: number; examples: number; schema: number };
  };
  selected_tools?: string[];
  trust_reasons?: string[];
  question_interpreted?: string;
  requires_confirmation?: boolean;
  required_action?: string;
  explanation_bundle?: {
    question_original?: string;
    question_interpreted?: string;
    selected_tools?: string[];
    sql_used?: string | null;
    trust_reasons?: string[];
    style_applied?: string | null;
  };
  conversation_id?: string | null;
  history_id?: string | null;
}

export interface DashboardStats {
  total_rows: number;
  total_queries: number;
  avg_confidence: string;
  top_categories: { name: string; value: number }[];
  recent_trend: { date: string; value: number }[];
  query_volume: { date: string; count: number }[];
}

export interface Insight {
  insight_id: string;
  title: string;
  severity: "info" | "warning" | "critical";
  summary: string;
  details?: string;
  metrics: Record<string, unknown>;
  sql: Record<string, string> | string[]; // backend may return list or array
  data_window?: string;
  confidence?: Confidence;
  plugin: string;
  generated_at?: string;
}

export interface DatasetMeta {
  dataset_id: string;
  row_count?: number;
  ingested_at?: string;
  plugin: string;
  plugin_id?: string;
  filename?: string;
  source_filename?: string;
  created_at?: string;
  last_ingested_at?: string;
  version?: number;
  is_deleted?: boolean;
  // Dynamic ingestion fields
  table_name?: string | null;
  schema_type?: "static" | "dynamic";
  file_format?: string | null;
  column_count?: number | null;
}

export interface UploadSchemaColumn {
  column: string;
  type: string;
  nullable: boolean;
  sample_values: string[];
  distinct_count: number;
}

export interface UploadResult extends DatasetMeta {
  message: string;
  schema?: UploadSchemaColumn[];
  load_errors?: number;
}

export interface ConnectorSyncResult extends DatasetMeta {
  message: string;
  source_table: string;
  load_errors?: number;
}

export interface RemoteTablesResult {
  connector_id: string;
  tables: string[];
}

export interface RemoteSchemaResult {
  connector_id: string;
  table: string;
  columns: { name: string; type: string; nullable: boolean }[];
}

export interface PluginMeta {
  id: string;
  name: string;
  description: string;
  domains: string[];
  required_columns?: string[];
  sample_csv_url?: string;
  sample_csvs?: string[];
}

export interface QuestionPack {
  id: string;
  title: string;
  questions: string[];
}

export interface GlossaryTerm {
  term: string;
  definition: string;
}

export interface RAGContextCitation {
  source_type: string;
  id?: string;
  title?: string;
  score?: number;
}

export interface RAGKnowledgeDocument {
  doc_id: string;
  plugin_id: string;
  dataset_id?: string | null;
  title: string;
  source_type: string;
  source_uri?: string | null;
  created_at?: string;
  updated_at?: string;
  is_active?: boolean;
}

export interface RAGReviewItem {
  review_id: string;
  plugin_id: string;
  dataset_id?: string | null;
  question: string;
  rewritten_question?: string | null;
  proposed_sql?: string | null;
  reason?: string | null;
  confidence?: Confidence | string | null;
  status: string;
  resolution_notes?: string | null;
  resolved_sql?: string | null;
  resolved_by?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface AgentProfile {
  profile_id: string;
  user_id: string;
  plugin_id: string;
  response_style: string;
  preferred_chart_types: string[];
  preferred_kpis: string[];
  timezone?: string | null;
  notes?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface AgentGoalStep {
  step_id: string;
  goal_id: string;
  step_order: number;
  title: string;
  description?: string | null;
  tool_name: string;
  status: string;
  requires_approval: boolean;
  input_payload?: Record<string, any> | null;
  output_payload?: Record<string, any> | null;
  error?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface AgentGoal {
  goal_id: string;
  plugin_id: string;
  dataset_id?: string | null;
  user_id?: string | null;
  thread_id?: string | null;
  title: string;
  goal_text: string;
  status: string;
  priority: string;
  requires_human_approval: boolean;
  approval_token?: string | null;
  working_memory?: Record<string, any> | null;
  result_summary?: string | null;
  created_at?: string;
  updated_at?: string;
  completed_at?: string | null;
}

export interface AgentAutomation {
  automation_id: string;
  plugin_id: string;
  dataset_id?: string | null;
  user_id?: string | null;
  title: string;
  goal_text: string;
  task_type: string;
  schedule_cron: string;
  enabled: boolean;
  config?: Record<string, any> | null;
  last_run_at?: string | null;
  next_run_at?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface AgentMetrics {
  period_days: number;
  queries: number;
  feedback_items: number;
  goals_total: number;
  goals_completed: number;
  goals_failed: number;
  first_answer_accuracy_proxy: number;
  clarification_rate: number;
  correction_rate: number;
  human_handoff_rate: number;
}

export interface JobStatus {
  job_id: string;
  job_type: "INGEST_SALES" | "RUN_INSIGHTS" | string;
  plugin_id: string;
  dataset_id?: string | null;
  status: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED";
  created_at?: string;
  started_at?: string;
  finished_at?: string;
  progress_pct?: number | null;
  result?: any;
  failure_reason?: string | null;
}

// ── Multi-turn conversations ─────────────────────────────────────

export interface ConversationThread {
  thread_id: string;
  plugin_id: string;
  dataset_id?: string | null;
  title: string;
  is_pinned?: boolean;
  archived?: boolean;
  summary?: string | null;
  last_message_preview?: string | null;
  created_at?: string;
  updated_at?: string;
  messages?: ConversationMessageItem[];
}

export interface ConversationMessageItem {
  message_id: string;
  role: "user" | "assistant";
  content: string;
  sql?: string | null;
  answer_type?: string | null;
  payload?: ChatResponse | null;
  created_at?: string;
}

export interface ConversationMemoryItem {
  memory_id: string;
  thread_id: string;
  memory_type: string;
  content: string;
  confidence?: string | null;
  updated_at?: string;
}

// ── Query history & favorites ────────────────────────────────────

export interface QueryHistoryItem {
  id: string;
  plugin_id: string;
  dataset_id?: string | null;
  question: string;
  sql?: string | null;
  answer_type?: string | null;
  answer_summary?: string | null;
  confidence?: Confidence | null;
  is_favorite: boolean;
  share_token?: string | null;
  created_at?: string;
}

// ── Feedback ─────────────────────────────────────────────────────

export interface FeedbackPayload {
  plugin_id: string;
  question: string;
  original_sql?: string | null;
  corrected_sql?: string | null;
  rating: 1 | -1;
  comment?: string | null;
  query_history_id?: string | null;
}

export interface FeedbackItem {
  id: string;
  plugin_id: string;
  question: string;
  original_sql?: string | null;
  corrected_sql?: string | null;
  rating: number;
  comment?: string | null;
  created_at?: string;
}

export interface FeedbackStats {
  total: number;
  positive: number;
  negative: number;
  corrections: number;
  approval_rate: number;
}

// ── Custom dashboards ────────────────────────────────────────────

export interface DashboardWidget {
  widget_id: string;
  dashboard_id: string;
  title: string;
  widget_type: "chart" | "kpi" | "table";
  query_text?: string | null;
  sql?: string | null;
  chart_hint?: ChartHint | null;
  config?: Record<string, any> | null;
  position?: { x: number; y: number; w: number; h: number } | null;
  created_at?: string;
}

export interface CustomDashboard {
  dashboard_id: string;
  title: string;
  plugin_id: string;
  description?: string | null;
  layout?: Record<string, any> | null;
  widgets: DashboardWidget[];
  created_at?: string;
  updated_at?: string;
}

// ── Scheduled reports ────────────────────────────────────────────

export interface ScheduledReport {
  report_id: string;
  title: string;
  plugin_id: string;
  dataset_id?: string | null;
  schedule_cron: string;
  report_type: "insights" | "query" | "dashboard";
  config?: Record<string, any> | null;
  delivery?: { method: string; target: string } | null;
  enabled: boolean;
  last_run_at?: string | null;
  next_run_at?: string | null;
  created_at?: string;
}

// ── Data connectors ──────────────────────────────────────────────

export interface DataConnector {
  connector_id: string;
  name: string;
  connector_type: string;
  config?: Record<string, any> | null;
  plugin_id?: string | null;
  status: string;
  last_sync_at?: string | null;
  created_at?: string;
}

// ── Data catalog / column profiles ───────────────────────────────

export interface ColumnProfileInfo {
  id?: string;
  column_name: string;
  data_type?: string | null;
  null_count?: number | null;
  distinct_count?: number | null;
  min_value?: string | null;
  max_value?: string | null;
  mean_value?: number | null;
  description?: string | null;
  sample_values?: string[] | null;
  profiled_at?: string | null;
}

// ── Usage / rate limit ───────────────────────────────────────────

export interface UsageCosts {
  period_days: number;
  total_calls: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_estimated_cost_usd: number;
  by_model: Record<string, { calls: number; input_tokens: number; output_tokens: number; cost: number }>;
}

export interface RateLimitStatus {
  client_ip: string;
  requests_in_window: number;
  max_requests: number;
  window_seconds: number;
  remaining: number;
}
