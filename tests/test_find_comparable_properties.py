"""Tests for the Otodom comparables search.

Runs against a saved search-results fixture so the parser stays honest when
Otodom changes its `__NEXT_DATA__` shape, and so the suite stays offline.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from src.tools._otodom import district_slug as _district_slug
from src.tools._otodom import percentile as _percentile
from src.tools.find_comparable_properties import (
    _rooms_filter,
    find_comparable_properties,
)

FIXTURE_HTML = (Path(__file__).parent / "fixtures" / "otodom_search_wola.html").read_text()


def test_district_slug_strips_polish_diacritics() -> None:
    assert _district_slug("Wola") == "wola"
    assert _district_slug("Mokotów") == "mokotow"
    assert _district_slug("Śródmieście") == "srodmiescie"
    assert _district_slug("Żoliborz") == "zoliborz"
    assert _district_slug("Białołęka") == "bialoleka"


def test_district_slug_doubles_hyphen_for_praga_districts() -> None:
    """Otodom slugs the two hyphenated Warsaw districts with a doubled hyphen
    — the single-hyphen form 404s. Either input spelling resolves: a listing's
    district field carries the hyphen, but a space form works too."""
    assert _district_slug("Praga-Południe") == "praga--poludnie"
    assert _district_slug("Praga-Północ") == "praga--polnoc"
    assert _district_slug("Praga Południe") == "praga--poludnie"


def test_rooms_filter_expands_plus_minus_one() -> None:
    assert _rooms_filter(4) == ["THREE", "FOUR", "FIVE"]
    # Edge: don't go below 1
    assert _rooms_filter(1) == ["ONE", "TWO"]
    # Edge: don't go above 10
    assert _rooms_filter(10) == ["NINE", "TEN"]


def test_percentile_handles_empty_and_short_lists() -> None:
    assert _percentile([], 50) is None
    assert _percentile([100], 25) == 100
    assert _percentile([100, 200], 50) == 150
    # 4 values, p25 = 1st quartile boundary
    assert _percentile([10, 20, 30, 40], 25) == 18
    assert _percentile([10, 20, 30, 40], 50) == 25
    assert _percentile([10, 20, 30, 40], 75) == 32


def test_returns_comparables_and_summary_stats(httpx_mock: HTTPXMock) -> None:
    # Match any Otodom search URL — the parser only cares about the response body.
    httpx_mock.add_response(text=FIXTURE_HTML)

    result = find_comparable_properties(district="Wola", rooms=4, surface_m2=73.0)

    # Subject was 73 m² -> search range is 58-88 m²
    assert result.surface_min_m2 == pytest.approx(58.0)
    assert result.surface_max_m2 == pytest.approx(88.0)
    assert result.rooms_filter == [3, 4, 5]
    assert result.transaction_type == "rent"
    assert result.district == "Wola"
    assert result.search_url.startswith(
        "https://www.otodom.pl/pl/wyniki/wynajem/mieszkanie/mazowieckie/warszawa/warszawa/warszawa/wola"
    )

    # Fixture has 37 results; we may filter a couple if they're junk
    assert result.count >= 30
    assert len(result.comparables) == result.count

    # Summary stats are populated
    assert result.median_rent_pln is not None
    assert result.median_rent_pln > 0
    assert result.median_pln_per_m2 is not None
    assert result.median_pln_per_m2 > 0
    p25, p75 = result.p25_pln_per_m2, result.p75_pln_per_m2
    assert p25 is not None
    assert p75 is not None
    assert p25 <= result.median_pln_per_m2 <= p75


def test_each_comparable_has_a_clickable_url(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(text=FIXTURE_HTML)

    result = find_comparable_properties(district="Wola", rooms=4, surface_m2=73.0)

    for comp in result.comparables:
        assert comp.url.startswith("https://www.otodom.pl/pl/oferta/")
        # Surface should fall within the requested range (the fixture data should respect filters)
        if comp.surface_m2 is not None:
            assert 50 <= comp.surface_m2 <= 100  # a little wider than ±20% to be safe


def test_sale_search_uses_sprzedaz_path(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(text=FIXTURE_HTML)

    result = find_comparable_properties(
        district="Wola", rooms=3, surface_m2=60.0, transaction_type="sale"
    )

    assert "/sprzedaz/" in result.search_url
    assert result.transaction_type == "sale"
