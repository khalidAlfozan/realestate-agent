"""Tests for src.cost — pricing snapshot + per-response computation."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from src import cost
from src.cost import (
    PRICING_SNAPSHOT_DATE,
    PRICING_USD_PER_M,
    STALENESS_WARN_AFTER_DAYS,
    _check_staleness,
    compute_cost_usd,
)


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
        result = compute_cost_usd("claude-sonnet-4-6", usage)
        # 100 * 3 + 50 * 15 = 1050 / 1e6 = 0.00105
        assert result == pytest.approx(0.00105, abs=1e-9)


class TestStaleness:
    """The pricing snapshot should self-warn when it's older than ~6 months,
    so silent decay becomes a visible CI / log artefact."""

    def test_does_not_warn_when_fresh(self, caplog: pytest.LogCaptureFixture) -> None:
        """Snapshot newer than the threshold → silent."""
        # Pretend "today" is one day after the snapshot.
        fake_today = PRICING_SNAPSHOT_DATE + timedelta(days=1)
        with caplog.at_level(logging.WARNING, logger="src.cost"):
            age = _check_staleness(today=fake_today)
        assert age == 1
        assert not caplog.records

    def test_warns_when_stale(self, caplog: pytest.LogCaptureFixture) -> None:
        """Snapshot older than the threshold → WARNING with actionable message."""
        # 1 day past the staleness threshold.
        fake_today = PRICING_SNAPSHOT_DATE + timedelta(days=STALENESS_WARN_AFTER_DAYS + 1)
        with caplog.at_level(logging.WARNING, logger="src.cost"):
            age = _check_staleness(today=fake_today)
        assert age == STALENESS_WARN_AFTER_DAYS + 1
        assert len(caplog.records) == 1
        msg = caplog.records[0].getMessage()
        assert "Pricing snapshot is" in msg
        assert "anthropic.com/api/pricing" in msg
        assert PRICING_SNAPSHOT_DATE.isoformat() in msg

    def test_threshold_boundary_is_strict(self, caplog: pytest.LogCaptureFixture) -> None:
        """Exactly at the threshold = no warning; one day past = warning."""
        fake_today = PRICING_SNAPSHOT_DATE + timedelta(days=STALENESS_WARN_AFTER_DAYS)
        with caplog.at_level(logging.WARNING, logger="src.cost"):
            _check_staleness(today=fake_today)
        assert not caplog.records

    def test_snapshot_date_is_a_real_date(self) -> None:
        """Sanity-check: the constant is an actual date, not None / not in the future."""
        assert isinstance(PRICING_SNAPSHOT_DATE, date)
        assert date.today() >= PRICING_SNAPSHOT_DATE


class TestUnknownModelWarning:
    """Hitting an unknown model in compute_cost_usd should warn once per
    model per process — not silently return 0.0 forever."""

    def setup_method(self) -> None:
        # Reset the per-process "already warned" set so each test starts clean.
        cost._warned_unknown_models.clear()

    def test_warns_first_time_unknown_model_seen(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="src.cost"):
            compute_cost_usd("claude-experimental-x", _usage(input_tokens=100))
        warnings = [r for r in caplog.records if "No pricing entry" in r.getMessage()]
        assert len(warnings) == 1
        assert "claude-experimental-x" in warnings[0].getMessage()

    def test_does_not_warn_repeatedly_for_same_unknown_model(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Calling the same unknown model 5x should warn ONCE — otherwise the
        agent loop would log a warning per iteration."""
        with caplog.at_level(logging.WARNING, logger="src.cost"):
            for _ in range(5):
                compute_cost_usd("claude-experimental-x", _usage(input_tokens=100))
        warnings = [r for r in caplog.records if "No pricing entry" in r.getMessage()]
        assert len(warnings) == 1

    def test_warns_separately_for_each_unknown_model(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="src.cost"):
            compute_cost_usd("claude-experimental-x", _usage(input_tokens=100))
            compute_cost_usd("claude-experimental-y", _usage(input_tokens=100))
        warnings = [r for r in caplog.records if "No pricing entry" in r.getMessage()]
        assert len(warnings) == 2

    def test_known_model_does_not_warn(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="src.cost"):
            compute_cost_usd("claude-sonnet-4-6", _usage(input_tokens=100))
        assert not caplog.records
