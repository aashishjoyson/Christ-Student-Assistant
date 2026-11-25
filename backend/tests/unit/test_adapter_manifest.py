"""The adapter manifest and the Model 3 endpoint check."""

from __future__ import annotations

import copy

import pytest

from app.eval.adapter_manifest import (
    EndpointNotReady,
    RetryableError,
    check_models_payload,
    validate_manifest,
    wait_for_endpoint,
)

BASE = "Qwen/Qwen3-4B-Instruct-2507"
GOOD = {
    "base_model_id": BASE, "base_model_revision": "a" * 40, "dataset_sha256": "b" * 64, "lora": {"r": 16, "alpha": 32, "dropout": 0.05},
    "epochs": 2, "trained_at": "2026-11-25T10:00:00Z", "prompt_version": "rag-v2", "eval_loss": 0.8, "libraries": {"trl": "1.18.2"},
}


def check(manifest: dict, **kw):  # type: ignore[no-untyped-def]
    return validate_manifest(manifest, current_prompt_version="rag-v2", **kw)


def test_a_complete_manifest_has_no_errors_or_warnings() -> None:
    assert check(GOOD) == ([], [])


@pytest.mark.parametrize("field", ["base_model_id", "base_model_revision", "dataset_sha256", "lora", "epochs", "trained_at", "prompt_version"])
def test_every_required_field_is_required(field: str) -> None:
    broken = {k: v for k, v in GOOD.items() if k != field}
    errors, _ = check(broken)
    assert errors == [f"missing field '{field}'"]


@pytest.mark.parametrize(("change", "fragment"), [
    ({"base_model_revision": "main"}, "40-character commit"),
    ({"dataset_sha256": "abc"}, "64-character SHA-256"),
    ({"lora": {"r": "sixteen", "alpha": 32, "dropout": 0.05}}, "numeric r, alpha and dropout"),
    ({"epochs": 0}, "positive number"),
    ({"trained_at": "yesterday"}, "ISO date-time"),
])
def test_malformed_fields_are_errors(change: dict, fragment: str) -> None:
    errors, _ = check({**GOOD, **change})
    assert len(errors) == 1 and fragment in errors[0]


def test_an_adapter_trained_on_another_prompt_is_refused() -> None:
    errors, _ = check({**GOOD, "prompt_version": "rag-v1"})
    assert len(errors) == 1 and "rag-v1" in errors[0] and "rag-v2" in errors[0] and "Retrain" in errors[0]


def test_the_adapter_must_belong_to_the_configured_base_model_and_to_this_dataset() -> None:
    errors, _ = check(GOOD, configured_base_model="Qwen/Qwen3-1.7B")
    assert len(errors) == 1 and "MODEL3_BASE_MODEL_ID" in errors[0]
    assert check(GOOD, dataset_manifest={"train_sha256": "b" * 64}) == ([], [])
    errors, _ = check(GOOD, dataset_manifest={"train_sha256": "c" * 64})
    assert len(errors) == 1 and "not trained on this dataset" in errors[0]


def test_missing_evidence_of_fit_and_reproducibility_are_warnings_not_errors() -> None:
    bare = {k: v for k, v in GOOD.items() if k not in ("eval_loss", "libraries")}
    errors, warnings = check(bare)
    assert errors == [] and len(warnings) == 2
    _, high_rank = check({**GOOD, "lora": {"r": 64, "alpha": 128, "dropout": 0.05}})
    assert any("--max-lora-rank 64" in w for w in high_rank)


def payload(*entries: dict) -> dict:
    return {"object": "list", "data": list(entries)}


BASE_ENTRY = {"id": BASE, "root": BASE, "parent": None}
ADAPTER = {"id": "cu-helpdesk-lora", "root": "me/cu-helpdesk-lora", "parent": BASE}


def test_an_endpoint_serving_the_adapter_as_a_lora_of_the_base_passes() -> None:
    problems, notes = check_models_payload(payload(BASE_ENTRY, ADAPTER), "cu-helpdesk-lora", BASE, "me/cu-helpdesk-lora@abc")
    assert problems == [] and "parent matches" in notes[0]


def test_a_missing_adapter_or_base_is_a_problem() -> None:
    problems, _ = check_models_payload(payload(BASE_ENTRY), "cu-helpdesk-lora", BASE)
    assert len(problems) == 1 and "not served" in problems[0] and "--enable-lora" in problems[0]
    problems, _ = check_models_payload(payload(ADAPTER), "cu-helpdesk-lora", BASE)
    assert any("base model" in p for p in problems)
    assert check_models_payload({"data": []}, "x", BASE)[0] == ["the endpoint lists no models"]


def test_a_wrong_parent_is_a_problem() -> None:
    other = {**ADAPTER, "parent": "Qwen/Qwen3-1.7B"}
    problems, _ = check_models_payload(payload(BASE_ENTRY, other), "cu-helpdesk-lora", BASE)
    assert len(problems) == 1 and "not the configured base" in problems[0]


def test_no_parent_is_accepted_only_when_the_root_identifies_the_adapter() -> None:
    no_parent = {**ADAPTER, "parent": None}
    problems, notes = check_models_payload(payload(BASE_ENTRY, no_parent), "cu-helpdesk-lora", BASE, "me/cu-helpdesk-lora@abc")
    assert problems == [] and "JSON form" in notes[0]
    unknown = {**no_parent, "root": "/models/unrelated-artifact"}
    problems, _ = check_models_payload(payload(BASE_ENTRY, unknown), "cu-helpdesk-lora", BASE, "me/cu-helpdesk-lora@abc")
    assert len(problems) == 1 and "cannot confirm" in problems[0]


def test_a_hugging_face_cache_path_identifies_the_adapter_when_no_parent_is_reported() -> None:
    """vLLM loaded from a local snapshot reports the cache path as root, where the repository appears as user--repo."""
    cache_path = "/root/.cache/huggingface/hub/models--someone--cu-helpdesk-lora/snapshots/" + "a" * 40
    no_parent = {"id": "cu-helpdesk-lora", "root": cache_path, "parent": None}
    problems, notes = check_models_payload(payload(BASE_ENTRY, no_parent), "cu-helpdesk-lora", BASE, "someone/cu-helpdesk-lora@aaaaaaa")
    assert problems == [] and "JSON form" in notes[0]


class FakeClock:
    """Time that only moves when something sleeps, so the waiting logic is tested instantly."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_waiting_returns_at_once_when_the_endpoint_is_up() -> None:
    t = FakeClock()
    assert wait_for_endpoint(lambda: {"ok": 1}, 600, clock=t.clock, sleep=t.sleep) == {"ok": 1} and t.sleeps == []


def test_a_cold_start_is_retried_until_the_endpoint_answers() -> None:
    t = FakeClock()
    answers = iter([RetryableError("HTTP 503"), RetryableError("HTTP 503"), RetryableError("ConnectError"), {"data": []}])
    seen: list[tuple[int, float]] = []

    def fetch() -> dict:
        item = next(answers)
        if isinstance(item, Exception):
            raise item
        return item

    result = wait_for_endpoint(fetch, 600, interval=10, clock=t.clock, sleep=t.sleep, on_wait=lambda attempt, left: seen.append((attempt, left)))
    assert result == {"data": []} and t.sleeps == [10, 10, 10]
    assert [a for a, _ in seen] == [1, 2, 3] and seen[0][1] == 600  # it reports each attempt and how long it will still wait


def test_waiting_gives_up_at_the_deadline_and_never_sleeps_past_it() -> None:
    t = FakeClock()
    calls: list[int] = []

    def never_ready() -> dict:
        calls.append(1)
        raise RetryableError("HTTP 503")

    with pytest.raises(EndpointNotReady, match="HTTP 503"):
        wait_for_endpoint(never_ready, 25, interval=10, clock=t.clock, sleep=t.sleep)
    assert t.sleeps == [10, 10, 5] and t.now == 25 and len(calls) == 4


def test_a_rejected_key_is_not_retried_and_zero_means_one_attempt() -> None:
    t = FakeClock()

    def wrong_key() -> dict:
        raise PermissionError("HTTP 401")

    with pytest.raises(PermissionError):
        wait_for_endpoint(wrong_key, 600, clock=t.clock, sleep=t.sleep)
    assert t.sleeps == []

    def cold() -> dict:
        raise RetryableError("HTTP 503")

    with pytest.raises(EndpointNotReady):
        wait_for_endpoint(cold, 0, clock=t.clock, sleep=t.sleep)
    assert t.sleeps == []


def test_an_adapter_named_like_the_base_model_is_flagged() -> None:
    clash = {"id": BASE, "root": "me/cu-helpdesk-lora", "parent": BASE}
    problems, _ = check_models_payload(payload(clash), BASE, BASE, "me/cu-helpdesk-lora")
    assert any("same name" in p for p in problems)
    assert copy.deepcopy(GOOD) == GOOD
