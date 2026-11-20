from __future__ import annotations

from pydantic import BaseModel


class ModelStatus(BaseModel):
    label: str
    configured: bool
    provider: str | None = None
    model: str | None = None
    base_model_id: str | None = None
    adapter_id: str | None = None
    retrieval: bool


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    models: dict[str, ModelStatus]
    retriever: dict[str, object]
    email: dict[str, object]
    drive: dict[str, object]
