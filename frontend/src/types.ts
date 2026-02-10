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
  created_at?: string;
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
