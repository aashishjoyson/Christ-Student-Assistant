"""Settings that protect an external service from a typo."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_the_drive_polling_interval_has_a_floor_and_a_sane_default() -> None:
    assert Settings(_env_file=None).drive_sync_interval_seconds == 300
    assert Settings(_env_file=None, drive_sync_interval_seconds=15).drive_sync_interval_seconds == 15
    with pytest.raises(ValidationError):
        Settings(_env_file=None, drive_sync_interval_seconds=1)
