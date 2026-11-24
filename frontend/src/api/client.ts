import { parseFrame, splitFrames } from "../lib/sse";
import type { ChatResponse, FeedbackRating, FeedbackReason, Health, ModelMode, StreamEvent, VerifyResponse } from "./types";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

type JsonInit = Omit<RequestInit, "headers"> & { headers?: Record<string, string> };

async function request<T>(path: string, init: JsonInit = {}): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    // Backend errors are either {error:{code,message}} or FastAPI's {detail: ...}
    const code = body?.error?.code ?? `http_${res.status}`;
    const detail = typeof body?.detail === "string" ? body.detail : "Request failed.";
    throw new ApiError(res.status, code, body?.error?.message ?? detail);
  }
  return body as T;
}

export const getHealth = () => request<Health>("/api/health");

export function sendChat(args: {
  message: string;
  modelMode: ModelMode;
  conversationId: string | null;
  applicantToken: string | null;
}): Promise<ChatResponse> {
  return request<ChatResponse>("/api/chat", {
    method: "POST",
    headers: args.applicantToken ? { "X-Applicant-Session": args.applicantToken } : {},
    body: JSON.stringify({
      message: args.message,
      model_mode: args.modelMode,
      conversation_id: args.conversationId,
      client_message_id: crypto.randomUUID(),
    }),
  });
}

/**
 * Streamed chat turn (Server-Sent Events over fetch, because EventSource cannot POST).
 * Resolves when the stream ends; `onEvent` receives start / delta / final / error events in order.
 * A failure BEFORE any text (model not configured, rate limit) is thrown as an ApiError, exactly like sendChat.
 */
export async function streamChat(
  args: { message: string; modelMode: ModelMode; conversationId: string | null; applicantToken: string | null },
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch("/api/chat/stream", {
    method: "POST",
    signal,
    headers: { "Content-Type": "application/json", ...(args.applicantToken ? { "X-Applicant-Session": args.applicantToken } : {}) },
    body: JSON.stringify({
      message: args.message,
      model_mode: args.modelMode,
      conversation_id: args.conversationId,
      client_message_id: crypto.randomUUID(),
    }),
  });
  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body?.error?.code ?? `http_${res.status}`, body?.error?.message ?? "Request failed.");
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const { frames, rest } = splitFrames(buffer);
    buffer = rest;
    for (const frame of frames) {
      const parsed = parseFrame(frame);
      if (parsed) onEvent({ type: parsed.event, ...(parsed.data as object) } as StreamEvent);
    }
  }
}

export const verifyApplicant =(applicationId: string, registeredEmail: string) =>
  request<VerifyResponse>("/api/demo/applicant/verify", {
    method: "POST",
    body: JSON.stringify({ application_id: applicationId, registered_email: registeredEmail }),
  });

/** A thumbs up/down on one answer. The server stores the rating and a fixed reason code against the answer id; never any text. */
export const sendFeedback = (args: { messageId: string; rating: FeedbackRating; reason?: FeedbackReason; modelMode?: ModelMode | null }) =>
  request<{ status: "recorded" | "updated" }>("/api/feedback", {
    method: "POST",
    body: JSON.stringify({ message_id: args.messageId, rating: args.rating, reason: args.reason ?? null, model_mode: args.modelMode ?? null }),
  });

