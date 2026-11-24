"""Name parity through the real graph (Phase 7.6): the applicant's name must never change what the system does."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.integration.conftest import Env

NAMES = ["Aarav Sharma", "Fatima Khan", "Joseph Thomas", "Zhang Wei", "Lakshmi Iyer", "Mohammed Ali", "Gurpreet Singh",
         "Oluwaseun Adeyemi"]
REQUESTS = {
    "resend": "I have not received my interview email.",
    "interview": "When is my interview?",
    "status": "What is the status of my application?",
}


def _shape(body: dict) -> tuple:
    action = body.get("action") or {}
    return (body["intent"], body["handled_by"]["kind"], tuple(body["workflow_path"]), action.get("status"),
            action.get("reason"), body["answer"])


@pytest.mark.parametrize("family", list(REQUESTS))
def test_name_in_message_does_not_change_the_response(family: str, make_env: Callable[..., Env]) -> None:
    shapes = []
    for name in NAMES:
        env = make_env()  # fresh database each time so the resend cooldown cannot differ between names
        token = env.token_for("CUAPP-DEMO-0001")
        body = env.chat(f"Hi, I'm {name}. {REQUESTS[family]}", token=token).json()
        shapes.append(_shape(body))
        assert env.primary.calls == []  # applicant paths never call the LLM
    assert len(set(shapes)) == 1, f"responses differ by name: {set(shapes)}"
