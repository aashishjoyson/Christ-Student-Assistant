"""The live-flow event log: ordering, bounds, thread safety, and above all what is NOT allowed into an event."""

from __future__ import annotations

import json
import threading

import pytest

from app.core import flow
from app.core.flow import SERVICES, FlowBus, clean_detail


def publish(bus: FlowBus, **kw: object) -> object:
    base: dict = {"trace_id": "t1", "kind": "node", "name": "n", "phase": "end", "service": "graph", "label": "did it"}
    base.update(kw)
    return bus.publish(**base)


def test_events_get_increasing_numbers_and_readers_ask_for_what_is_newer() -> None:
    bus = FlowBus()
    first, second, third = (publish(bus, name=f"n{i}") for i in range(3))
    assert [first.seq, second.seq, third.seq] == [1, 2, 3] and bus.last_seq == 3
    assert [e.name for e in bus.since(0)] == ["n0", "n1", "n2"]
    assert [e.name for e in bus.since(2)] == ["n2"]
    assert bus.since(3) == []
    assert len(bus.since(0, limit=2)) == 2


def test_the_log_is_bounded_and_forgets_the_oldest_first() -> None:
    bus = FlowBus(capacity=5)
    for i in range(12):
        publish(bus, name=f"n{i}")
    assert [e.name for e in bus.since(0)] == ["n7", "n8", "n9", "n10", "n11"] and bus.last_seq == 12


def test_many_threads_publishing_never_duplicate_a_number() -> None:
    bus = FlowBus(capacity=5000)
    threads = [threading.Thread(target=lambda: [publish(bus) for _ in range(100)]) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    numbers = [e.seq for e in bus.since(0, limit=1000)]
    assert numbers == list(range(1, 801))


# ---------- what may never be in an event ----------
@pytest.mark.parametrize(
    "key",
    ["message", "text", "question", "answer", "prompt", "query", "email", "subject", "body", "passage", "passages", "content", "password", "api_key",
     "authorization", "recipient", "to", "answer_text", "smtp_password", "db_secret", "user_email", "search_query", "Message", "TEXT"],
)
def test_keys_that_could_hold_private_text_or_secrets_are_dropped(key: str) -> None:
    assert clean_detail({key: "something private", "model": "kept"}) == {"model": "kept"}


def test_useful_keys_that_look_similar_are_kept() -> None:
    kept = {"prompt_version": "rag-v2", "input_tokens": 120, "masked_recipient": "a***o@example.com", "provider_message_id": "<id@x>",
            "message_chars": 41, "first_token_ms": 300}
    assert clean_detail(kept) == kept


def test_addresses_are_masked_everywhere_and_long_text_is_cut() -> None:
    out = clean_detail({"note": "sent to aarav.demo@example.com ok", "nested": {"who": ["x.y@example.org"]}, "long": "x" * 1000})
    assert "aarav.demo@example.com" not in json.dumps(out) and "x.y@example.org" not in json.dumps(out)
    assert out["note"] == "sent to a********o@example.com ok" and len(out["long"]) == 160


def test_numbers_lists_and_odd_objects_are_made_safe() -> None:
    out = clean_detail({"distance": 0.123456789, "items": list(range(50)), "obj": object, "none": None, "flag": True})
    assert out["distance"] == 0.1235 and len(out["items"]) == 12 and out["none"] is None and out["flag"] is True
    assert isinstance(out["obj"], str)


def test_an_address_that_is_already_masked_is_not_masked_again() -> None:
    assert clean_detail({"who": "a***o@example.com"}) == {"who": "a***o@example.com"}
    assert clean_detail({"who": "to a***o@example.com and bob@example.org"}) == {"who": "to a***o@example.com and b*b@example.org"}


def test_the_message_id_survives_but_only_under_its_own_key() -> None:
    assert clean_detail({"mail_id": "<1.2@gmail.com>"}) == {"mail_id": "<1.2@gmail.com>"}
    assert clean_detail({"other": "<1.2@gmail.com>"}) != {"other": "<1.2@gmail.com>"}


def test_the_label_is_masked_too() -> None:
    bus = FlowBus()
    event = publish(bus, label="Sent to aarav.demo@example.com")
    assert "aarav.demo@example.com" not in event.label


# ---------- the process-wide hook ----------
def test_without_a_bus_everything_is_a_silent_no_op() -> None:
    flow.install(None)
    flow.emit("node", "n", "end", "graph", "x")
    with flow.span("s", "graph", "x") as info:
        info["a"] = 1
    with flow.trace_scope("t"):
        flow.emit("node", "n", "end", "graph", "x")


def test_a_span_publishes_one_event_with_its_duration_and_the_detail_it_collected() -> None:
    bus = FlowBus()
    flow.install(bus)
    with flow.trace_scope("req-1"), flow.span("embed_query", "embedder", "Embedded", model="m") as info:
        info["tokens"] = 7
    (event,) = bus.since(0)
    assert (event.trace_id, event.name, event.phase, event.service) == ("req-1", "embed_query", "end", "embedder")
    assert event.ms is not None and event.ms >= 0 and event.detail == {"model": "m", "tokens": 7}


def test_a_failing_span_publishes_an_error_and_lets_the_exception_through() -> None:
    bus = FlowBus()
    flow.install(bus)
    with pytest.raises(RuntimeError), flow.span("vector_search", "chroma", "Searching"):
        raise RuntimeError("boom with secret text")
    (event,) = bus.since(0)
    assert event.phase == "error" and event.detail == {"error": "RuntimeError"}  # the class name, never the message


def test_events_outside_any_request_belong_to_system_and_an_explicit_trace_wins() -> None:
    bus = FlowBus()
    flow.install(bus)
    flow.emit("node", "a", "end", "graph", "x")
    with flow.trace_scope("scoped"):
        flow.emit("node", "b", "end", "graph", "x")
        flow.emit("node", "c", "end", "graph", "x", trace_id="explicit")
    assert [e.trace_id for e in bus.since(0)] == ["system", "scoped", "explicit"]


def test_a_broken_bus_never_breaks_the_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = FlowBus()
    flow.install(bus)
    monkeypatch.setattr(bus, "publish", lambda **_: (_ for _ in ()).throw(RuntimeError("bus down")))
    flow.emit("node", "n", "end", "graph", "x")  # must not raise
    with flow.span("s", "graph", "x"):
        pass


def test_every_box_on_the_map_is_described() -> None:
    assert {"browser", "api", "graph", "chroma", "llm_openai", "llm_modal", "email", "sqlite", "evidently", "gate"} <= set(SERVICES)
    for key, info in SERVICES.items():
        assert info["label"] and info["role"] and info["group"] in {"client", "app", "model", "data", "ops"}, key
