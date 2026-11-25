// Pure helpers that turn the raw event stream into what the dashboard draws. No React, no network.
import type { FlowEvent } from "../api/flow";

export type NodeState = "idle" | "active" | "done" | "error";

export interface Trace {
  id: string;
  kind: "chat" | "sync";
  events: FlowEvent[];
  startedAt: string;
  finished: boolean;
  failed: boolean;
  totalMs: number | null;
}

/** One trace per chat request ("m-...") or per Drive sync ("sync-12"), newest first. Events outside any request are ignored. */
export function groupTraces(events: FlowEvent[]): Trace[] {
  const byId = new Map<string, FlowEvent[]>();
  for (const e of events) {
    if (e.trace_id === "system") continue;
    const list = byId.get(e.trace_id);
    if (list) list.push(e);
    else byId.set(e.trace_id, [e]);
  }
  const traces: Trace[] = [];
  for (const [id, list] of byId) {
    const sync = id.startsWith("sync-");
    const end = list.find((e) => e.kind === (sync ? "ingest" : "request") && e.name === (sync ? "sync" : "request") && e.phase !== "start");
    traces.push({ id, kind: sync ? "sync" : "chat", events: list, startedAt: list[0].ts, finished: Boolean(end), failed: end?.phase === "error", totalMs: end?.ms ?? null });
  }
  return traces.reverse();
}

/** Which boxes on the map are working, finished or failed in one trace. */
export function serviceStates(trace: Trace | undefined): Record<string, NodeState> {
  const states: Record<string, NodeState> = {};
  if (!trace) return states;
  const startedOn: Record<string, string> = {};
  for (const e of trace.events) {
    if (e.phase === "start") {
      states[e.service] = "active";
      if (e.kind === "node") startedOn[e.name] = e.service;
      continue;
    }
    const was = e.kind === "node" ? startedOn[e.name] : undefined;
    states[e.service] = e.phase === "error" ? "error" : "done";
    if (was && was !== e.service) states[was] = "done";
  }
  if (trace.finished) for (const [id, s] of Object.entries(states)) if (s === "active") states[id] = "done";
  return states;
}

export interface StepRow { e: FlowEvent; running: boolean }

/** The timeline: finished steps in order, plus the nodes still running (a start with no end yet). */
export function stepsOf(trace: Trace): StepRow[] {
  const ended = new Set(trace.events.filter((x) => x.kind === "node" && x.phase !== "start").map((x) => x.name));
  const rows: StepRow[] = [];
  for (const e of trace.events) {
    if (e.phase !== "start") rows.push({ e, running: false });
    else if (e.kind === "request") rows.push({ e, running: false });
    else if (e.kind === "node" && !ended.has(e.name) && !trace.finished) rows.push({ e, running: true });
  }
  return rows;
}

export const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
export const text = (v: unknown): string => (v === null || v === undefined ? "" : String(v));
