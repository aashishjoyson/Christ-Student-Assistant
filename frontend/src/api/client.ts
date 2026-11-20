import type { ChatResponse, Health, ModelMode, VerifyResponse } from "./types";

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

export const verifyApplicant = (applicationId: string, registeredEmail: string) =>
  request<VerifyResponse>("/api/demo/applicant/verify", {
    method: "POST",
    body: JSON.stringify({ application_id: applicationId, registered_email: registeredEmail }),
  });
