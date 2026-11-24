"""Conversation memory that survives a restart (opt-in). The graph keeps history in memory per conversation; this stores the same turns in the
database and puts them back when the graph has never seen the conversation (after a restart). What is stored is what the graph already keeps
for the model: applicant-service answers are a placeholder, never their details. Emails and secret-looking values are masked before saving.
A storage problem never breaks a chat turn: it is logged and the turn goes on without memory."""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy.orm import Session, sessionmaker

from app.db.repositories.history import delete_turns, load_turns, purge_older_than, save_turns
from app.domain.clock import utcnow
from app.domain.redaction import redact_text

log = logging.getLogger("history")


class HistoryStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def load(self, conversation_id: str) -> list[dict[str, str]]:
        try:
            with self._session_factory() as session:
                return load_turns(session, conversation_id)
        except Exception:  # noqa: BLE001 - memory is a convenience; the turn must still be answered
            log.exception("could not load conversation history")
            return []

    def save(self, conversation_id: str, turns: list[dict[str, str]]) -> None:
        masked = [{"role": t["role"], "content": redact_text(t["content"])} for t in turns]
        try:
            with self._session_factory() as session:
                save_turns(session, conversation_id, masked, utcnow())
        except Exception:  # noqa: BLE001
            log.exception("could not save conversation history")

    def delete(self, conversation_id: str) -> bool:
        with self._session_factory() as session:
            return delete_turns(session, conversation_id)

    def purge(self, older_than_days: int) -> int:
        with self._session_factory() as session:
            return purge_older_than(session, utcnow() - timedelta(days=older_than_days))
