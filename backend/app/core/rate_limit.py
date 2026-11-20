"""In-memory sliding-window rate limiter (single-process prototype).

Used to slow down guessing of application ID + email pairs on the verify endpoint.
State is lost on restart and not shared between workers - acceptable for a local demo,
documented as a production gap.
"""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta


class SlidingWindowLimiter:
    def __init__(self, max_attempts: int, window: timedelta) -> None:
        self.max_attempts = max_attempts
        self.window = window
        self._hits: dict[str, deque[datetime]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, now: datetime) -> bool:
        """Record an attempt. Returns False when the key is over its limit (attempt not recorded)."""
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] >= self.window:
                q.popleft()
            if len(q) >= self.max_attempts:
                return False
            q.append(now)
            return True

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)
