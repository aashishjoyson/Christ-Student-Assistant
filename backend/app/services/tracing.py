"""Append-only JSONL request traces (always on; MLflow is optional and used for evaluation runs)."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from app.domain.redaction import redact


class TraceRecorder:
    def __init__(self, trace_dir: Path, include_text: bool = False) -> None:
        self._path = trace_dir / "requests.jsonl"
        self._include_text = include_text
        self._lock = threading.Lock()

    @property
    def include_text(self) -> bool:
        return self._include_text

    def record(self, trace: dict[str, Any]) -> None:
        line = json.dumps(redact(trace), default=str, ensure_ascii=False)
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
