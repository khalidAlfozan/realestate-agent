"""Tests for the Otodom listing parser.

Runs against a saved HTML fixture (`fixtures/otodom_wola.html` — a minimal
shell wrapping the real `__NEXT_DATA__` payload from one Wola listing) so
the parser keeps working when Otodom changes their schema, and so this
test suite stays offline.
"""

from __future__ import annotations

from pathlib import Path

from pytest_httpx import HTTPXMock

from src.tools.get_property_details import get_property_details

FIXTURE_URL = "https://www.otodom.pl/pl/oferta/test-fixture-wola"
FIXTURE_HTML = (Path(__file__).parent / "fixtures" / "otodom_wola.html").read_text()


def test_parses_headline_fields(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=FIXTURE_URL, text=FIXTURE_HTML)

    result = get_property_details(FIXTURE_URL)

    assert result["price_pln"] == 1_290_000
    assert result["surface_m2"] == 73.0
    assert result["rooms"] == 4
    assert result["address"]["district"] == "Wola"
    assert result["address"]["city"] == "Warszawa"
    assert result["address"]["province"] == "mazowieckie"


def test_parses_polish_specific_fields(httpx_mock: HTTPXMock) -> None:
    """Fields that don't exist on Fotocasa but matter for Warsaw analysis."""
    httpx_mock.add_response(url=FIXTURE_URL, text=FIXTURE_HTML)

    result = get_property_details(FIXTURE_URL)

    assert result["monthly_community_fee_pln"] == 930
    assert result["ownership_form"] == "limited_ownership"
    assert result["heating"] == "urban"
    assert result["building_material"] == "brick"
    assert result["build_year"] == 1959
    assert result["floor"] == "ground_floor"
    assert result["market"] == "secondary"


def test_extracts_image_urls(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=FIXTURE_URL, text=FIXTURE_HTML)

    result = get_property_details(FIXTURE_URL)

    assert len(result["image_urls"]) == 18
    assert all(url.startswith("https://") for url in result["image_urls"])


def test_strips_html_from_description(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=FIXTURE_URL, text=FIXTURE_HTML)

    result = get_property_details(FIXTURE_URL)

    desc = result["description_pl"]
    assert "<p>" not in desc
    assert "</p>" not in desc
    # The substantive Polish text should still be there
    assert "Aktualnie mieszkanie zarezerwowane" in desc


def test_coordinates_are_floats(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=FIXTURE_URL, text=FIXTURE_HTML)

    result = get_property_details(FIXTURE_URL)

    lat = result["coordinates"]["latitude"]
    lon = result["coordinates"]["longitude"]
    assert isinstance(lat, float)
    assert isinstance(lon, float)
    # Sanity-check: Warsaw is roughly 52°N, 21°E
    assert 52.0 < lat < 52.5
    assert 20.5 < lon < 21.5


def test_raises_on_missing_next_data(httpx_mock: HTTPXMock) -> None:
    """If Otodom changes their SSR shape, fail loud, not silent."""
    import pytest

    httpx_mock.add_response(url=FIXTURE_URL, text="<html><body>no script tag here</body></html>")

    with pytest.raises(RuntimeError, match="__NEXT_DATA__"):
        get_property_details(FIXTURE_URL)
