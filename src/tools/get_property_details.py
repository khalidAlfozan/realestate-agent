"""Tool: get_property_details(url) — fetch an Otodom listing and parse its embedded JSON."""
from __future__ import annotations

import json
from typing import Any

import httpx
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

SCHEMA = {
    "name": "get_property_details",
    "description": (
        "Fetch an Otodom property listing URL and return its structured data: "
        "price (PLN), surface (m²), rooms, floor, build year, building type, "
        "ownership form, monthly community fee (czynsz administracyjny), "
        "heating type, full address (district, city), coordinates, agent "
        "description, amenities, and image URLs. Always call this first when "
        "analysing a Warsaw property."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Full Otodom listing URL (e.g. https://www.otodom.pl/pl/oferta/...).",
            },
        },
        "required": ["url"],
        "additionalProperties": False,
    },
}


def _to_int(v: Any) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _to_float(v: Any) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def get_property_details(url: str) -> dict[str, Any]:
    response = httpx.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,pl;q=0.8",
        },
        follow_redirects=True,
        timeout=15.0,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    raw = soup.find("script", id="__NEXT_DATA__")
    if raw is None or not raw.string:
        raise RuntimeError(
            "No __NEXT_DATA__ script tag found — Otodom page structure may have changed."
        )

    data = json.loads(raw.string)
    ad = data["props"]["pageProps"]["ad"]

    # Otodom keeps numeric data in a flat list of {key, value} dicts.
    chars = {c["key"]: c["value"] for c in (ad.get("characteristics") or [])}

    address = ((ad.get("location") or {}).get("address")) or {}
    coordinates = ((ad.get("location") or {}).get("coordinates")) or {}

    # Description ships as HTML — strip tags for clean text.
    description_text = BeautifulSoup(
        ad.get("description") or "", "html.parser"
    ).get_text(separator=" ", strip=True)

    return {
        "url": url,
        "id": str(ad["id"]),
        "title": ad.get("title"),
        "price_pln": _to_int(chars.get("price")),
        "price_per_m2_pln": _to_int(chars.get("price_per_m")),
        "monthly_community_fee_pln": _to_int(chars.get("rent")),
        "surface_m2": _to_float(chars.get("m")),
        "rooms": _to_int(chars.get("rooms_num")),
        "floor": chars.get("floor_no"),
        "total_floors": _to_int(chars.get("building_floors_num")),
        "build_year": _to_int(chars.get("build_year")),
        "building_type": chars.get("building_type"),
        "building_material": chars.get("building_material"),
        "construction_status": chars.get("construction_status"),
        "windows_type": chars.get("windows_type"),
        "heating": chars.get("heating"),
        "ownership_form": chars.get("building_ownership"),
        "market": chars.get("market"),
        "free_from": chars.get("free_from"),
        "address": {
            "street": ((address.get("street") or {}).get("name")),
            "district": ((address.get("district") or {}).get("name")),
            "subdistrict": ((address.get("subdistrict") or {}).get("name")) if address.get("subdistrict") else None,
            "city": ((address.get("city") or {}).get("name")),
            "province": ((address.get("province") or {}).get("name")),
            "postal_code": address.get("postalCode"),
        },
        "coordinates": {
            "latitude": coordinates.get("latitude"),
            "longitude": coordinates.get("longitude"),
        },
        "amenities": ad.get("features") or [],
        "description_pl": description_text,
        "image_urls": [
            img.get("large") for img in (ad.get("images") or []) if img.get("large")
        ],
        "advert_type": ad.get("advertType"),
        "created_at": ad.get("createdAt"),
    }
