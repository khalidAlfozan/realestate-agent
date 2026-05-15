"""Tests for the GUS BDL demographics tool.

The BDL API is mocked via pytest_httpx — three sequential GETs per tool
invocation (one per variable). Tests cover happy path, missing-data
graceful degradation, unknown-district guard, and that the X-ClientId
header is sent.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
import pytest
from pytest_httpx import HTTPXMock

from src.tools.get_district_demographics import (
    DZIELNICA_UNIT_IDS,
    _fetch_latest_value,
    get_district_demographics,
)


def _bdl_response(values: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a minimal BDL data/by-unit response payload."""
    return {
        "totalRecords": 1,
        "page": 0,
        "pageSize": 100,
        "results": [{"id": "071412865188", "name": "Wola - dzielnica", "values": values}],
    }


def test_dzielnica_table_covers_all_18_districts() -> None:
    """If a refactor accidentally drops a district from the table, the agent
    will start failing for any listing in that dzielnica — catch it here."""
    assert len(DZIELNICA_UNIT_IDS) == 18
    expected = {
        "Bemowo",
        "Białołęka",
        "Bielany",
        "Mokotów",
        "Ochota",
        "Praga-Południe",
        "Praga-Północ",
        "Rembertów",
        "Śródmieście",
        "Targówek",
        "Ursus",
        "Ursynów",
        "Wawer",
        "Wesoła",
        "Wilanów",
        "Włochy",
        "Wola",
        "Żoliborz",
    }
    assert set(DZIELNICA_UNIT_IDS) == expected


def test_unknown_district_raises_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Agent should never get back a silent zero for a typo'd district name."""
    monkeypatch.setenv("GUS_BDL_API_KEY", "fake-key-for-test")
    with pytest.raises(ValueError, match="Unknown Warsaw district"):
        get_district_demographics("Atlantis")


def test_fetch_latest_picks_most_recent_year(httpx_mock: HTTPXMock) -> None:
    """When BDL returns multiple years, we want the freshest — not the first."""
    httpx_mock.add_response(
        json=_bdl_response(
            [
                {"year": 2021, "val": 100000.0, "attrId": 0, "attribute": ""},
                {"year": 2023, "val": 145000.0, "attrId": 0, "attribute": ""},
                {"year": 2022, "val": 120000.0, "attrId": 0, "attribute": ""},
            ]
        )
    )
    val, year = _fetch_latest_value("071412865188", 72305, "fake-key")
    assert val == 145000.0
    assert year == 2023


def test_fetch_latest_handles_empty_results(httpx_mock: HTTPXMock) -> None:
    """BDL returns an empty results array for unit/variable combos with no data."""
    httpx_mock.add_response(json={"totalRecords": 0, "page": 0, "pageSize": 100, "results": []})
    val, year = _fetch_latest_value("071412865188", 99999, "fake-key")
    assert val is None
    assert year is None


def test_fetch_latest_handles_404(httpx_mock: HTTPXMock) -> None:
    """If BDL doesn't recognise the variable for this unit, treat as missing data
    rather than raising — agent's memo just skips that line."""
    httpx_mock.add_response(status_code=404, text="Not Found")
    val, year = _fetch_latest_value("071412865188", 99999, "fake-key")
    assert val is None
    assert year is None


def test_returns_full_demographics_on_happy_path(
    httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three GETs (population, dwellings, net migration) → one DistrictDemographics.
    Year comes back from the live API as a STRING ('2024'), not int — fixture
    mirrors that to keep the test honest."""
    monkeypatch.setenv("GUS_BDL_API_KEY", "fake-key-for-test")
    httpx_mock.add_response(json=_bdl_response([{"year": "2024", "val": 145000, "attrId": 1}]))
    httpx_mock.add_response(json=_bdl_response([{"year": "2024", "val": 109194, "attrId": 1}]))
    httpx_mock.add_response(json=_bdl_response([{"year": "2024", "val": 408, "attrId": 1}]))

    result = get_district_demographics("Wola")

    assert result.district == "Wola"
    assert result.bdl_unit_id == "071412865188"
    assert result.population == 145000
    assert result.population_year == 2024
    assert result.dwellings == 109194
    assert result.dwellings_year == 2024
    assert result.net_migration == 408
    assert result.net_migration_year == 2024

    parsed_at = datetime.fromisoformat(result.fetched_at)
    assert parsed_at.utcoffset() is not None


def test_negative_net_migration_is_preserved(
    httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A shrinking dzielnica returns a negative migration balance — sign matters
    for the memo's tenant-pool reasoning, so don't accidentally clamp at zero."""
    monkeypatch.setenv("GUS_BDL_API_KEY", "fake-key-for-test")
    httpx_mock.add_response(json=_bdl_response([{"year": "2024", "val": 30000, "attrId": 1}]))
    httpx_mock.add_response(json=_bdl_response([{"year": "2024", "val": 12000, "attrId": 1}]))
    httpx_mock.add_response(json=_bdl_response([{"year": "2024", "val": -185, "attrId": 1}]))

    result = get_district_demographics("Rembertów")
    assert result.net_migration == -185


def test_partial_data_returns_nones_for_missing_fields(
    httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If BDL has no dwellings data for a particular dzielnica, that field is None
    and the memo skips it — but the call still succeeds and returns the
    other variables."""
    monkeypatch.setenv("GUS_BDL_API_KEY", "fake-key-for-test")
    httpx_mock.add_response(json=_bdl_response([{"year": "2024", "val": 50000, "attrId": 1}]))
    httpx_mock.add_response(json={"totalRecords": 0, "page": 0, "pageSize": 100, "results": []})
    httpx_mock.add_response(status_code=404, text="Not Found")

    result = get_district_demographics("Wesoła")

    assert result.population == 50000
    assert result.dwellings is None
    assert result.dwellings_year is None
    assert result.net_migration is None
    assert result.net_migration_year is None


def test_sends_x_clientid_header_on_each_request(
    httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without X-ClientId, BDL applies stricter rate limits — verify we're not
    accidentally calling unauthenticated."""
    monkeypatch.setenv("GUS_BDL_API_KEY", "verify-this-key")
    for _ in range(3):
        httpx_mock.add_response(
            json=_bdl_response([{"year": 2023, "val": 1.0, "attrId": 0, "attribute": ""}])
        )

    get_district_demographics("Mokotów")

    requests = httpx_mock.get_requests()
    assert len(requests) == 3
    for req in requests:
        assert req.headers.get("X-ClientId") == "verify-this-key"


def test_missing_api_key_raises_helpful_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Surface 'register at api.stat.gov.pl' rather than an opaque 401."""
    monkeypatch.delenv("GUS_BDL_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GUS_BDL_API_KEY is not set"):
        get_district_demographics("Wola")


def test_propagates_unexpected_http_errors(
    httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 500 from BDL should propagate (not silently degrade) — the agent's
    _execute_tool wrapper turns it into an error message in the tool result,
    which the model can then mention in §2 of the memo. Silent zeros would
    be worse."""
    monkeypatch.setenv("GUS_BDL_API_KEY", "fake-key")
    httpx_mock.add_response(status_code=500, text="Internal Server Error")
    with pytest.raises(httpx.HTTPStatusError):
        get_district_demographics("Wola")
