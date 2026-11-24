"""Automatic ingestion: the poller runs on a schedule, never overlaps, backs off on failure and survives anything."""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.container import build_container
from app.graph.deps import GraphDeps
from app.main import create_app
from app.rag.ingest import SyncAlreadyRunning
from app.rag.poller import IngestionPoller
from tests.fakes import FakeChatClient, FakeRetriever, RecordingEmailProvider
from tests.integration.conftest import make_settings


class FakeService:
    def __init__(self, work_seconds: float = 0.0, outcomes: list | None = None) -> None:
        self.calls = 0
        self.triggers: list[str] = []
        self.running = 0
        self.max_running = 0
        self.work = work_seconds
        self.outcomes = outcomes or []
        self._guard = threading.Lock()

    def sync(self, trigger: str = "manual"):  # type: ignore[no-untyped-def]
        with self._guard:
            self.calls += 1
            self.running += 1
            self.max_running = max(self.max_running, self.running)
            outcome = self.outcomes[min(self.calls - 1, len(self.outcomes) - 1)] if self.outcomes else "ok"
        self.triggers.append(trigger)
        time.sleep(self.work)
        with self._guard:
            self.running -= 1
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(status="failed" if outcome == "failed" else "succeeded", error="boom" if outcome == "failed" else None)


async def _run_for(poller: IngestionPoller, seconds: float) -> None:
    poller.start()
    await asyncio.sleep(seconds)
    await poller.stop()


def test_it_runs_repeatedly_and_reports_its_state() -> None:
    service = FakeService()
    poller = IngestionPoller(service, 0.1, first_delay_seconds=0.0)
    asyncio.run(_run_for(poller, 0.9))
    assert service.calls >= 3 and set(service.triggers) == {"poll"}
    d = poller.describe()
    assert d["runs"] == service.calls and d["last_status"] == "succeeded" and d["consecutive_failures"] == 0
    assert d["last_started_at"] and d["last_finished_at"] and d["enabled"] is False  # stopped


def test_runs_never_overlap_even_when_a_sync_takes_longer_than_the_interval() -> None:
    service = FakeService(work_seconds=0.3)
    asyncio.run(_run_for(IngestionPoller(service, 0.05, first_delay_seconds=0.0), 1.3))
    assert service.calls >= 2 and service.max_running == 1


def test_a_failing_source_backs_off_exponentially_up_to_a_cap() -> None:
    poller = IngestionPoller(FakeService(), 10, max_backoff_seconds=100)
    assert poller.next_delay() == 10
    poller.consecutive_failures = 1
    assert poller.next_delay() == 20
    poller.consecutive_failures = 3
    assert poller.next_delay() == 80
    poller.consecutive_failures = 9
    assert poller.next_delay() == 100  # capped


def test_it_survives_exceptions_and_counts_failures_then_recovers() -> None:
    service = FakeService(outcomes=[RuntimeError("drive exploded"), "failed", "ok"])
    poller = IngestionPoller(service, 10)

    async def three_runs() -> None:
        for _ in range(3):
            await poller._once()  # noqa: SLF001 - driving the loop body directly keeps the test instant

    asyncio.run(three_runs())
    assert poller.runs == 3 and service.calls == 3
    assert poller.consecutive_failures == 0 and poller.last_status == "succeeded"  # recovered
    asyncio.run(poller._once())  # noqa: SLF001 - and a raised error is recorded, not propagated


def test_failures_are_recorded_with_a_safe_message() -> None:
    poller = IngestionPoller(FakeService(outcomes=[RuntimeError("drive exploded")]), 10)
    asyncio.run(poller._once())  # noqa: SLF001
    assert poller.consecutive_failures == 1 and poller.last_status == "error" and "RuntimeError" in poller.last_error


def test_a_manual_sync_in_progress_is_not_a_failure() -> None:
    poller = IngestionPoller(FakeService(outcomes=[SyncAlreadyRunning("busy")]), 10)
    asyncio.run(poller._once())  # noqa: SLF001
    assert poller.last_status == "skipped_busy" and poller.consecutive_failures == 0


def test_the_app_starts_the_poller_with_the_api_and_stops_it_on_shutdown(tmp_path: Path) -> None:
    service = FakeService()
    poller = IngestionPoller(service, 0.1, first_delay_seconds=0.0)
    settings = make_settings(tmp_path)
    from app.db.session import make_engine, make_session_factory

    deps = GraphDeps(settings=settings, session_factory=make_session_factory(make_engine(settings.database_url)),
                     primary_llm=FakeChatClient(), model3_llm=None, retriever=FakeRetriever(), email_provider=RecordingEmailProvider())
    container = build_container(settings, deps_override=deps, pollers_override=[poller])
    with TestClient(create_app(container)) as client:
        deadline = time.time() + 5
        while poller.runs < 2 and time.time() < deadline:
            time.sleep(0.05)
        assert poller.runs >= 2  # it started by itself, with no request
        status = client.get("/api/admin/drive/status", headers={"X-Admin-Key": "test-admin-key"}).json()
        assert status["pollers"][0]["name"] == "drive" and status["pollers"][0]["last_status"] == "succeeded"
        assert status["pollers"][0]["enabled"] is True
    assert poller.describe()["enabled"] is False  # stopped cleanly when the app shut down
