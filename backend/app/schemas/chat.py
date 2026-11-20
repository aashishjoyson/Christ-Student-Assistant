from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ModelModeLiteral = Literal["direct", "rag", "rag_peft"]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    model_mode: ModelModeLiteral = "rag"
    conversation_id: UUID | None = None  # omit on the first message; the server issues one
    client_message_id: str | None = Field(default=None, max_length=64)


class CitationOut(BaseModel):
    index: int
    source_name: str
    page: int | None = None
    section: str | None = None
    source_url: str | None = None
    chunk_id: str
    cited: bool


class HandledBy(BaseModel):
    kind: Literal["llm", "applicant_service", "helpdesk"]
    label: str
    mode: ModelModeLiteral | None = None
    provider: str | None = None
    model: str | None = None
    base_model_id: str | None = None
    adapter_id: str | None = None


class ActionResult(BaseModel):
    type: Literal["interview_email_resend", "verification"]
    status: Literal["sent", "simulated", "failed", "not_eligible", "verification_required"]
    masked_recipient: str | None = None
    reason: str | None = None


class Usage(BaseModel):
    latency_ms: int
    llm_called: bool = False
    input_tokens: int | None = None
    output_tokens: int | None = None
    est_cost_usd: float | None = None


class ChatResponse(BaseModel):
    conversation_id: UUID
    message_id: str
    answer: str
    intent: str
    model_mode_requested: ModelModeLiteral
    handled_by: HandledBy
    grounded: bool | None = None
    notice: str | None = None
    citations: list[CitationOut] = []
    action: ActionResult | None = None
    workflow_path: list[str] = []
    usage: Usage


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
