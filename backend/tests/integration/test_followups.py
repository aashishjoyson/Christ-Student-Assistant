"""Follow-up questions keep their context in RETRIEVAL too (found live: 'and for the mid semester ones?' searched for nothing)."""

from __future__ import annotations

import json
from collections.abc import Callable

from app.domain.contextualize import CONDENSE_SYSTEM_PROMPT
from tests.fakes import FakeChatClient, ScriptedChatClient
from tests.integration.conftest import Env

FIRST = "What is the minimum attendance required to appear for exams?"
FOLLOW_UP = "And what about the mid semester ones?"
STANDALONE = "What is the minimum attendance required for mid semester exams?"


def _condense_calls(env: Env) -> list:
    return [c for c in env.primary.calls if c[0]["content"] == CONDENSE_SYSTEM_PROMPT]


def _two_turns(env: Env, mode: str = "rag") -> dict:
    first = env.chat(FIRST, mode=mode).json()
    return env.chat(FOLLOW_UP, mode=mode, conversation_id=first["conversation_id"]).json()


def test_a_follow_up_is_searched_as_a_standalone_question(make_env: Callable[..., Env]) -> None:
    env = make_env(primary=ScriptedChatClient(condense_reply=STANDALONE))
    body = _two_turns(env)
    assert env.retriever.calls == [FIRST, STANDALONE]  # the first message is untouched; the follow-up was restated
    assert body["usage"]["condense_llm_called"] is True and body["grounded"] is True
    answer_call = [c for c in env.primary.calls if c[0]["content"] != CONDENSE_SYSTEM_PROMPT][-1]
    assert FOLLOW_UP in answer_call[-1]["content"]  # the answering model still sees what the student actually typed ...
    assert any(m["content"] == FIRST for m in answer_call)  # ... and the earlier conversation


def test_the_first_message_and_standalone_questions_make_no_extra_call(make_env: Callable[..., Env]) -> None:
    env = make_env(primary=ScriptedChatClient(condense_reply=STANDALONE))
    first = env.chat(FIRST).json()
    assert first["usage"]["condense_llm_called"] is False and _condense_calls(env) == []
    long_question = "Please explain in detail how the university evaluates internal assessment marks for postgraduate programmes in commerce"
    env.chat(long_question, conversation_id=first["conversation_id"])
    assert _condense_calls(env) == [] and env.retriever.calls[-1] == long_question


def test_if_the_rewriter_fails_a_deterministic_query_keeps_the_topic(make_env: Callable[..., Env]) -> None:
    env = make_env(primary=ScriptedChatClient(condense_reply="__error__"))
    body = _two_turns(env)
    assert body["answer"]  # the chat still works
    assert env.retriever.calls[-1] == f"{FIRST} {FOLLOW_UP}"  # previous question + this message


def test_models_2_and_3_retrieve_with_the_same_rewritten_query(make_env: Callable[..., Env]) -> None:
    queries = {}
    for mode in ("rag", "rag_peft"):
        model3 = FakeChatClient(provider="m3", model="adapter", reply="Answer [1].")
        env = make_env(primary=ScriptedChatClient(condense_reply=STANDALONE), model3=model3, model3_base_model_id="b",
                       model3_adapter_id="a", model3_base_url="http://x", model3_model="adapter")
        _two_turns(env, mode=mode)
        queries[mode] = list(env.retriever.calls)
    assert queries["rag"] == queries["rag_peft"] == [FIRST, STANDALONE]


def test_model_1_never_searches_or_rewrites(make_env: Callable[..., Env]) -> None:
    env = make_env(primary=ScriptedChatClient(condense_reply=STANDALONE))
    _two_turns(env, mode="direct")
    assert env.retriever.calls == [] and _condense_calls(env) == []


def test_the_rewrite_prompt_never_contains_applicant_details(make_env: Callable[..., Env]) -> None:
    env = make_env(primary=ScriptedChatClient(condense_reply=STANDALONE))
    token = env.token_for("CUAPP-DEMO-0001")
    first = env.chat("When is my interview?", token=token).json()  # an applicant-service answer enters the history as a placeholder
    env.chat(FIRST, conversation_id=first["conversation_id"], token=token)
    env.chat(FOLLOW_UP, conversation_id=first["conversation_id"], token=token)
    sent = json.dumps(_condense_calls(env))
    assert "meet.example.com" not in sent and "Panel A" not in sent and "aarav" not in sent.lower()
    assert "withheld from conversation memory" in sent  # only the placeholder is ever shown


def test_the_trace_records_the_rewrite_without_the_text(make_env: Callable[..., Env]) -> None:
    env = make_env(primary=ScriptedChatClient(condense_reply=STANDALONE))
    _two_turns(env)
    line = json.loads((env.settings.trace_dir / "requests.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert line["retrieval_query_rewritten"] == "llm" and line["condense_llm_called"] is True
    assert line["condense_llm_input_tokens"] == 200
    assert "mid semester" not in json.dumps(line)
