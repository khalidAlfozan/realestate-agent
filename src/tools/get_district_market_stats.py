"""Tool: get_district_market_stats — district-wide Otodom rent + sale snapshot.

Complements `find_comparable_properties`. That tool filters to the subject's
rooms/surface segment; this one returns the unfiltered district baseline.
The gap between segment-medians and district-medians lets the agent place
the subject within its district market (premium / mid / discount segment).

One tool call hits Otodom twice (rent + sale, sequential — only ~1.5s
wall clock, not worth threading). Both sides are returned together so the
agent doesn't need to orchestrate parallel calls; rent + sale stats are
inherently paired in the memo's market-context narrative.
"""

from __future__ import annotations

import json
import statistics
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
from anthropic.types import ToolParam
from bs4 import BeautifulSoup

from src.config import settings
from src.models import DistrictMarketSide, DistrictMarketStats
from src.tools._otodom import district_slug, percentile

# Single page is plenty for a stable median; 72 is the largest page size
# Otodom honours and avoids pagination logic entirely.
_PAGE_LIMIT = 72

SCHEMA: ToolParam = {
    "name": "get_district_market_stats",
    "description": (
        "Get district-wide Warsaw market stats from Otodom: median, p25, and p75 "
        "PLN/m² for both rent AND sale, plus total active listing counts (a supply "
        "signal). UNFILTERED by rooms/surface — this is the broader district "
        "baseline, not segment-specific. Use it alongside find_comparable_properties "
        "to judge whether the subject sits in a premium, mid, or discount segment "
        "within its district. One call returns both rent and sale sides."
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
        },
        "required": ["district"],
        "additionalProperties": False,
    },
}


def _build_search_url(slug: str, transaction_type: Literal["rent", "sale"]) -> str:
    base = (
        f"https://www.otodom.pl/pl/wyniki/"
        f"{'wynajem' if transaction_type == 'rent' else 'sprzedaz'}"
        f"/mieszkanie/mazowieckie/warszawa/warszawa/warszawa/{slug}"
    )
    params = {"limit": str(_PAGE_LIMIT)}
    return f"{base}?{urlencode(params)}"


def _fetch_search_data(url: str) -> dict[str, Any]:
    """Fetch one Otodom search page and return its parsed __NEXT_DATA__ block.

    Returns the searchAds dict (items + pagination + stats). Raises
    RuntimeError if the page structure changed (caught upstream, surfaced
    in the memo rather than crashing the loop).
    """
    response = httpx.get(
        url,
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
    return ((data.get("props") or {}).get("pageProps") or {}).get("data") or {}


def _summarise_side(search_url: str, search_ads: dict[str, Any]) -> DistrictMarketSide:
    items = search_ads.get("items") or []
    pln_per_m2: list[int] = []
    for item in items:
        v = (item.get("pricePerSquareMeter") or {}).get("value")
        if v is not None:
            pln_per_m2.append(int(v))

    total = (search_ads.get("pagination") or {}).get("totalItems")
    return DistrictMarketSide(
        search_url=search_url,
        sample_count=len(pln_per_m2),
        total_listings_in_district=int(total) if isinstance(total, int) else None,
        median_pln_per_m2=int(statistics.median(pln_per_m2)) if pln_per_m2 else None,
        p25_pln_per_m2=percentile(pln_per_m2, 25),
        p75_pln_per_m2=percentile(pln_per_m2, 75),
    )


def get_district_market_stats(district: str) -> DistrictMarketStats:
    slug = district_slug(district)

    rent_url = _build_search_url(slug, "rent")
    sale_url = _build_search_url(slug, "sale")

    rent_data = _fetch_search_data(rent_url)
    sale_data = _fetch_search_data(sale_url)

    rent_ads = rent_data.get("searchAds") or {}
    sale_ads = sale_data.get("searchAds") or {}

    return DistrictMarketStats(
        district=district,
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
        rent=_summarise_side(rent_url, rent_ads),
        sale=_summarise_side(sale_url, sale_ads),
    )
