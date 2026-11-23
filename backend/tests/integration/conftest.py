"""Integration fixtures: real SQLite (temp file), real LangGraph, fake LLMs/retriever/email."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.container import AppContainer, build_container
from app.core.config import REPO_ROOT, Settings
from app.db.seed import reset_and_seed
from app.db.session import make_engine, make_session_factory
from app.domain.tokens import issue_token
from app.graph.deps import GraphDeps
from app.main import create_app
from tests.fakes import FakeChatClient, FakeRetriever, RecordingEmailProvider

SEED_NOW = datetime(2026, 11, 20, 4, 0, tzinfo=UTC)
SECRET = "integration-test-secret"


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now = self.now + timedelta(**kwargs)


@dataclass
class Env:
    settings: Settings
    container: AppContainer
    client: TestClient
    primary: FakeChatClient
    model3: FakeChatClient | None
    retriever: FakeRetriever
    email: RecordingEmailProvider
    clock: Clock

    def token_for(self, application_id: str) -> str:
        from sqlalchemy import select

        from app.db.models import Applicant

        with self.container.session_factory() as s:
            applicant = s.execute(select(Applicant).where(Applicant.application_id == application_id)).scalar_one()
        token, _ = issue_token(applicant.id, SECRET.encode(), timedelta(minutes=30), self.clock.now)
        return token

    def chat(self, message: str, mode: str = "rag", token: str | None = None, conversation_id: str | None = None):
        headers = {"X-Applicant-Session": token} if token else {}
        body: dict[str, object] = {"message": message, "model_mode": mode}
        if conversation_id:
            body["conversation_id"] = conversation_id
        return self.client.post("/api/chat", json=body, headers=headers)


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    base: dict[str, object] = {
        "app_env": "test",
        "app_secret_key": SECRET,
        "database_url": f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        "trace_dir": tmp_path / "traces",
        "outbox_dir": tmp_path / "outbox",
        "openai_api_key": "test-key-not-real",
        "openai_chat_model": "fake-model",
        "admin_api_key": "test-admin-key",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


@pytest.fixture
def make_env(tmp_path: Path) -> Iterator[Callable[..., Env]]:
    clients: list[TestClient] = []

    def _make(
        *,
        model3: FakeChatClient | None = None,
        retriever: FakeRetriever | None = None,
        email: RecordingEmailProvider | None = None,
        primary: FakeChatClient | None = None,
        **setting_overrides: object,
    ) -> Env:
        settings = make_settings(tmp_path, **setting_overrides)
        engine = make_engine(settings.database_url)
        reset_and_seed(engine, REPO_ROOT / "data" / "synthetic_applicants.csv", settings.app_timezone, SEED_NOW)
        clock = Clock(SEED_NOW + timedelta(hours=1))
        deps = GraphDeps(
            settings=settings,
            session_factory=make_session_factory(engine),
            primary_llm=primary or FakeChatClient(),
            model3_llm=model3,
            retriever=retriever or FakeRetriever(),
            email_provider=email or RecordingEmailProvider(),
            now=clock,
        )
        container = build_container(settings, deps_override=deps)
        client = TestClient(create_app(container))
        client.__enter__()
        clients.append(client)
        return Env(settings, container, client, deps.primary_llm, model3, deps.retriever, deps.email_provider, clock)  # type: ignore[arg-type]

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def env(make_env: Callable[..., Env]) -> Env:
    return make_env()
