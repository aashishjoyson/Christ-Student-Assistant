from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.domain.clock import utcnow
from app.llm.base import ChatClient
from app.rag.base import Retriever
from app.services.email.base import EmailProvider


@dataclass
class GraphDeps:
    """Everything the nodes need, injected once. Tests pass fakes here."""

    settings: Settings
    session_factory: sessionmaker[Session]
    primary_llm: ChatClient | None  # Models 1 and 2 (same client)
    model3_llm: ChatClient | None  # Model 3 (LoRA endpoint); None = not configured
    retriever: Retriever
    email_provider: EmailProvider
    now: Callable[[], datetime] = field(default=utcnow)
