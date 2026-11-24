// Admin API calls. The key is passed in by the page and held in memory only (never in storage), sent as the X-Admin-Key header.
export interface Alert { level: "critical" | "warning" | "info"; code: string; message: string }

export interface WindowSummary {
  requests: number; errors: number; error_rate: number | null; error_codes: Record<string, number>;
  latency_ms: { p50: number | null; p95: number | null }; first_word_ms: { p50: number | null; p95: number | null };
  cost_usd_total: number; cost_usd_per_request: number | null;
  document_questions: number; no_evidence_rate: number | null; not_indexed: number;
  best_distance: { mean: number | null; p50: number | null; p90: number | null; n: number };
  intent_mix: Record<string, number>; mode_mix: Record<string, number>;
  feedback: { votes: number; down: number; thumbs_down_rate: number | null; down_reasons: Record<string, number> };
}

export interface MonitoringReport {
  generated_at: string; window_hours: number; reference_hours: number; status: "ok" | "warning" | "critical";
  alerts: Alert[]; current: WindowSummary; reference: WindowSummary;
  index: { last_successful_sync: string | null; age_seconds: number | null; automatic_ingestion: boolean };
}

export interface IngestedFile { source: string; name: string; status: string; chunk_count: number; indexed_at: string | null; last_error: string | null }
export interface IngestionStatus {
  drive_configured: boolean; drive_ready: boolean; drive_error: string | null; poll_enabled: boolean; poll_interval_seconds: number;
  files: IngestedFile[]; counts: Record<string, number>; seconds_since_last_success: number | null;
  pollers: { name: string; enabled: boolean; last_status: string | null; consecutive_failures: number; runs: number }[];
}

export interface ModeMetrics { [metric: string]: number | null }
export interface RunSummary { run_id: string; created_at?: string | null; git?: { commit: string | null; dirty: boolean | null } | null; modes: Record<string, ModeMetrics> }
export interface Experiments { baseline: (RunSummary & { promoted_at: string; reason: string }) | null; runs: RunSummary[] }

export class AdminError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function call<T>(path: string, key: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, { ...init, headers: { "X-Admin-Key": key, ...(init.headers ?? {}) } });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof body?.detail === "string" ? body.detail : "Request failed.";
    throw new AdminError(res.status, res.status === 401 ? "That key was not accepted." : detail);
  }
  return body as T;
}

export const getMonitoring = (key: string) => call<MonitoringReport>("/api/admin/monitoring/summary?hours=24&reference_hours=168", key);
export const getIngestion = (key: string) => call<IngestionStatus>("/api/admin/drive/status", key);
export const getExperiments = (key: string) => call<Experiments>("/api/admin/experiments/summary?limit=8", key);
export const syncDriveNow = (key: string) => call<{ status: string; files_indexed: number; files_skipped: number; files_failed: number; est_embedding_cost_usd: number | null }>(
  "/api/admin/drive/sync", key, { method: "POST" });
