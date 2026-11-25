"""The ready-made demo logins offered in the chat: synthetic records only, real inboxes never shown in full, honest about what a resend will do."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models import Applicant
from app.db.seed import set_demo_email
from tests.fakes_smtp import make_provider
from tests.integration.conftest import Env

URL = "/api/demo/applicant/examples"


def by_id(env: Env) -> dict[str, dict]:
    response = env.client.get(URL)
    assert response.status_code == 200
    return {row["application_id"]: row for row in response.json()}


def test_every_synthetic_applicant_is_listed_with_a_scenario_and_what_to_ask(env: Env) -> None:
    rows = by_id(env)
    assert len(rows) == 10 and rows["CUAPP-DEMO-0001"]["scenario"] == "Interview scheduled, interview scheduled (online)"
    assert rows["CUAPP-DEMO-0003"]["scenario"] == "Under review, no interview"
    assert "I have not received my interview email" in rows["CUAPP-DEMO-0001"]["suggestions"]
    assert "I have not received my interview email" not in rows["CUAPP-DEMO-0003"]["suggestions"]


def test_synthetic_example_addresses_are_prefilled_so_the_demo_login_is_one_click(env: Env) -> None:
    row = by_id(env)["CUAPP-DEMO-0001"]
    assert row["email_prefill"] == "aarav.demo@example.com" and row["real_inbox"] is False


def test_a_real_inbox_is_never_shown_in_full(env: Env) -> None:
    assert set_demo_email(env.container.engine, "someone.real@gmail.com") is True
    response = env.client.get(URL)
    row = {r["application_id"]: r for r in response.json()}["CUAPP-DEMO-0001"]
    assert row["email_prefill"] is None and row["real_inbox"] is True and row["email_hint"] == "s**********l@gmail.com"
    assert "someone.real@gmail.com" not in response.text


def test_the_outcome_of_a_resend_follows_the_email_settings(make_env: Callable[..., Env]) -> None:
    simulated = by_id(make_env())
    assert simulated["CUAPP-DEMO-0001"]["resend_outcome"].startswith("Simulated")
    assert simulated["CUAPP-DEMO-0003"]["resend_outcome"].startswith("Refused: there is no interview")
    assert simulated["CUAPP-DEMO-0005"]["resend_outcome"].startswith("Refused: the interview is not active")

    provider, _ = make_provider()
    real = by_id(make_env(email=provider, email_provider="smtp", email_send_enabled=True, email_recipient_allowlist="aarav.demo@example.com"))
    assert real["CUAPP-DEMO-0001"]["resend_outcome"].startswith("A real email is sent")
    assert real["CUAPP-DEMO-0002"]["resend_outcome"].startswith("Refused: this address is not on the email allowlist")


def test_a_non_synthetic_record_is_never_listed(env: Env) -> None:
    with Session(env.container.engine) as session:
        session.add(Applicant(application_id="CUAPP-REAL-0001", full_name="Real Person", registered_email="real@university.example",
                              programme="p", is_synthetic=False, created_at=datetime(2026, 1, 1, tzinfo=UTC)))
        session.commit()
    assert "CUAPP-REAL-0001" not in by_id(env)


def test_the_list_is_off_in_production(make_env: Callable[..., Env]) -> None:
    env = make_env(app_env="production")
    assert env.client.get(URL).status_code == 404
