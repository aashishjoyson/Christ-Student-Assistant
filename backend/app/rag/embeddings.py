"""Embedding interface and the OpenAI implementation (batched, usage recorded)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

BATCH_SIZE = 100  # inputs per API request


class EmbeddingError(Exception):
    """An embedding request failed. The message is safe to store and show (no text content)."""


@dataclass(frozen=True)
class EmbedResult:
    vectors: list[list[float]]
    tokens: int  # tokens billed (0 when the provider does not report usage)
    calls: int  # API requests made


class Embedder(Protocol):
    model: str

    def embed(self, texts: Sequence[str]) -> EmbedResult: ...


class OpenAIEmbedder:
    """OpenAI embeddings through the same SDK the chat client uses. `client` is injectable for tests."""

    def __init__(self, api_key: str, model: str, *, timeout: float = 30.0, max_retries: int = 2, client: Any = None) -> None:
        self.model = model
        if client is None:
            from openai import OpenAI

            client = OpenAI(api_key=api_key, timeout=timeout, max_retries=max_retries)
        self._client = client

    def embed(self, texts: Sequence[str]) -> EmbedResult:
        vectors: list[list[float]] = []
        tokens = calls = 0
        for start in range(0, len(texts), BATCH_SIZE):
            batch = list(texts[start : start + BATCH_SIZE])
            try:
                response = self._client.embeddings.create(model=self.model, input=batch)
            except Exception as exc:  # SDK errors vary by version; keep the message free of request content
                raise EmbeddingError(f"embedding request failed ({type(exc).__name__})") from exc
            calls += 1
            data = sorted(response.data, key=lambda item: item.index)
            if len(data) != len(batch):
                raise EmbeddingError("embedding response had the wrong number of vectors")
            vectors.extend(list(item.embedding) for item in data)
            usage = getattr(response, "usage", None)
            tokens += int(getattr(usage, "total_tokens", 0) or 0)
        return EmbedResult(vectors=vectors, tokens=tokens, calls=calls)
