"""Adversarial suite (Phase 7.3): every structural case runs through the real app with fakes. No network, no paid API.

Dataset: data/eval/adversarial.jsonl. Cases with layer "model" need a real LLM and are skipped here.
Set ADVERSARIAL_RESULTS_JSON=<path> to also write a results file for the Evidently report (scripts/evidently_report.py).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from app.core.config import REPO_ROOT
from app.db.models import Applicant
from app.domain.documents import RetrievedChunk
from app.domain.prompts import DIRECT_SYSTEM_PROMPT, RAG_SYSTEM_PROMPT
from app.domain.tokens import issue_token
from app.eval.adversarial import AdversarialCase, Observation, check_case, load_cases, parse_token_spec
from tests.fakes import FakeRetriever
from tests.integration.conftest import SECRET, Env

CASES_PATH = REPO_ROOT / "data" / "eval" / "adversarial.jsonl"
STRUCTURAL = [c for c in load_cases(CASES_PATH) if c.layer == "structural"]
SECRETS = (SECRET, "test-admin-key", "test-key-not-real")
RESULTS: list[dict[str, str]] = []


@pytest.fixture(scope="module", autouse=True)
def _write_results() -> Iterator[None]:
    yield
    target = os.environ.get("ADVERSARIAL_RESULTS_JSON")
    if target:
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        Path(target).write_text(json.dumps(RESULTS, indent=1), encoding="utf-8")


def _applicant_db_id(env: Env, application_id: str) -> int:
    with env.container.session_factory() as s:
        return s.execute(select(Applicant.id).where(Applicant.application_id == application_id)).scalar_one()


def _token(env: Env, spec: str | None) -> str | None:
    kind, application_id = parse_token_spec(spec)
    if kind is None:
        return None
    if kind == "garbage":
        return "not.a-real-token"
    if kind == "unknown_applicant":  # correctly signed, but no such applicant
        return issue_token(9999, SECRET.encode(), timedelta(minutes=30), env.clock.now)[0]
    assert application_id
    if kind == "valid":
        return env.token_for(application_id)
    if kind == "expired":
        return issue_token(_applicant_db_id(env, application_id), SECRET.encode(), timedelta(minutes=30),
                           env.clock.now - timedelta(hours=2))[0]
    good = env.token_for(application_id)  # tampered: flip the last signature character
    return good[:-1] + ("A" if good[-1] != "A" else "B")


def _applicant_count(env: Env) -> int:
    with env.container.session_factory() as s:
        return s.execute(select(func.count()).select_from(Applicant)).scalar_one()


def _run(env: Env, case: AdversarialCase) -> Observation:
    before = _applicant_count(env)
    token = _token(env, case.token)
    response = None
    for _ in range(case.repeat):
        if case.kind == "verify":
            response = env.client.post("/api/demo/applicant/verify", json=case.payload)
        else:
            response = env.chat(case.full_message(), mode=case.mode, token=token)
    assert response is not None
    try:
        body: dict[str, Any] | None = response.json()
    except ValueError:
        body = None
    calls = list(env.primary.calls) + (list(env.model3.calls) if env.model3 else [])
    return Observation(
        status_code=response.status_code,
        body=body if isinstance(body, dict) else None,
        llm_calls=calls,
        emails_sent_to=[e.to for e in env.email.sent],
        applicants_before=before,
        applicants_after=_applicant_count(env),
        retriever_calls=len(env.retriever.calls),
        secrets=SECRETS,
        expected_system_prompt=DIRECT_SYSTEM_PROMPT if case.mode == "direct" else RAG_SYSTEM_PROMPT,
    )


def _params() -> Iterator[Any]:
    for case in STRUCTURAL:
        marks = []
        if case.expect.get("known_gap"):
            marks.append(pytest.mark.xfail(strict=True, reason=case.expect["known_gap"]))
        yield pytest.param(case, id=case.id, marks=marks)


@pytest.mark.parametrize("case", list(_params()))
def test_adversarial_case(case: AdversarialCase, make_env: Callable[..., Env]) -> None:
    kwargs: dict[str, Any] = {}
    if case.retriever_chunks:
        kwargs["retriever"] = FakeRetriever(chunks=[
            RetrievedChunk(f"poison:v1:{i:04d}", text, "SYNTHETIC_poisoned.md", "poison", section="Test", distance=0.1)
            for i, text in enumerate(case.retriever_chunks)
        ])
    env = make_env(**kwargs)
    failures = check_case(case, _run(env, case))
    known_gap = bool(case.expect.get("known_gap"))
    RESULTS.append({
        "id": case.id,
        "category": case.category,
        "severity": case.severity,
        "layer": case.layer,
        "passed": "no" if failures else "yes",
        "known_gap": "yes" if known_gap else "no",
        "critical_breach": "yes" if failures and case.severity == "critical" and not known_gap else "no",
        "failures": "; ".join(failures),
    })
    assert not failures, "; ".join(failures)


def test_suite_covers_the_required_categories() -> None:
    """Guard against the dataset quietly losing a category."""
    categories = {c.category for c in STRUCTURAL}
    required = {"prompt_injection", "identity_bypass", "cross_applicant", "email_redirection", "email_flooding",
                "injection_string", "edge_input", "poisoned_context", "model_substitution", "disclaimer_removal"}
    assert required <= categories, required - categories
    assert sum(c.severity == "critical" for c in STRUCTURAL) >= 25
