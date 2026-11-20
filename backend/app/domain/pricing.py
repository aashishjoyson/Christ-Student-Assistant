"""Approximate USD prices per 1M tokens, used only for cost *estimates* in traces/evaluation.

Prices change often. Checked on 2026-11-20 from public pricing pages; re-check before reporting
costs and record the date in your evaluation report. Unknown models return None (shown as "n/a").
"""

from __future__ import annotations

PRICES_CHECKED_ON = "2026-11-20"

# model id -> (input $/1M tokens, output $/1M tokens)
PRICES_PER_MILLION: dict[str, tuple[float, float]] = {
    "gpt-6-luna": (0.10, 0.50),
    "gpt-5.6-luna": (0.20, 1.20),
    "text-embedding-3-small": (0.02, 0.0),
}


def estimate_cost_usd(model: str, input_tokens: int | None, output_tokens: int | None) -> float | None:
    prices = PRICES_PER_MILLION.get(model)
    if prices is None or input_tokens is None:
        return None
    cost = input_tokens * prices[0] / 1_000_000 + (output_tokens or 0) * prices[1] / 1_000_000
    return round(cost, 8)
