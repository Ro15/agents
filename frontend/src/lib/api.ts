import type { ChatResponse, DatasetMeta, Insight, PluginMeta, QuestionPack, JobStatus } from "../types";

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

// Plugins
export const getPlugins = async (): Promise<PluginMeta[]> => {
  const data = await request<{ plugins: PluginMeta[]; active_plugin?: string }>("/plugins");
  return data.plugins ?? [];
};
export const getPlugin = (pluginId: string) => request<any>(`/plugins/${pluginId}`);
export const getPluginQuestions = (pluginId: string) => request<QuestionPack[]>(`/plugins/${pluginId}/questions`);
export const getPluginViews = async (pluginId: string) => {
  try {
    const res = await request<any>(`/plugins/${pluginId}/views`);
    return res?.views || [];
  } catch {
    return [];
  }
};

// Datasets
export const listDatasets = (pluginId?: string) =>
  request<DatasetMeta[]>(`/datasets${pluginId ? `?plugin_id=${encodeURIComponent(pluginId)}` : ""}`);
export const getDataset = (datasetId: string) => request<DatasetMeta>(`/datasets/${datasetId}`);
export const deleteDataset = (datasetId: string) => request<{ status: string }>(`/datasets/${datasetId}`, { method: "DELETE" });

// Upload (sync)
export async function uploadSalesSync(plugin: string, file: File, datasetName?: string): Promise<DatasetMeta> {
  const form = new FormData();
  form.append("file", file);
  if (datasetName) form.append("dataset_name", datasetName);
  return request<DatasetMeta>("/upload/sales", { method: "POST", body: form, headers: { "x-plugin": plugin } });
}

// Upload (async)
export async function uploadSalesAsync(plugin: string, file: File, datasetName?: string): Promise<{ job_id: string }> {
  const form = new FormData();
  form.append("file", file);
  form.append("plugin_id", plugin);
  if (datasetName) form.append("dataset_name", datasetName);
  return request<{ job_id: string }>("/upload/sales/async", { method: "POST", body: form });
}

// Auto upload with fallback
export async function uploadSalesAuto(plugin: string, file: File, datasetName?: string): Promise<{ asyncUsed: boolean; job_id?: string; dataset?: DatasetMeta }> {
  try {
    const asyncRes = await uploadSalesAsync(plugin, file, datasetName);
    return { asyncUsed: true, job_id: asyncRes.job_id };
  } catch (err: any) {
    if (err instanceof ApiError && (err.status === 404 || err.status === 400)) {
      const syncRes = await uploadSalesSync(plugin, file, datasetName);
      return { asyncUsed: false, dataset: syncRes };
    }
    throw err;
  }
}

// Chat
export const chat = (plugin: string, dataset_id: string | null, message: string) =>
  request<ChatResponse>("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plugin, dataset_id, query: message }),
  });

// Insights
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

// Jobs
export const getJob = (jobId: string) => request<JobStatus>(`/jobs/${jobId}`);
export const listJobs = (pluginId?: string, datasetId?: string, status?: string) => {
  const params = new URLSearchParams();
  if (pluginId) params.set("plugin_id", pluginId);
  if (datasetId) params.set("dataset_id", datasetId);
  if (status) params.set("status", status);
  const q = params.toString();
  return request<JobStatus[]>(`/jobs${q ? `?${q}` : ""}`);
};
