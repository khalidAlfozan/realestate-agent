"""Tests for src.cost — pricing snapshot + per-response computation."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.cost import PRICING_USD_PER_M, compute_cost_usd


def _usage(
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read: int = 0,
    cache_write: int = 0,
) -> MagicMock:
    """Build a minimal Usage-like object for the cost calculator."""
    u = MagicMock()
    u.input_tokens = input_tokens
    u.output_tokens = output_tokens
    u.cache_read_input_tokens = cache_read
    u.cache_creation_input_tokens = cache_write
    return u


class TestPricingSnapshot:
    def test_snapshot_includes_all_models_we_use(self) -> None:
        """The agent loop runs on Sonnet 4.6, the vision sub-call on Haiku 4.5.
        These must always be priced; missing pricing returns 0.0 silently which
        would silently under-report cost."""
        assert "claude-sonnet-4-6" in PRICING_USD_PER_M
        assert "claude-haiku-4-5" in PRICING_USD_PER_M

    def test_pricing_fields_complete(self) -> None:
        """Each model must have all four pricing dimensions."""
        for model, prices in PRICING_USD_PER_M.items():
            assert {"input", "output", "cache_read", "cache_write"} <= prices.keys(), (
                f"{model!r} missing pricing fields"
            )


class TestComputeCost:
    def test_basic_input_output(self) -> None:
        """Sonnet 4.6 at 1M input + 1M output = $3 + $15 = $18."""
        cost = compute_cost_usd(
            "claude-sonnet-4-6", _usage(input_tokens=1_000_000, output_tokens=1_000_000)
        )
        assert cost == pytest.approx(18.0)

    def test_typical_real_run(self) -> None:
        """A representative iteration: ~5K input, 2K output, 3K cache_read,
        500 cache_write on Sonnet 4.6."""
        cost = compute_cost_usd(
            "claude-sonnet-4-6",
            _usage(input_tokens=5000, output_tokens=2000, cache_read=3000, cache_write=500),
        )
        # 5000*3 + 2000*15 + 3000*0.3 + 500*3.75 = 15000 + 30000 + 900 + 1875 = 47775 / 1e6 = 0.047775
        assert cost == pytest.approx(0.047775, abs=1e-6)

    def test_unknown_model_returns_zero(self) -> None:
        """Unknown models (e.g. internal experiments) shouldn't crash the loop;
        cost just under-reports."""
        cost = compute_cost_usd(
            "claude-experimental-x", _usage(input_tokens=1000, output_tokens=1000)
        )
        assert cost == 0.0

    def test_cache_tokens_priced_correctly(self) -> None:
        """Cache reads are ~10x cheaper than fresh input; cache writes 1.25x."""
        # Sonnet pricing: input $3/M, cache_read $0.30/M, cache_write $3.75/M
        # 1000 cache_read = 1000 * 0.3 / 1e6 = $0.0003
        cost = compute_cost_usd("claude-sonnet-4-6", _usage(cache_read=1000))
        assert cost == pytest.approx(0.0003, abs=1e-9)
        # 1000 cache_write = 1000 * 3.75 / 1e6 = $0.00375
        cost = compute_cost_usd("claude-sonnet-4-6", _usage(cache_write=1000))
        assert cost == pytest.approx(0.00375, abs=1e-9)

    def test_handles_missing_cache_attrs(self) -> None:
        """Some Usage variants don't set cache_*_tokens at all (they're added
        only when caching is in play). getattr should return 0."""
        usage = MagicMock(spec=["input_tokens", "output_tokens"])
        usage.input_tokens = 1000
        usage.output_tokens = 500
        cost = compute_cost_usd("claude-sonnet-4-6", usage)
        # 1000 * 3 + 500 * 15 = 3000 + 7500 = 10500 / 1e6 = 0.0105
        assert cost == pytest.approx(0.0105, abs=1e-6)

    def test_handles_none_cache_values(self) -> None:
        """cache_*_input_tokens can be present as None on responses that didn't
        use caching. Treat as 0."""
        usage = MagicMock()
        usage.input_tokens = 100
        usage.output_tokens = 50
        usage.cache_read_input_tokens = None
        usage.cache_creation_input_tokens = None
        cost = compute_cost_usd("claude-sonnet-4-6", usage)
        # 100 * 3 + 50 * 15 = 1050 / 1e6 = 0.00105
        assert cost == pytest.approx(0.00105, abs=1e-9)
