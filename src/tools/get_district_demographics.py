"""Tool: get_district_demographics — Warsaw dzielnica stats from GUS BDL.

Pulls annual demographic context for one Warsaw district from Poland's
Central Statistical Office (Bank Danych Lokalnych): total population,
total housing stock, and net migration balance. All three are dzielnica-
level (BDL `levels: [6]`) so the numbers genuinely describe the district,
not Warsaw as a whole.

Note on what's NOT here: average wage and unemployment rate are both
published only at powiat (county) level — for Warsaw that means city-wide,
not per-dzielnica. We deliberately keep this tool dzielnica-specific;
Warsaw-level macro context comes from the agent's prior knowledge.

Three sequential API calls per invocation (one per variable). Hardcoded
unit and variable IDs: BDL search-by-name is ambiguous ("Wola" matches
multiple Polish towns), and BDL has no "list variables for unit" endpoint
to discover at runtime. The IDs here are stable TERYT/catalogue codes that
don't change.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from anthropic.types import ToolParam

from src.config import require_gus_bdl_api_key, settings
from src.models import DistrictDemographics

# 18 Warsaw dzielnice → BDL territorial-unit IDs. From the BDL units endpoint
# children-of M.st.Warszawa (071412865011). Stable codes; updating this map
# is a one-time exercise. The 19th sibling unit "GMINY-DZIELNICY WARSZAWY
# NIE USTALONO" (district unspecified) is intentionally excluded — it's a
# placeholder for unattributed records, not a real district.
DZIELNICA_UNIT_IDS: dict[str, str] = {
    "Bemowo": "071412865028",
    "Białołęka": "071412865038",
    "Bielany": "071412865048",
    "Mokotów": "071412865058",
    "Ochota": "071412865068",
    "Praga-Południe": "071412865078",
    "Praga-Północ": "071412865088",
    "Rembertów": "071412865098",
    "Śródmieście": "071412865108",
    "Targówek": "071412865118",
    "Ursus": "071412865128",
    "Ursynów": "071412865138",
    "Wawer": "071412865148",
    "Wesoła": "071412865158",
    "Wilanów": "071412865168",
    "Włochy": "071412865178",
    "Wola": "071412865188",
    "Żoliborz": "071412865198",
}

# BDL variable IDs, all confirmed dzielnica-available (subjects with levels:[6]):
#   72305   - Ludność, stan w dniu 31 XII (year-end population)
#   60811   - Zasoby mieszkaniowe / mieszkania ogółem (total dwellings)
#   1365234 - Migracje gminne / saldo migracji ogółem (net migration count)
# Comments record the BDL catalogue label so future maintainers can re-verify
# against bdl.stat.gov.pl. Updating these IDs is rare — BDL keeps catalogue
# codes stable across releases.
_VAR_POPULATION = 72305
_VAR_DWELLINGS = 60811
_VAR_NET_MIGRATION = 1365234

SCHEMA: ToolParam = {
    "name": "get_district_demographics",
    "description": (
        "Get annual dzielnica-level stats from Poland's Central Statistical Office "
        "(GUS BDL): year-end population, total housing stock (dwellings), and "
        "net migration balance (in-flows minus out-flows; positive = district is "
        "growing, negative = shrinking). Each field reports the year of the most "
        "recent observation. Wage and unemployment are deliberately NOT included "
        "(BDL only publishes them at city level, not per dzielnica). Use these in "
        "§2 (Neighbourhood context) to ground tenant-pool size, market depth, and "
        "demand-trend claims in authoritative data."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "district": {
                "type": "string",
                "description": (
                    "Warsaw district name in canonical Polish form: "
                    "'Wola', 'Mokotów', 'Śródmieście', 'Praga-Południe', 'Żoliborz', etc. "
                    "Pass exactly as it appears in get_property_details' address.district."
                ),
            },
        },
        "required": ["district"],
        "additionalProperties": False,
    },
}


def _fetch_latest_value(unit_id: str, var_id: int, api_key: str) -> tuple[float | None, int | None]:
    """Return (value, year) for the most recent observation of one variable.

    Returns (None, None) if BDL has no data for this (unit, variable) — a
    common case at dzielnica granularity for variables only published at
    higher aggregation levels.
    """
    response = httpx.get(
        f"{settings.gus_bdl.base_url}/data/by-unit/{unit_id}",
        params={"var-id": str(var_id), "format": "json", "page-size": "100"},
        headers={"X-ClientId": api_key},
        timeout=settings.gus_bdl.request_timeout_s,
    )
    if response.status_code == 404:
        return None, None
    response.raise_for_status()
    payload: dict[str, Any] = response.json()

    results = payload.get("results") or []
    if not results:
        return None, None
    values = results[0].get("values") or []
    if not values:
        return None, None

    latest = max(values, key=lambda v: v.get("year") or 0)
    val = latest.get("val")
    year = latest.get("year")
    return (
        (float(val) if val is not None else None),
        (int(year) if year is not None else None),
    )


def get_district_demographics(district: str) -> DistrictDemographics:
    unit_id = DZIELNICA_UNIT_IDS.get(district)
    if unit_id is None:
        raise ValueError(
            f"Unknown Warsaw district: {district!r}. Expected one of: {sorted(DZIELNICA_UNIT_IDS)}"
        )

    api_key = require_gus_bdl_api_key()

    population, population_year = _fetch_latest_value(unit_id, _VAR_POPULATION, api_key)
    dwellings, dwellings_year = _fetch_latest_value(unit_id, _VAR_DWELLINGS, api_key)
    net_migration, net_migration_year = _fetch_latest_value(
        unit_id, _VAR_NET_MIGRATION, api_key
    )

    return DistrictDemographics(
        district=district,
        bdl_unit_id=unit_id,
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
        population=int(population) if population is not None else None,
        population_year=population_year,
        dwellings=int(dwellings) if dwellings is not None else None,
        dwellings_year=dwellings_year,
        net_migration=int(net_migration) if net_migration is not None else None,
        net_migration_year=net_migration_year,
    )
