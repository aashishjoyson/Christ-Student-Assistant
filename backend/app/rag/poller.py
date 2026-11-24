"""Automatic ingestion: run IngestionService.sync("poll") on a schedule inside the API process.

Source-agnostic (it only needs an object with .sync(trigger)). Guarantees: syncs never overlap (the service is single-flight
and the loop is sequential); a failing source backs off exponentially instead of hammering the API; the loop survives any error;
the state is exposed for the admin status page, so "how fresh is the index?" is a question the system can answer.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, timedelta
from typing import Any, Protocol

from app.domain.clock import utcnow
from app.rag.ingest import SyncAlreadyRunning

log = logging.getLogger("rag.poller")


class Syncable(Protocol):
    def sync(self, trigger: str = "manual") -> Any: ...


class IngestionPoller:
    def __init__(self, service: Syncable, interval_seconds: float, *, name: str = "drive", first_delay_seconds: float = 3.0,
                 max_backoff_seconds: float = 3600) -> None:
        self._service = service
        self._interval = max(0.05, float(interval_seconds))
        self._first_delay = first_delay_seconds
        self._max_backoff = float(max_backoff_seconds)
        self._task: asyncio.Task[None] | None = None
        self.name = name
        self.runs = 0
        self.consecutive_failures = 0
        self.last_started_at: datetime | None = None
        self.last_finished_at: datetime | None = None
        self.last_status: str | None = None
        self.last_error: str | None = None
        self.next_run_at: datetime | None = None

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> asyncio.Task[None]:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._run(), name=f"ingestion-poller-{self.name}")
        return self._task

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    def describe(self) -> dict[str, object]:
        iso = lambda d: d.isoformat() if d else None  # noqa: E731
        return {
            "name": self.name, "enabled": self._task is not None and not self._task.done(), "interval_seconds": self._interval,
            "runs": self.runs, "consecutive_failures": self.consecutive_failures, "last_status": self.last_status,
            "last_error": self.last_error, "last_started_at": iso(self.last_started_at),
            "last_finished_at": iso(self.last_finished_at), "next_run_at": iso(self.next_run_at),
        }

    # ------------------------------------------------------------------ loop
    async def _run(self) -> None:
        await asyncio.sleep(self._first_delay)  # let the API finish starting up first
        while True:
            await self._once()
            delay = self.next_delay()
            self.next_run_at = utcnow() + timedelta(seconds=delay)
            await asyncio.sleep(delay)

    def next_delay(self) -> float:
        """Seconds until the next run: the interval, or exponential backoff (capped) while the source keeps failing."""
        if self.consecutive_failures == 0:
            return float(self._interval)
        return float(min(self._interval * 2 ** self.consecutive_failures, self._max_backoff))

    async def _once(self) -> None:
        self.last_started_at = utcnow()
        self.runs += 1
        try:
            result = await asyncio.to_thread(self._service.sync, "poll")  # blocking work stays off the event loop
        except SyncAlreadyRunning:
            self.last_status, self.last_error = "skipped_busy", None  # a manual sync is running: not a failure
        except Exception as exc:  # the loop must survive anything
            self.consecutive_failures += 1
            self.last_status, self.last_error = "error", f"{type(exc).__name__}: {str(exc)[:200]}"
            log.warning("poll sync raised %s", type(exc).__name__)
        else:
            status = getattr(result, "status", "unknown")
            self.last_status = status
            self.last_error = getattr(result, "error", None)
            self.consecutive_failures = self.consecutive_failures + 1 if status == "failed" else 0
            if status != "succeeded":
                log.warning("poll sync finished with status %s", status)
        self.last_finished_at = utcnow()
