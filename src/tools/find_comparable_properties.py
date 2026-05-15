"""Tool: find_comparable_properties — search Otodom for comparable rentals/sales."""

from __future__ import annotations

import json
import statistics
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
from anthropic.types import ToolParam
from bs4 import BeautifulSoup

from src.config import settings
from src.models import Comparable, ComparablesResult

# Otodom's roomsNumber filter takes an enum of word-form room counts.
_ROOM_ENUMS = ["", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE", "TEN"]

# Diacritic-stripping table for Polish district slugs (lowercase only).
_PL_DIACRITICS = str.maketrans(
    {"ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n", "ó": "o", "ś": "s", "ź": "z", "ż": "z"}
)

SCHEMA: ToolParam = {
    "name": "find_comparable_properties",
    "description": (
        "Search Otodom for comparable Warsaw properties of the same transaction "
        "type (rent or sale), in the same district, with similar room count "
        "(±1) and surface (±20%). Returns up to ~36 listings plus median/p25/p75 "
        "PLN/m² statistics. Call TWICE per memo: once with transaction_type='rent' "
        "(to ground the monthly-rent estimate that drives yield) and once with "
        "transaction_type='sale' (to judge whether the asking price is fair vs "
        "the local market). Both calls are independent and should run in parallel."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "district": {
                "type": "string",
                "description": (
                    "Warsaw district name (e.g. 'Wola', 'Mokotów', 'Śródmieście'). "
                    "Pass it exactly as it appears in get_property_details' address.district."
                ),
            },
            "rooms": {
                "type": "integer",
                "description": "Room count of the subject property. Search expands ±1.",
                "minimum": 1,
                "maximum": 10,
            },
            "surface_m2": {
                "type": "number",
                "description": "Surface of the subject property in m². Search expands ±20%.",
                "exclusiveMinimum": 0,
            },
            "transaction_type": {
                "type": "string",
                "enum": ["rent", "sale"],
                "description": "Whether to search for rentals or sales. Default: rent.",
                "default": "rent",
            },
        },
        "required": ["district", "rooms", "surface_m2"],
        "additionalProperties": False,
    },
}


def _district_slug(name: str) -> str:
    """Normalise a Warsaw district name to its Otodom URL slug."""
    return name.lower().translate(_PL_DIACRITICS).replace(" ", "-")


def _rooms_filter(rooms: int) -> list[str]:
    """Build the ±1 room range for the Otodom roomsNumber enum."""
    lo = max(1, rooms - 1)
    hi = min(10, rooms + 1)
    return [_ROOM_ENUMS[r] for r in range(lo, hi + 1)]


def _parse_rooms_enum(s: str | None) -> int | None:
    """Reverse-map Otodom's room enum string to an integer."""
    if not s:
        return None
    try:
        return _ROOM_ENUMS.index(s)
    except ValueError:
        return None


def _percentile(values: list[int], p: float) -> int | None:
    """p-th percentile (linear interpolation) of a non-empty list. None if empty."""
    if not values:
        return None
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (p / 100)
    lo, hi = int(k), int(k) + 1
    if hi >= len(sorted_vals):
        return sorted_vals[-1]
    return round(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo))


def _build_search_url(
    district_slug: str,
    transaction_type: Literal["rent", "sale"],
    rooms_enum: list[str],
    surface_min: int,
    surface_max: int,
    limit: int,
) -> str:
    base = (
        f"https://www.otodom.pl/pl/wyniki/"
        f"{'wynajem' if transaction_type == 'rent' else 'sprzedaz'}"
        f"/mieszkanie/mazowieckie/warszawa/warszawa/warszawa/{district_slug}"
    )
    params = {
        "roomsNumber": "[" + ",".join(rooms_enum) + "]",
        "areaMin": str(surface_min),
        "areaMax": str(surface_max),
        "limit": str(limit),
    }
    return f"{base}?{urlencode(params, safe='[],')}"


def _parse_comparable(item: dict[str, Any]) -> Comparable | None:
    """Extract one Comparable from an Otodom search-result item, or None if junk."""
    listing_id = item.get("id")
    slug = item.get("slug")
    if not listing_id or not slug:
        return None

    total_price = (item.get("totalPrice") or {}).get("value")
    rent_price = (item.get("rentPrice") or {}).get("value")  # czynsz, despite the name
    pln_per_m2 = (item.get("pricePerSquareMeter") or {}).get("value")

    return Comparable(
        id=str(listing_id),
        url=f"https://www.otodom.pl/pl/oferta/{slug}",
        title=item.get("title"),
        monthly_rent_pln=int(total_price) if total_price else None,
        monthly_community_fee_pln=int(rent_price) if rent_price else None,
        pln_per_m2_rent=int(pln_per_m2) if pln_per_m2 else None,
        surface_m2=float(item["areaInSquareMeters"]) if item.get("areaInSquareMeters") else None,
        rooms=_parse_rooms_enum(item.get("roomsNumber")),
        floor=item.get("floorNumber") if isinstance(item.get("floorNumber"), int) else None,
        is_private_owner=item.get("isPrivateOwner"),
    )


def find_comparable_properties(
    district: str,
    rooms: int,
    surface_m2: float,
    transaction_type: Literal["rent", "sale"] = "rent",
) -> ComparablesResult:
    surface_min = round(surface_m2 * 0.8)
    surface_max = round(surface_m2 * 1.2)
    rooms_enum = _rooms_filter(rooms)
    rooms_filter_ints = [_ROOM_ENUMS.index(e) for e in rooms_enum]
    district_slug = _district_slug(district)

    search_url = _build_search_url(
        district_slug, transaction_type, rooms_enum, surface_min, surface_max, limit=36
    )

    response = httpx.get(
        search_url,
        headers={
            "User-Agent": settings.scraping.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,pl;q=0.8",
        },
        follow_redirects=True,
        timeout=settings.scraping.request_timeout_s,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    raw = soup.find("script", id="__NEXT_DATA__")
    if raw is None or not raw.string:
        raise RuntimeError(
            "No __NEXT_DATA__ in Otodom search response — page structure may have changed."
        )

    data = json.loads(raw.string)
    page_props = data.get("props", {}).get("pageProps", {})
    items = ((page_props.get("data") or {}).get("searchAds") or {}).get("items") or []

    comparables: list[Comparable] = []
    for item in items:
        comp = _parse_comparable(item)
        if comp is not None:
            comparables.append(comp)

    rents = [c.monthly_rent_pln for c in comparables if c.monthly_rent_pln is not None]
    pln_per_m2 = [c.pln_per_m2_rent for c in comparables if c.pln_per_m2_rent is not None]

    return ComparablesResult(
        search_url=search_url,
        transaction_type=transaction_type,
        district=district,
        rooms_filter=rooms_filter_ints,
        surface_min_m2=float(surface_min),
        surface_max_m2=float(surface_max),
        count=len(comparables),
        comparables=comparables,
        median_rent_pln=int(statistics.median(rents)) if rents else None,
        median_pln_per_m2=int(statistics.median(pln_per_m2)) if pln_per_m2 else None,
        p25_pln_per_m2=_percentile(pln_per_m2, 25),
        p75_pln_per_m2=_percentile(pln_per_m2, 75),
    )
