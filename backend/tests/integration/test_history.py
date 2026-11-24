"""Opt-in conversation memory that survives a restart (CHAT_HISTORY_PERSIST), and what it must never keep."""

from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import select, update

from app.container import build_container
from app.db.models import ConversationHistory
from app.domain.clock import utcnow
from app.graph.state import APPLICANT_HISTORY_PLACEHOLDER
from app.schemas.chat import ChatRequest
from app.services.history_store import HistoryStore


def restart(env):  # type: ignore[no-untyped-def]
    """A new container on the same database and the same fakes: a new graph with an empty in-memory checkpointer, as after a server restart."""
    return build_container(env.settings, deps_override=env.container.deps)


def contents(env, conversation_id: str) -> list[str]:  # type: ignore[no-untyped-def]
    with env.container.session_factory() as session:
        row = session.execute(select(ConversationHistory).where(ConversationHistory.conversation_id == conversation_id)).scalar_one_or_none()
    return [t["content"] for t in json.loads(row.turns)] if row else []


def sent_to_the_model(env) -> str:  # type: ignore[no-untyped-def]
    return json.dumps(env.primary.calls[-1])


def test_a_conversation_continues_after_a_restart_when_memory_is_persistent(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(chat_history_persist=True)
    cid = env.chat("What attendance do I need for the mid semester exam?").json()["conversation_id"]
    after = restart(env)
    after.chat_service.handle(ChatRequest(message="And what about the end semester one?", conversation_id=cid, model_mode="rag"), None)
    assert "attendance do I need for the mid semester" in sent_to_the_model(env)  # the model still saw the earlier question


def test_without_persistence_a_restart_forgets_the_conversation(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()  # the default
    cid = env.chat("What attendance do I need for the mid semester exam?").json()["conversation_id"]
    restart(env).chat_service.handle(ChatRequest(message="And what about the end semester one?", conversation_id=cid, model_mode="rag"), None)
    assert "attendance do I need for the mid semester" not in sent_to_the_model(env)
    assert contents(env, cid) == []  # and nothing was written down


def test_memory_inside_one_running_server_does_not_read_the_database_again(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(chat_history_persist=True)
    cid = env.chat("first question about fees").json()["conversation_id"]
    env.chat("second question about hostels", conversation_id=cid)
    stored = contents(env, cid)
    assert sum("first question" in c for c in stored) == 1 and sum("second question" in c for c in stored) == 1  # not duplicated by rehydration


def test_streamed_turns_are_remembered_too(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(chat_history_persist=True)
    events = list(env.container.chat_service.stream(ChatRequest(message="a streamed question about libraries", model_mode="rag"), None))
    cid = events[-1]["response"]["conversation_id"]
    assert any("streamed question about libraries" in c for c in contents(env, cid))


def test_an_applicants_details_are_never_stored(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(chat_history_persist=True)
    token = env.token_for("CUAPP-DEMO-0001")
    answer = env.chat("When is my interview?", token=token).json()
    assert "meet.example.com" in answer["answer"]  # the visitor sees their own details
    stored = " ".join(contents(env, answer["conversation_id"]))
    assert "meet.example.com" not in stored and "Aarav" not in stored and APPLICANT_HISTORY_PLACEHOLDER in stored


def test_emails_a_visitor_types_are_masked_before_storage(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(chat_history_persist=True)
    cid = env.chat("My email is student.person@example.com, what is the library fine?").json()["conversation_id"]
    stored = " ".join(contents(env, cid))
    assert "student.person@example.com" not in stored and "library fine" in stored


def test_a_broken_database_never_breaks_a_chat_turn() -> None:
    def broken():  # type: ignore[no-untyped-def]
        raise RuntimeError("database down")

    store = HistoryStore(broken)  # type: ignore[arg-type]
    assert store.load("c1") == []
    store.save("c1", [{"role": "user", "content": "x"}])  # must not raise


def test_a_conversation_can_be_forgotten(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(chat_history_persist=True)
    cid = env.chat("something I would rather not keep").json()["conversation_id"]
    assert contents(env, cid)
    assert env.client.delete(f"/api/chat/{cid}").json() == {"deleted": True}
    assert env.client.delete(f"/api/chat/{cid}").json() == {"deleted": False}  # forgetting twice is fine
    assert contents(env, cid) == []
    restart(env).chat_service.handle(ChatRequest(message="and now?", conversation_id=cid, model_mode="rag"), None)
    assert "rather not keep" not in sent_to_the_model(env)  # the restarted server has nothing to restore


def test_forgetting_works_with_persistence_off_and_rejects_a_bad_id(env) -> None:  # type: ignore[no-untyped-def]
    cid = env.chat("hello there").json()["conversation_id"]
    assert env.client.delete(f"/api/chat/{cid}").json() == {"deleted": False}
    assert env.client.delete("/api/chat/not-a-uuid").status_code == 422


def test_old_conversations_are_purged_by_the_retention_period(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(chat_history_persist=True)
    old = env.chat("an old conversation").json()["conversation_id"]
    new = env.chat("a recent conversation").json()["conversation_id"]
    with env.container.session_factory() as session:
        session.execute(update(ConversationHistory).where(ConversationHistory.conversation_id == old).values(updated_at=utcnow() - timedelta(days=40)))
        session.commit()
    assert HistoryStore(env.container.session_factory).purge(30) == 1
    assert contents(env, old) == [] and contents(env, new) != []
