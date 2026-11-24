"""Monitoring over the request trace log (stdlib only): window summaries, drift against a reference window, and alerts.

The traces hold no message text (invariant 7), so everything here is numbers and labels: latency, cost, error codes, intents, how close the
nearest passage was, and thumbs. The same functions feed the admin endpoint, `scripts/monitor_traces.py` and the tests.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.eval.metrics import percentile

RAG_MODES = ("rag", "rag_peft")


@dataclass(frozen=True)
class Thresholds:
    min_requests: int = 20  # below this a rate is noise: it is reported, never alerted on
    error_rate: float = 0.05  # critical
    latency_p95_ms: float = 15_000.0
    no_evidence_rate: float = 0.35  # of document questions answered "could not find": the documents or the retrieval may be broken
    thumbs_down_rate: float = 0.30
    min_votes: int = 10
    distance_shift: float = 0.08  # the nearest passage got this much farther away on average than in the reference window
    cost_ratio: float = 2.0  # cost per request versus the reference window
    latency_ratio: float = 2.0
    index_max_age: timedelta = timedelta(hours=24)  # no successful document sync for this long


@dataclass(frozen=True)
class Alert:
    level: str  # "critical" | "warning" | "info"
    code: str
    message: str


def parse_ts(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def in_window(traces: Iterable[dict[str, Any]], since: datetime | None, until: datetime | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in traces:
        ts = parse_ts(str(t.get("ts", "")))
        if ts is None or (since is not None and ts < since) or (until is not None and ts >= until):
            continue
        out.append(t)
    return out


def _cost(trace: dict[str, Any]) -> float:
    return sum(float(trace.get(k) or 0.0) for k in ("est_cost_usd", "intent_llm_est_cost_usd", "condense_llm_est_cost_usd"))


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _stats(values: Sequence[float]) -> dict[str, float | None]:
    return {"p50": percentile(values, 50), "p95": percentile(values, 95)}


def summarize(traces: Sequence[dict[str, Any]], feedback: Sequence[dict[str, Any]] = ()) -> dict[str, Any]:
    """One window of traffic, as plain numbers. `feedback` rows are {rating, reason, model_mode}."""
    n = len(traces)
    errors = [t for t in traces if t.get("error_code")]
    ok = [t for t in traces if not t.get("error_code")]
    docs = [t for t in ok if t.get("intent") == "academic_qa" and t.get("model_mode_requested") in RAG_MODES]
    retrievals = [t["retrieval"] for t in docs if isinstance(t.get("retrieval"), dict)]
    no_evidence = [r for r in retrievals if r.get("ready") and r.get("kept") == 0]
    not_indexed = [r for r in retrievals if r.get("ready") is False]
    distances = [float(r["best_distance"]) for r in retrievals if r.get("best_distance") is not None]
    latencies = [float(t["total_latency_ms"]) for t in ok if t.get("total_latency_ms") is not None]
    ttft = [float(t["ttft_ms"]) for t in ok if t.get("ttft_ms") is not None]
    costs = [_cost(t) for t in traces]
    down = sum(1 for f in feedback if f.get("rating") == "down")
    return {
        "requests": n,
        "errors": len(errors), "error_rate": _rate(len(errors), n), "error_codes": dict(Counter(str(t["error_code"]) for t in errors)),
        "latency_ms": _stats(latencies), "first_word_ms": _stats(ttft),
        "cost_usd_total": round(sum(costs), 6), "cost_usd_per_request": round(sum(costs) / n, 6) if n else None,
        "llm_answers": sum(1 for t in ok if t.get("llm_called")), "template_answers": sum(1 for t in ok if not t.get("llm_called")),
        "intent_llm_calls": sum(1 for t in traces if t.get("intent_llm_called")),
        "mode_mix": dict(Counter(str(t.get("model_mode_requested")) for t in traces)),
        "intent_mix": dict(Counter(str(t.get("intent")) for t in traces)),
        "document_questions": len(docs),
        "no_evidence_rate": _rate(len(no_evidence), len(retrievals)), "not_indexed": len(not_indexed),
        "best_distance": {"mean": round(sum(distances) / len(distances), 4) if distances else None, "p50": percentile(distances, 50),
                          "p90": percentile(distances, 90), "n": len(distances)},
        "feedback": {"votes": len(feedback), "down": down, "thumbs_down_rate": _rate(down, len(feedback)),
                     "down_reasons": dict(Counter(str(f.get("reason") or "none") for f in feedback if f.get("rating") == "down"))},
    }


def _get(summary: dict[str, Any] | None, *path: str) -> Any:
    cur: Any = summary
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def evaluate_alerts(current: dict[str, Any], reference: dict[str, Any] | None = None, thresholds: Thresholds = Thresholds(),
                    index_age: timedelta | None = None, index_known: bool = True) -> list[Alert]:
    """Turn a window summary (and an optional reference window) into alerts. Rate alerts need `min_requests` of traffic."""
    t = thresholds
    alerts: list[Alert] = []
    n = current["requests"]
    if n == 0:
        alerts.append(Alert("info", "no_traffic", "No requests in this window."))
    enough = n >= t.min_requests
    if 0 < n < t.min_requests:
        alerts.append(Alert("info", "small_sample", f"Only {n} requests (need {t.min_requests}): rates are shown but not alerted on."))

    if enough and (current["error_rate"] or 0) > t.error_rate:
        alerts.append(Alert("critical", "error_rate", f"Error rate {current['error_rate']:.1%} is above {t.error_rate:.0%}: {current['error_codes']}"))
    p95 = _get(current, "latency_ms", "p95")
    if enough and p95 is not None and p95 > t.latency_p95_ms:
        alerts.append(Alert("warning", "latency_p95", f"p95 latency {p95:.0f} ms is above {t.latency_p95_ms:.0f} ms."))
    ne = current.get("no_evidence_rate")
    if current["document_questions"] >= t.min_requests and ne is not None and ne > t.no_evidence_rate:
        alerts.append(Alert("warning", "no_evidence_rate", f"{ne:.0%} of document questions found no passage within the cut-off "
                                                           f"(above {t.no_evidence_rate:.0%}): the documents or the retrieval may be broken."))
    if current.get("not_indexed"):
        alerts.append(Alert("warning", "not_indexed", f"{current['not_indexed']} document question(s) were asked while nothing was indexed."))
    fb = current["feedback"]
    if fb["votes"] >= t.min_votes and (fb["thumbs_down_rate"] or 0) > t.thumbs_down_rate:
        alerts.append(Alert("warning", "thumbs_down", f"{fb['thumbs_down_rate']:.0%} of {fb['votes']} ratings are thumbs down: {fb['down_reasons']}"))

    if reference is not None and reference["requests"] >= t.min_requests and enough:
        d_now, d_ref = _get(current, "best_distance", "mean"), _get(reference, "best_distance", "mean")
        if d_now is not None and d_ref is not None and d_now - d_ref > t.distance_shift:
            alerts.append(Alert("warning", "distance_drift", f"The nearest passage is farther than before (mean best distance {d_ref:.3f} -> {d_now:.3f}): "
                                                             "the questions, the documents or the embeddings have changed."))
        c_now, c_ref = current.get("cost_usd_per_request"), reference.get("cost_usd_per_request")
        if c_now and c_ref and c_now > c_ref * t.cost_ratio:
            alerts.append(Alert("warning", "cost_drift", f"Cost per request rose x{c_now / c_ref:.1f} (${c_ref:.5f} -> ${c_now:.5f})."))
        l_ref = _get(reference, "latency_ms", "p95")
        if p95 and l_ref and p95 > l_ref * t.latency_ratio:
            alerts.append(Alert("warning", "latency_drift", f"p95 latency rose x{p95 / l_ref:.1f} ({l_ref:.0f} -> {p95:.0f} ms)."))

    if not index_known:
        alerts.append(Alert("info", "index_unknown", "No document sync has been recorded yet."))
    elif index_age is not None and index_age > t.index_max_age:
        alerts.append(Alert("warning", "stale_index", f"The last successful document sync was {index_age.total_seconds() / 3600:.1f} h ago "
                                                      f"(limit {t.index_max_age.total_seconds() / 3600:.0f} h): answers may be out of date."))
    return alerts


def worst_level(alerts: Sequence[Alert]) -> str:
    levels = {a.level for a in alerts}
    return "critical" if "critical" in levels else ("warning" if "warning" in levels else "ok")
