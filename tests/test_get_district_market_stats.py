"""Tests for the Otodom district-wide market-stats tool.

Reuses the same saved Otodom search-results fixture as the comparables tests
— the __NEXT_DATA__ shape is identical, only the filters in the URL differ.
The tool fires two HTTP calls (rent + sale); we register a fixture response
for each.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from pytest_httpx import HTTPXMock

from src.tools.get_district_market_stats import (
    _build_search_url,
    _summarise_side,
    get_district_market_stats,
)

FIXTURE_HTML = (Path(__file__).parent / "fixtures" / "otodom_search_wola.html").read_text()


def test_rent_url_uses_wynajem_path_and_no_room_filter() -> None:
    url = _build_search_url("wola", "rent")
    assert "/wynajem/" in url
    assert "wola" in url
    assert "roomsNumber" not in url
    assert "areaMin" not in url


def test_sale_url_uses_sprzedaz_path() -> None:
    url = _build_search_url("mokotow", "sale")
    assert "/sprzedaz/" in url
    assert "mokotow" in url
    assert "roomsNumber" not in url


def test_summarise_side_handles_empty_searchads() -> None:
    side = _summarise_side("https://example/", {})
    assert side.sample_count == 0
    assert side.median_pln_per_m2 is None
    assert side.p25_pln_per_m2 is None
    assert side.p75_pln_per_m2 is None
    assert side.total_listings_in_district is None


def test_returns_both_sides_with_stats(httpx_mock: HTTPXMock) -> None:
    """Tool fires two GETs (rent + sale); both should be summarised and the
    pagination.totalItems supply signal should be surfaced."""
    # Two responses: tool calls rent first, then sale (sequential)
    httpx_mock.add_response(text=FIXTURE_HTML)
    httpx_mock.add_response(text=FIXTURE_HTML)

    result = get_district_market_stats(district="Wola")

    assert result.district == "Wola"

    # Both sides got real data from the fixture
    for side in (result.rent, result.sale):
        assert side.sample_count > 0
        assert side.median_pln_per_m2 is not None
        assert side.median_pln_per_m2 > 0
        assert side.p25_pln_per_m2 is not None
        assert side.p75_pln_per_m2 is not None
        assert side.p25_pln_per_m2 <= side.median_pln_per_m2 <= side.p75_pln_per_m2
        # Fixture pagination.totalItems = 241
        assert side.total_listings_in_district == 241

    assert "/wynajem/" in result.rent.search_url
    assert "/sprzedaz/" in result.sale.search_url


def test_fetched_at_is_iso_utc(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(text=FIXTURE_HTML)
    httpx_mock.add_response(text=FIXTURE_HTML)

    result = get_district_market_stats(district="Wola")

    # ISO 8601 with timezone (UTC offset present); parseable.
    parsed = datetime.fromisoformat(result.fetched_at)
    assert parsed.utcoffset() is not None
    # Timestamp is to-the-second precision (no microseconds noise in logs)
    assert not re.search(r"\.\d", result.fetched_at)


def test_diacritics_in_district_are_slugged(httpx_mock: HTTPXMock) -> None:
    """A district like 'Mokotów' must hit the URL as 'mokotow' on both sides."""
    httpx_mock.add_response(text=FIXTURE_HTML)
    httpx_mock.add_response(text=FIXTURE_HTML)

    result = get_district_market_stats(district="Mokotów")

    assert "mokotow" in result.rent.search_url
    assert "mokotow" in result.sale.search_url
    # The echoed district preserves the user's casing/diacritics for the memo
    assert result.district == "Mokotów"
