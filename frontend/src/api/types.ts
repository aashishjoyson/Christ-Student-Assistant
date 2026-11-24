// Mirrors backend/app/schemas/*.py. Keep in sync when the API contract changes.

export type ModelMode = "direct" | "rag" | "rag_peft";

export const MODE_LABELS: Record<ModelMode, string> = {
  direct: "Model 1 - Direct LLM",
  rag: "Model 2 - LLM + RAG",
  rag_peft: "Model 3 - LLM + RAG + PEFT",
};

export interface Citation {
  index: number;
  source_name: string;
  page: number | null;
  section: string | null;
  source_url: string | null;
  chunk_id: string;
  cited: boolean;
}

export interface HandledBy {
  kind: "llm" | "applicant_service" | "helpdesk";
  label: string;
  mode?: ModelMode | null;
  provider?: string | null;
  model?: string | null;
  base_model_id?: string | null;
  adapter_id?: string | null;
}

export interface ActionResult {
  type: "interview_email_resend" | "verification";
  status: "sent" | "simulated" | "failed" | "not_eligible" | "verification_required";
  masked_recipient?: string | null;
  reason?: string | null;
}

export interface ChatResponse {
  conversation_id: string;
  message_id: string;
  answer: string;
  intent: string;
  model_mode_requested: ModelMode;
  handled_by: HandledBy;
  grounded: boolean | null;
  notice: string | null;
  citations: Citation[];
  action: ActionResult | null;
  workflow_path: string[];
  usage: {
    latency_ms: number;
    first_token_ms?: number | null;
    llm_called: boolean;
    intent_llm_called?: boolean;
    condense_llm_called?: boolean;
    input_tokens?: number | null;
    output_tokens?: number | null;
  };
}

export interface ModelStatus {
  label: string;
  configured: boolean;
  provider?: string | null;
  model?: string | null;
  base_model_id?: string | null;
  adapter_id?: string | null;
  retrieval: boolean;
}

export interface Health {
  status: string;
  version: string;
  models: Record<ModelMode, ModelStatus>;
  retriever: Record<string, unknown>;
  email: { provider: string; send_enabled: boolean };
}

export interface VerifyResponse {
  verified: boolean;
  session_token: string;
  expires_at: string;
  applicant: { application_id: string; first_name: string; masked_email: string; programme: string };
}

// Events of POST /api/chat/stream (Server-Sent Events): start -> delta* -> final, or error.
export type StreamEvent =
  | { type: "start"; handled_by: HandledBy; notice?: string | null }
  | { type: "delta"; text: string }
  | { type: "final"; response: ChatResponse }
  | { type: "error"; code: string; message: string };

export type FeedbackRating = "up" | "down";
export type FeedbackReason = "wrong_answer" | "not_helpful" | "missing_source" | "too_slow" | "other";
