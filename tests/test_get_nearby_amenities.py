"""Tests for the OSM Overpass amenities tool.

Mocked via pytest_httpx using a real Overpass response captured from a Wola
coordinate (52.2363, 20.9709). The fixture has 53 elements covering all five
amenity kinds — gives the categoriser, distance maths, and dedupe a realistic
exercise without hitting the live API in CI.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from src.tools.get_nearby_amenities import (
    _PLATFORM_SUFFIX_RE,
    _categorise,
    _haversine_m,
    get_nearby_amenities,
)

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "overpass_wola.json").read_text())

# Subject coords used to capture the fixture — distance assertions rely on these.
_LAT = 52.2363
_LON = 20.9709


class TestHaversine:
    def test_zero_distance_to_self(self) -> None:
        assert _haversine_m(52.0, 21.0, 52.0, 21.0) == 0

    def test_known_distance(self) -> None:
        # ~1.11 km per 0.01 degree latitude near Warsaw — sanity check.
        d = _haversine_m(52.2363, 20.9709, 52.2453, 20.9709)
        assert 990 <= d <= 1010


class TestCategorise:
    """Priority order: subway > tram > bus > school > park.
    Interchange nodes assign to highest-priority mode the tenant cares about."""

    def test_subway_wins_over_tram(self) -> None:
        # An interchange node with both subway + tram tags should count as subway.
        assert _categorise({"station": "subway", "tram": "yes"}) == "subway"
        assert _categorise({"subway": "yes", "highway": "bus_stop"}) == "subway"

    def test_tram_wins_over_bus(self) -> None:
        assert _categorise({"railway": "tram_stop", "bus": "yes"}) == "tram"

    def test_plain_bus(self) -> None:
        assert _categorise({"highway": "bus_stop"}) == "bus"
        assert _categorise({"public_transport": "stop_position", "bus": "yes"}) == "bus"

    def test_school(self) -> None:
        assert _categorise({"amenity": "school"}) == "school"

    def test_park(self) -> None:
        assert _categorise({"leisure": "park"}) == "park"

    def test_returns_none_for_unrecognised(self) -> None:
        # Café isn't in our five categories — silently dropped.
        assert _categorise({"amenity": "cafe"}) is None
        assert _categorise({}) is None


def test_platform_suffix_strip() -> None:
    """Warsaw stops are mapped per-direction with ' 01' / ' 02' suffixes;
    the dedupe key collapses them so the agent sees one location, not two."""
    assert _PLATFORM_SUFFIX_RE.sub("", "Leszno 01") == "Leszno"
    assert _PLATFORM_SUFFIX_RE.sub("", "Metro Płocka 08") == "Metro Płocka"
    # Don't eat trailing digits that ARE part of the name (e.g. street numbers)
    assert _PLATFORM_SUFFIX_RE.sub("", "Aleja 3 Maja") == "Aleja 3 Maja"


def test_returns_all_five_categories(httpx_mock: HTTPXMock) -> None:
    """Tool always returns all five categories, even if some are empty.
    Schema users (the agent) shouldn't have to handle missing keys."""
    httpx_mock.add_response(json=FIXTURE)
    result = get_nearby_amenities(latitude=_LAT, longitude=_LON, radius_m=500)
    # All five categories present; counts are non-negative ints
    for cat in (result.subway, result.tram, result.bus, result.school, result.park):
        assert cat.count >= 0
        assert isinstance(cat.nearest, list)


def test_real_fixture_parses_known_amenities(httpx_mock: HTTPXMock) -> None:
    """The fixture covers a busy Wola location — we expect non-trivial counts
    for transit, schools, and parks, and the closest park in the deduped
    nearest list should be 'Plac Opolski' (verified from raw fixture)."""
    httpx_mock.add_response(json=FIXTURE)
    result = get_nearby_amenities(latitude=_LAT, longitude=_LON, radius_m=500)

    assert result.tram.count > 0
    assert result.bus.count > 0
    assert result.school.count > 0
    assert result.park.count > 0

    # Closest park in the fixture is Plac Opolski.
    assert result.park.nearest
    assert result.park.nearest[0].name == "Plac Opolski"


def test_nearest_is_deduped_and_capped(httpx_mock: HTTPXMock) -> None:
    """Bus stops with ' 01' / ' 02' suffix should collapse; nearest list capped at 3."""
    httpx_mock.add_response(json=FIXTURE)
    result = get_nearby_amenities(latitude=_LAT, longitude=_LON, radius_m=500)

    for cat in (result.subway, result.tram, result.bus, result.school, result.park):
        assert len(cat.nearest) <= 3
        # No duplicate stripped names in the nearest list
        names = [_PLATFORM_SUFFIX_RE.sub("", n.name) for n in cat.nearest if n.name]
        assert len(names) == len(set(names))


def test_nearest_sorted_by_distance(httpx_mock: HTTPXMock) -> None:
    """Closest stops first — the agent's narrative should lead with 'X is 180m away'.
    Transit + parks fall within radius_m; schools within the wider school_radius_m."""
    httpx_mock.add_response(json=FIXTURE)
    result = get_nearby_amenities(latitude=_LAT, longitude=_LON, radius_m=500)

    # Small slack on the bound: OSM ways report a centroid, our distance is
    # straight-line to it, so an element near the edge can read slightly over.
    for cat in (result.tram, result.bus, result.park):
        distances = [a.distance_m for a in cat.nearest]
        assert distances == sorted(distances)
        for d in distances:
            assert d <= result.radius_m + 200

    school_distances = [a.distance_m for a in result.school.nearest]
    assert school_distances == sorted(school_distances)
    for d in school_distances:
        assert d <= result.school_radius_m + 200


def test_metadata_passes_through(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=FIXTURE)
    result = get_nearby_amenities(latitude=_LAT, longitude=_LON, radius_m=750)

    assert result.latitude == _LAT
    assert result.longitude == _LON
    assert result.radius_m == 750
    # 750 < 1200 floor, so schools widen to the catchment minimum.
    assert result.school_radius_m == 1200
    parsed = datetime.fromisoformat(result.fetched_at)
    assert parsed.utcoffset() is not None


def test_school_query_uses_wider_radius(httpx_mock: HTTPXMock) -> None:
    """The Overpass query must search schools at the wider catchment radius —
    a 500m disc misses schools in school-dense districts like Miasteczko Wilanów."""
    httpx_mock.add_response(json=FIXTURE)
    get_nearby_amenities(latitude=_LAT, longitude=_LON, radius_m=500)

    request = httpx_mock.get_request()
    assert request is not None
    body = request.read().decode()
    school_lines = [ln for ln in body.splitlines() if '"amenity"="school"' in ln]
    assert school_lines  # both the node and way school clauses
    for line in school_lines:
        assert "around:1200" in line
    # Transit clauses still use the tight 500m walkability radius.
    transit_lines = [ln for ln in body.splitlines() if '"highway"="bus_stop"' in ln]
    assert transit_lines
    for line in transit_lines:
        assert "around:500" in line


def test_school_radius_never_narrower_than_transit(httpx_mock: HTTPXMock) -> None:
    """A caller asking for a wide transit radius must not get a NARROWER school
    search — school_radius_m is max(radius_m, 1200)."""
    httpx_mock.add_response(json=FIXTURE)
    result = get_nearby_amenities(latitude=_LAT, longitude=_LON, radius_m=1500)

    assert result.radius_m == 1500
    assert result.school_radius_m == 1500


def test_empty_response_returns_zero_counts(httpx_mock: HTTPXMock) -> None:
    """Property in the middle of nowhere — Overpass returns no elements.
    Tool should return five empty categories, not crash."""
    httpx_mock.add_response(json={"elements": []})
    result = get_nearby_amenities(latitude=52.0, longitude=21.0)
    for cat in (result.subway, result.tram, result.bus, result.school, result.park):
        assert cat.count == 0
        assert cat.nearest == []


def test_sends_user_agent(httpx_mock: HTTPXMock) -> None:
    """Overpass returns 406 without a meaningful UA — verify we always send one."""
    httpx_mock.add_response(json=FIXTURE)
    get_nearby_amenities(latitude=_LAT, longitude=_LON)

    request = httpx_mock.get_request()
    assert request is not None
    ua = request.headers.get("User-Agent", "")
    assert ua
    assert ua != "python-httpx"


def test_propagates_overpass_errors(httpx_mock: HTTPXMock) -> None:
    """A 429 (Overpass rate limit) or 504 should propagate — the agent's
    _execute_tool wrapper turns it into an error string in the tool result,
    so the agent can mention 'amenity data unavailable' rather than hide it."""
    import httpx

    httpx_mock.add_response(status_code=429, text="Too Many Requests")
    with pytest.raises(httpx.HTTPStatusError):
        get_nearby_amenities(latitude=_LAT, longitude=_LON)
