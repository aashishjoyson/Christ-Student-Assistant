"""Shared test setup."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.core import flow


@pytest.fixture(autouse=True)
def _no_flow_bus_leaks_between_tests() -> Iterator[None]:
    """The live-flow bus is process-wide (the container installs it); never let one test's bus leak into the next."""
    yield
    flow.install(None)
