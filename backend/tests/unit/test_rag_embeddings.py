from types import SimpleNamespace

import pytest

from app.rag.embeddings import BATCH_SIZE, EmbeddingError, OpenAIEmbedder


class StubClient:
    """Stands in for openai.OpenAI(): returns vectors out of order to prove ordering is restored."""

    def __init__(self, fail_on_call: int | None = None) -> None:
        self.requests: list[list[str]] = []
        self.fail_on_call = fail_on_call
        self.embeddings = SimpleNamespace(create=self._create)

    def _create(self, model: str, input: list[str]):  # noqa: A002 - mirrors the SDK argument name
        self.requests.append(list(input))
        if self.fail_on_call == len(self.requests):
            raise RuntimeError(f"boom containing the text {input[0]!r}")
        data = [SimpleNamespace(index=i, embedding=[float(len(t)), 1.0]) for i, t in enumerate(input)]
        return SimpleNamespace(data=list(reversed(data)), usage=SimpleNamespace(total_tokens=len(input) * 10))


def test_requests_are_batched_ordered_and_usage_is_summed() -> None:
    client = StubClient()
    texts = [("x" * (i + 1)) for i in range(BATCH_SIZE * 2 + 5)]
    result = OpenAIEmbedder("k", "text-embedding-3-small", client=client).embed(texts)
    assert [len(r) for r in client.requests] == [BATCH_SIZE, BATCH_SIZE, 5]
    assert result.calls == 3 and result.tokens == len(texts) * 10
    assert [v[0] for v in result.vectors] == [float(i + 1) for i in range(len(texts))]  # order restored


def test_a_failing_request_raises_a_safe_error() -> None:
    client = StubClient(fail_on_call=1)
    with pytest.raises(EmbeddingError) as exc:
        OpenAIEmbedder("k", "m", client=client).embed(["very private sentence"])
    assert "private" not in str(exc.value) and "RuntimeError" in str(exc.value)


def test_no_texts_means_no_requests() -> None:
    client = StubClient()
    result = OpenAIEmbedder("k", "m", client=client).embed([])
    assert client.requests == [] and result.vectors == [] and result.calls == 0
