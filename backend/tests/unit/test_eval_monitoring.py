"""Monitoring: window summaries, alerts, drift and freshness, over trace records shaped like the real ones."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.eval.monitoring import Thresholds, evaluate_alerts, in_window, parse_ts, summarize, worst_level

T0 = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def trace(i: int = 0, **kw: object) -> dict:
    base = {"ts": (T0 + timedelta(seconds=i)).isoformat(), "message_id": f"m{i}", "intent": "academic_qa", "model_mode_requested": "rag",
            "handled_by": "llm", "llm_called": True, "total_latency_ms": 1500, "ttft_ms": None, "est_cost_usd": 0.0001,
            "intent_llm_est_cost_usd": None, "condense_llm_est_cost_usd": None, "intent_llm_called": False, "error_code": None,
            "retrieval": {"ready": True, "returned": 8, "kept": 8, "best_distance": 0.3}}
    return base | kw


def many(n: int, **kw: object) -> list[dict]:
    return [trace(i, **kw) for i in range(n)]


def test_an_empty_window_summarises_to_zeros_without_dividing_by_zero() -> None:
    s = summarize([])
    assert s["requests"] == 0 and s["error_rate"] is None and s["latency_ms"] == {"p50": None, "p95": None} and s["cost_usd_per_request"] is None
    assert [a.code for a in evaluate_alerts(s)] == ["no_traffic"]


def test_the_summary_counts_what_the_traces_say() -> None:
    traces = [
        trace(0, total_latency_ms=1000, ttft_ms=400, est_cost_usd=0.001, intent_llm_est_cost_usd=0.0005, intent_llm_called=True),
        trace(1, total_latency_ms=3000, est_cost_usd=0.002),
        trace(2, error_code="llm_timeout", total_latency_ms=30000, est_cost_usd=None),
        trace(3, intent="applicant_status", llm_called=False, model_mode_requested="direct", retrieval=None, total_latency_ms=20, est_cost_usd=None),
        trace(4, retrieval={"ready": True, "returned": 8, "kept": 0, "best_distance": 0.91}, llm_called=False),
    ]
    s = summarize(traces)
    assert s["requests"] == 5 and s["errors"] == 1 and s["error_rate"] == 0.2 and s["error_codes"] == {"llm_timeout": 1}
    assert s["latency_ms"]["p50"] == 1250.0  # median of 20, 1000, 1500 and 3000 ms; the 30 s timeout is an error, not a latency
    assert s["first_word_ms"]["p50"] == 400.0
    assert s["cost_usd_total"] == 0.0036 and s["intent_llm_calls"] == 1  # 0.0015 + 0.002 + 0.0001, the answer and the routing call both count
    assert s["intent_mix"] == {"academic_qa": 4, "applicant_status": 1} and s["mode_mix"] == {"rag": 4, "direct": 1}
    assert s["document_questions"] == 3 and s["no_evidence_rate"] == round(1 / 3, 4)
    assert s["best_distance"]["n"] == 3 and s["best_distance"]["mean"] == round((0.3 + 0.3 + 0.91) / 3, 4)


def test_feedback_is_summarised_with_reasons() -> None:
    votes = [{"rating": "up"}] * 3 + [{"rating": "down", "reason": "wrong_answer"}] * 2 + [{"rating": "down"}]
    f = summarize([], votes)["feedback"]
    assert f == {"votes": 6, "down": 3, "thumbs_down_rate": 0.5, "down_reasons": {"wrong_answer": 2, "none": 1}}


def test_windows_select_by_timestamp_and_skip_unreadable_ones() -> None:
    traces = many(10) + [{"ts": "garbage"}, {}]
    got = in_window(traces, T0 + timedelta(seconds=3), T0 + timedelta(seconds=7))
    assert [t["message_id"] for t in got] == ["m3", "m4", "m5", "m6"]
    assert parse_ts("2026-11-24T12:00:00Z") == T0 and parse_ts("2026-11-24T12:00:00").tzinfo is not None and parse_ts("nope") is None


def test_healthy_traffic_raises_no_alert() -> None:
    assert evaluate_alerts(summarize(many(30))) == []


def test_a_small_sample_is_not_alerted_on() -> None:
    s = summarize(many(5, error_code="llm_timeout"))
    alerts = evaluate_alerts(s)
    assert [a.code for a in alerts] == ["small_sample"] and worst_level(alerts) == "ok"


def test_a_high_error_rate_is_critical() -> None:
    traces = many(30) + [trace(100 + i, error_code="provider_unreachable") for i in range(5)]
    alerts = evaluate_alerts(summarize(traces))
    assert [a.level for a in alerts if a.code == "error_rate"] == ["critical"] and worst_level(alerts) == "critical"


def test_slow_answers_and_missing_evidence_are_warnings() -> None:
    slow = summarize(many(30, total_latency_ms=20000))
    assert [a.code for a in evaluate_alerts(slow)] == ["latency_p95"]
    none_found = summarize(many(30, retrieval={"ready": True, "returned": 8, "kept": 0, "best_distance": 0.95}))
    assert [a.code for a in evaluate_alerts(none_found)] == ["no_evidence_rate"]
    assert [a.code for a in evaluate_alerts(summarize(many(3, retrieval={"ready": False})))] == ["small_sample", "not_indexed"]


def test_thumbs_down_needs_enough_votes() -> None:
    base = summarize(many(30))
    few = summarize(many(30), [{"rating": "down"}] * 5)
    assert [a.code for a in evaluate_alerts(few)] == []  # 5 votes: not enough
    many_votes = summarize(many(30), [{"rating": "down", "reason": "wrong_answer"}] * 8 + [{"rating": "up"}] * 4)
    assert [a.code for a in evaluate_alerts(many_votes)] == ["thumbs_down"] and evaluate_alerts(base) == []


def test_drift_against_a_reference_window() -> None:
    reference = summarize(many(40))
    farther = summarize(many(30, retrieval={"ready": True, "returned": 8, "kept": 8, "best_distance": 0.45}))
    costly = summarize(many(30, est_cost_usd=0.0005))
    slower = summarize(many(30, total_latency_ms=4000))
    assert [a.code for a in evaluate_alerts(farther, reference)] == ["distance_drift"]
    assert [a.code for a in evaluate_alerts(costly, reference)] == ["cost_drift"]
    assert [a.code for a in evaluate_alerts(slower, reference)] == ["latency_drift"]
    assert evaluate_alerts(summarize(many(30)), reference) == []
    # a thin reference window proves nothing, so it is not used
    assert evaluate_alerts(farther, summarize(many(3))) == []


def test_a_stale_index_is_flagged_and_an_unknown_one_is_information() -> None:
    s = summarize(many(30))
    assert [a.code for a in evaluate_alerts(s, index_age=timedelta(hours=30))] == ["stale_index"]
    assert evaluate_alerts(s, index_age=timedelta(hours=2)) == []
    assert [a.code for a in evaluate_alerts(s, index_known=False)] == ["index_unknown"]


@pytest.mark.parametrize(("thresholds", "expected"), [(Thresholds(error_rate=0.5), []), (Thresholds(error_rate=0.01), ["error_rate"])])
def test_thresholds_are_adjustable(thresholds: Thresholds, expected: list[str]) -> None:
    traces = many(40) + [trace(100 + i, error_code="x") for i in range(3)]  # 7% errors
    assert [a.code for a in evaluate_alerts(summarize(traces), thresholds=thresholds)] == expected
