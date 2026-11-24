"""Opt-in persistent conversation memory (CHAT_HISTORY_PERSIST). One row per conversation holding the most recent turns."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import ConversationHistory


def load_turns(session: Session, conversation_id: str) -> list[dict[str, str]]:
    row = session.execute(select(ConversationHistory).where(ConversationHistory.conversation_id == conversation_id)).scalar_one_or_none()
    if row is None:
        return []
    try:
        turns = json.loads(row.turns)
    except ValueError:
        return []
    return [{"role": str(t["role"]), "content": str(t["content"])} for t in turns if isinstance(t, dict) and "role" in t and "content" in t]


def save_turns(session: Session, conversation_id: str, turns: list[dict[str, str]], now: datetime) -> None:
    row = session.execute(select(ConversationHistory).where(ConversationHistory.conversation_id == conversation_id)).scalar_one_or_none()
    payload = json.dumps(turns, ensure_ascii=False)
    if row is None:
        session.add(ConversationHistory(conversation_id=conversation_id, turns=payload, updated_at=now))
    else:
        row.turns, row.updated_at = payload, now
    session.commit()


def delete_turns(session: Session, conversation_id: str) -> bool:
    deleted = session.execute(delete(ConversationHistory).where(ConversationHistory.conversation_id == conversation_id)).rowcount
    session.commit()
    return bool(deleted)


def purge_older_than(session: Session, cutoff: datetime) -> int:
    deleted = session.execute(delete(ConversationHistory).where(ConversationHistory.updated_at < cutoff)).rowcount
    session.commit()
    return int(deleted or 0)
