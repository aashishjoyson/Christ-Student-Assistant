// Live flow dashboard API. The admin key is passed in by the page and held in memory only (sent as X-Admin-Key).
import { parseFrame, splitFrames } from "../lib/sse";

export interface FlowEvent {
  seq: number;
  ts: string;
  trace_id: string;
  kind: string; // request | node | step | ingest
  name: string;
  phase: string; // start | end | error
  service: string;
  label: string;
  ms: number | null;
  detail: Record<string, unknown>;
}

export interface ServiceInfo { label: string; group: string; role: string }

export interface EvidentlySummary {
  available: boolean;
  run_id?: string;
  generated_at?: string;
  outcomes?: string[];
  by_mode?: Record<string, Record<string, number>>;
  by_category?: Record<string, Record<string, number>>;
  tests?: { name: string; description: string; status: string }[];
  tests_passed?: number;
  html_available?: boolean;
  html_kb?: number | null;
}

export class FlowAuthError extends Error {}

export async function getJson<T>(path: string, key: string): Promise<T> {
  const res = await fetch(path, { headers: { "X-Admin-Key": key } });
  if (res.status === 401) throw new FlowAuthError("That key was not accepted.");
  if (res.status === 403) throw new FlowAuthError("Admin routes are disabled: set ADMIN_API_KEY in .env.");
  if (!res.ok) throw new Error(`Request failed (${res.status}).`);
  return (await res.json()) as T;
}

export const getServices = (key: string) => getJson<{ services: Record<string, ServiceInfo> }>("/api/admin/flow/services", key).then((r) => r.services);
export const getRecent = (key: string, since = 0) =>
  getJson<{ enabled: boolean; last_seq: number; events: FlowEvent[] }>(`/api/admin/flow/recent?since=${since}&limit=600`, key);
export const getEvidently = (key: string) => getJson<EvidentlySummary>("/api/admin/flow/evidently", key);

export async function openEvidentlyReport(key: string): Promise<void> {
  const res = await fetch("/api/admin/flow/evidently/report", { headers: { "X-Admin-Key": key } });
  if (!res.ok) throw new Error("No Evidently report yet: run scripts/run_evaluation.py --evidently.");
  window.open(URL.createObjectURL(await res.blob()), "_blank");
}

/** Server-Sent Events over fetch (EventSource cannot send the admin key). Resolves when the stream ends; the caller reconnects. */
export async function streamFlow(key: string, since: number, onEvent: (event: FlowEvent) => void, signal: AbortSignal): Promise<void> {
  const res = await fetch(`/api/admin/flow/stream?since=${since}&max_seconds=900`, { headers: { "X-Admin-Key": key }, signal });
  if (res.status === 401 || res.status === 403) throw new FlowAuthError("That key was not accepted.");
  if (!res.ok || !res.body) throw new Error(`The stream failed (${res.status}).`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true });
    const { frames, rest } = splitFrames(buffer);
    buffer = rest;
    for (const frame of frames) {
      const parsed = parseFrame(frame);
      if (parsed && parsed.event === "flow") onEvent(parsed.data as FlowEvent);
    }
  }
}
