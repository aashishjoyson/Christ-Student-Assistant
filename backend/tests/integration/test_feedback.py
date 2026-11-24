"""Thumbs up/down: stored by answer id, one rating per answer, fixed reason codes only, rate limited, and never any message text."""

from __future__ import annotations

from sqlalchemy import select

from app.db.models import Feedback
from app.db.repositories.feedback import feedback_summary


def rows(env) -> list[Feedback]:  # type: ignore[no-untyped-def]
    with env.container.session_factory() as session:
        return list(session.execute(select(Feedback).order_by(Feedback.id)).scalars())


def test_a_rating_is_stored_against_the_answer_id_the_chat_returned(env) -> None:  # type: ignore[no-untyped-def]
    answer = env.chat("When do classes begin?").json()
    r = env.client.post("/api/feedback", json={"message_id": answer["message_id"], "rating": "up", "model_mode": "rag"})
    assert r.status_code == 200 and r.json() == {"status": "recorded"}
    [row] = rows(env)
    assert (row.message_id, row.rating, row.reason, row.model_mode) == (answer["message_id"], "up", None, "rag")


def test_rating_again_changes_the_rating_instead_of_adding_one(env) -> None:  # type: ignore[no-untyped-def]
    body = {"message_id": "abc123", "rating": "down", "reason": "wrong_answer", "model_mode": "direct"}
    assert env.client.post("/api/feedback", json=body).json() == {"status": "recorded"}
    assert env.client.post("/api/feedback", json={**body, "rating": "up", "reason": None}).json() == {"status": "updated"}
    [row] = rows(env)
    assert row.rating == "up" and row.reason is None  # a reason only belongs to a thumbs down


def test_a_thumbs_down_keeps_a_fixed_reason_code(env) -> None:  # type: ignore[no-untyped-def]
    env.client.post("/api/feedback", json={"message_id": "m1", "rating": "down", "reason": "missing_source"})
    [row] = rows(env)
    assert (row.rating, row.reason) == ("down", "missing_source")


def test_invalid_ratings_are_rejected_and_nothing_is_stored(env) -> None:  # type: ignore[no-untyped-def]
    bad = [
        {"message_id": "m", "rating": "meh"},
        {"message_id": "m", "rating": "up", "reason": "wrong_answer"},  # a reason only with a thumbs down
        {"message_id": "m", "rating": "down", "reason": "My email is a@b.com and it was rude"},  # free text is not accepted
        {"message_id": "has space", "rating": "up"},
        {"message_id": "x" * 65, "rating": "up"},
        {"message_id": "m", "rating": "up", "model_mode": "gpt"},
        {"rating": "up"},
    ]
    assert [env.client.post("/api/feedback", json=b).status_code for b in bad] == [422] * len(bad)
    assert rows(env) == []


def test_a_flood_from_one_client_is_limited(env) -> None:  # type: ignore[no-untyped-def]
    codes = [env.client.post("/api/feedback", json={"message_id": f"m{i}", "rating": "up"}).status_code for i in range(65)]
    assert codes[:60] == [200] * 60 and set(codes[60:]) == {429}
    assert len(rows(env)) == 60


def test_the_summary_counts_votes_by_reason_and_mode(env) -> None:  # type: ignore[no-untyped-def]
    for i, (rating, reason, mode) in enumerate([("up", None, "rag"), ("down", "wrong_answer", "rag"), ("down", "wrong_answer", "direct"), ("down", None, "rag")]):
        env.client.post("/api/feedback", json={"message_id": f"m{i}", "rating": rating, "reason": reason, "model_mode": mode})
    with env.container.session_factory() as session:
        from app.db.repositories.feedback import feedback_rows
        summary = feedback_summary(feedback_rows(session))
    assert summary["votes"] == 4 and summary["up"] == 1 and summary["down"] == 3
    assert summary["down_reasons"] == {"wrong_answer": 2, "none": 1}
    assert summary["by_mode"] == {"rag:up": 1, "rag:down": 2, "direct:down": 1}


def test_the_retrieval_distance_is_recorded_in_the_trace_without_any_text(make_env, tmp_path) -> None:  # type: ignore[no-untyped-def]
    import json

    env = make_env()
    env.chat("When do classes begin?")
    trace = [json.loads(line) for line in (env.settings.trace_dir / "requests.jsonl").read_text(encoding="utf-8").splitlines()][-1]
    assert trace["retrieval"]["best_distance"] == 0.2 and trace["retrieval"]["top_k"] == env.settings.rag_top_k
    assert "question" not in trace and "answer" not in trace
