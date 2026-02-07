export type Confidence = "high" | "medium" | "low";

export type AnswerType = "number" | "table" | "text" | "insights";

export interface ChatResponse {
  answer_type: AnswerType;
  answer: any;
  explanation: string;
  sql: string | null;
  data_last_updated?: string | null;
  confidence: Confidence;
  plugin: string;
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
  filename?: string;
  source_filename?: string;
  created_at?: string;
  last_ingested_at?: string;
  version?: number;
  is_deleted?: boolean;
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
