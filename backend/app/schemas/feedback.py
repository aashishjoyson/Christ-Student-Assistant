from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.chat import ModelModeLiteral

# A fixed list on purpose: free text could carry personal data, and a fixed list can be counted.
ReasonLiteral = Literal["wrong_answer", "not_helpful", "missing_source", "too_slow", "other"]


class FeedbackRequest(BaseModel):
    message_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    rating: Literal["up", "down"]
    reason: ReasonLiteral | None = None
    model_mode: ModelModeLiteral | None = None

    @model_validator(mode="after")
    def reason_only_with_down(self) -> FeedbackRequest:
        if self.reason is not None and self.rating != "down":
            raise ValueError("a reason can only be given with a thumbs down")
        return self


class FeedbackResponse(BaseModel):
    status: Literal["recorded", "updated"]
