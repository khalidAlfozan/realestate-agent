"""Cost calculation for Anthropic API calls.

Prices are USD per 1M tokens, snapshotted from the Anthropic public price
sheet. Update when Anthropic changes pricing — pricing isn't in Settings
because it's vendor-published, not user-tunable.

Cache pricing math (Anthropic's documented multipliers vs base input):
  cache write (5-min TTL) = base *1.25
  cache read              = base *0.10

We track them as separate per-1M figures here for clarity (no implicit
multiplication at call sites).
"""

from __future__ import annotations

from typing import Protocol


class _Usage(Protocol):
    """Subset of anthropic.types.Usage we read for cost calculation."""

    input_tokens: int
    output_tokens: int


# USD per 1M tokens. Snapshot 2026-05; refresh periodically.
PRICING_USD_PER_M: dict[str, dict[str, float]] = {
    "claude-opus-4-7": {
        "input": 5.00,
        "output": 25.00,
        "cache_read": 0.50,
        "cache_write": 6.25,
    },
    "claude-sonnet-4-6": {
        "input": 3.00,
        "output": 15.00,
        "cache_read": 0.30,
        "cache_write": 3.75,
    },
    "claude-haiku-4-5": {
        "input": 1.00,
        "output": 5.00,
        "cache_read": 0.10,
        "cache_write": 1.25,
    },
}


def compute_cost_usd(model: str, usage: _Usage) -> float:
    """Compute USD cost for a single API response given its usage block.

    Returns 0.0 (with no error) for unknown models — pricing is missing for
    e.g. Anthropic's internal experimental models. The agent loop continues
    to work; cost just under-reports.
    """
    pricing = PRICING_USD_PER_M.get(model)
    if pricing is None:
        return 0.0

    input_tokens = usage.input_tokens
    output_tokens = usage.output_tokens
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0

    return (
        input_tokens * pricing["input"]
        + output_tokens * pricing["output"]
        + cache_read * pricing["cache_read"]
        + cache_write * pricing["cache_write"]
    ) / 1_000_000
