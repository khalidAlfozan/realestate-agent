"""Tests for the gross yield calculation tool."""

from __future__ import annotations

import pytest

from src.tools.calculate_gross_yield import calculate_gross_yield


def test_basic_yield() -> None:
    # 1.29M PLN at 6,250 PLN/month → 5.81% gross yield
    result = calculate_gross_yield(price_pln=1_290_000, monthly_rent_pln=6_250)
    assert result["annual_rent_pln"] == 75_000
    assert result["gross_yield_pct"] == 5.81


def test_rounds_to_two_decimals() -> None:
    """Yield is rounded for memo readability — verify the rounding behaviour."""
    result = calculate_gross_yield(price_pln=1_000_000, monthly_rent_pln=4_000)
    assert result["gross_yield_pct"] == 4.8  # 48,000 / 1,000,000 * 100 = 4.8


def test_handles_floats() -> None:
    result = calculate_gross_yield(price_pln=472_500.5, monthly_rent_pln=1_340.75)
    assert result["annual_rent_pln"] == pytest.approx(16_089.0)
    assert result["gross_yield_pct"] == 3.41
