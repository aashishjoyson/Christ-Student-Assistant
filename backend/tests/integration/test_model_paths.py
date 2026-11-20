"""Required tests 1-4: routing and the three model boundaries."""

from tests.fakes import FakeChatClient, FakeRetriever
from tests.integration.conftest import Env


def test_model1_never_calls_retriever_and_flags_ungrounded(env: Env) -> None:
    r = env.chat("When do classes begin?", mode="direct")
    assert r.status_code == 200, r.text
    body = r.json()
    assert env.retriever.calls == []
    assert body["handled_by"]["label"] == "Model 1 - Direct LLM"
    assert body["grounded"] is False and body["citations"] == []
    assert body["notice"]
    assert body["workflow_path"] == ["classify_intent", "check_model_available", "direct_answer"]
    assert "Context passages" not in str(env.primary.calls[0])


def test_model2_calls_retriever_and_returns_citations(env: Env) -> None:
    r = env.chat("When do classes begin?", mode="rag")
    body = r.json()
    assert len(env.retriever.calls) == 1
    assert body["handled_by"]["label"] == "Model 2 - LLM + RAG"
    assert body["grounded"] is True
    assert body["citations"][0]["source_name"] == "SYNTHETIC_academic_calendar.md"
    assert body["citations"][0]["cited"] is True
    assert "Context passages" in env.primary.calls[0][-1]["content"]


def test_model1_and_model2_use_the_same_client(env: Env) -> None:
    env.chat("q1", mode="direct")
    env.chat("q2", mode="rag")
    assert len(env.primary.calls) == 2


def test_model3_not_configured_returns_503_and_calls_nothing(env: Env) -> None:
    r = env.chat("When do classes begin?", mode="rag_peft")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "model3_not_configured"
    assert env.primary.calls == []  # no silent fallback to Model 1/2
    assert env.retriever.calls == []


def test_model3_uses_peft_endpoint_with_same_evidence(make_env) -> None:  # type: ignore[no-untyped-def]
    model3 = FakeChatClient(provider="model3-endpoint", model="cu-helpdesk-lora", reply="Answer from adapter [1].")
    env = make_env(model3=model3, model3_base_model_id="Qwen/Qwen3-4B-Instruct-2507",
                   model3_adapter_id="demo/cu-helpdesk-lora@abc123")
    body = env.chat("When do classes begin?", mode="rag_peft").json()
    assert len(model3.calls) == 1 and env.primary.calls == []
    assert body["handled_by"]["adapter_id"] == "demo/cu-helpdesk-lora@abc123"
    assert body["handled_by"]["label"] == "Model 3 - LLM + RAG + PEFT"
    assert body["citations"]


def test_no_evidence_short_circuits_without_llm(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(retriever=FakeRetriever(chunks=[]))
    body = env.chat("What is the hostel curfew?", mode="rag").json()
    assert "could not find" in body["answer"].lower()
    assert env.primary.calls == [] and body["usage"]["llm_called"] is False


def test_not_indexed_is_reported_honestly(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(retriever=FakeRetriever(ready=False))
    body = env.chat("When do classes begin?", mode="rag").json()
    assert "no university documents have been indexed" in body["answer"].lower()
    assert body["grounded"] is False


def test_general_help_and_unsupported_use_no_llm(env: Env) -> None:
    help_body = env.chat("hi").json()
    assert help_body["handled_by"]["kind"] == "helpdesk"
    bad = env.chat("Can you change my grade in maths?").json()
    assert bad["intent"] == "unsupported"
    assert env.primary.calls == []


def test_conversation_history_is_kept_per_thread(env: Env) -> None:
    first = env.chat("When do classes begin?", mode="direct").json()
    env.chat("And when do they end?", mode="direct", conversation_id=first["conversation_id"])
    second_call = env.primary.calls[1]
    assert any(m["content"] == "When do classes begin?" for m in second_call)
