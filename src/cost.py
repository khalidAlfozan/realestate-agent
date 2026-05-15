"""Cost calculation for Anthropic API calls.

Prices are USD per 1M tokens, snapshotted from the Anthropic public price
sheet (https://www.anthropic.com/api/pricing). Pricing isn't in Settings
because it's vendor-published, not user-tunable.

Anthropic doesn't currently expose pricing programmatically (the Models API
returns metadata + capabilities but no price), so the table is hand-curated.
To prevent silent staleness:

- `PRICING_SNAPSHOT_DATE` records when the table was last verified.
- A WARNING is logged at module load if the snapshot is older than
  `STALENESS_WARN_AFTER_DAYS`.
- `compute_cost_usd` logs a one-time WARNING per unknown model, so
  silent under-reporting becomes visible instead of hiding.

When updating: bump `PRICING_SNAPSHOT_DATE` to today's date in the same
commit, so the staleness clock resets only when the numbers actually got
verified.

Cache pricing math (Anthropic's documented multipliers vs base input):
  cache write (5-min TTL) = base *1.25
  cache read              = base *0.10

We track them as separate per-1M figures here for clarity (no implicit
multiplication at call sites).
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Protocol

log = logging.getLogger(__name__)


class _Usage(Protocol):
    """Subset of anthropic.types.Usage we read for cost calculation."""

    input_tokens: int
    output_tokens: int


# Date this pricing table was last verified against
# https://www.anthropic.com/api/pricing. Bump in the same commit when
# updating PRICING_USD_PER_M, otherwise the staleness check lies.
PRICING_SNAPSHOT_DATE = date(2026, 5, 1)

# How long before the staleness warning fires. ~6 months matches the
# observed cadence of Anthropic price changes (rare but real).
STALENESS_WARN_AFTER_DAYS = 180

# USD per 1M tokens.
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

# Track which unknown models we've already warned about so we log once
# per model per process, not on every iteration.
_warned_unknown_models: set[str] = set()


def _check_staleness(today: date | None = None) -> int:
    """Log a WARNING if the pricing snapshot is older than the threshold.

    Returns the snapshot age in days (for tests). Pure function — `today`
    is injectable so tests can simulate "in 7 months from now".
    """
    today = today or datetime.now(UTC).date()
    age_days = (today - PRICING_SNAPSHOT_DATE).days
    if age_days > STALENESS_WARN_AFTER_DAYS:
        log.warning(
            "Pricing snapshot is %d days old (last verified %s). "
            "Verify against https://www.anthropic.com/api/pricing and update "
            "src/cost.py:PRICING_USD_PER_M + PRICING_SNAPSHOT_DATE.",
            age_days,
            PRICING_SNAPSHOT_DATE.isoformat(),
        )
    return age_days


# Run staleness check at module load. Cost is one timedelta subtraction +
# one log call (no-op if not stale); negligible vs the cost of silent drift.
_check_staleness()


def compute_cost_usd(model: str, usage: _Usage) -> float:
    """Compute USD cost for a single API response given its usage block.

    Returns 0.0 for unknown models so the agent loop keeps working — pricing
    is missing for e.g. Anthropic's internal experimental models. Logs a
    WARNING the first time we hit an unknown model, so the under-reporting
    becomes visible instead of silent.
    """
    pricing = PRICING_USD_PER_M.get(model)
    if pricing is None:
        if model not in _warned_unknown_models:
            _warned_unknown_models.add(model)
            log.warning(
                "No pricing entry for model %r — cost reporting will under-report by "
                "this model's contribution. Add an entry to "
                "src/cost.py:PRICING_USD_PER_M.",
                model,
            )
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
