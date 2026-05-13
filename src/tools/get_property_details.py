"""Tool: get_property_details(url) — fetch a Fotocasa listing and parse its embedded JSON."""
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
        "Fetch a Fotocasa property listing URL and return its structured data: "
        "price, surface (m²), bedrooms, bathrooms, floor, construction state, "
        "energy rating, full address (district, municipality, province), "
        "coordinates, agent description, amenities, and image URLs. "
        "Always call this first when analysing a property."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Full Fotocasa listing URL (e.g. https://www.fotocasa.es/.../d).",
            },
        },
        "required": ["url"],
        "additionalProperties": False,
    },
}


def get_property_details(url: str) -> dict[str, Any]:
    response = httpx.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
        },
        follow_redirects=True,
        timeout=15.0,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    raw = soup.find("script", id="__initial_props__")
    if raw is None or not raw.string:
        raise RuntimeError(
            "No __initial_props__ script tag found — Fotocasa page structure may have changed."
        )

    data = json.loads(raw.string)
    detail = data["realEstateAdDetailEntityV2"]
    real_estate = data["realEstate"]
    address = real_estate["address"]
    features = real_estate["features"]
    feats_named = {f["label"]: f["value"] for f in real_estate["featuresList"]}

    return {
        "url": url,
        "id": str(real_estate["id"]),
        "title": data.get("propertyTitle"),
        "price_eur": real_estate["price"],
        "surface_m2": features.get("surface"),
        "bedrooms": features.get("rooms"),
        "bathrooms": features.get("bathrooms"),
        "floor": feats_named.get("floor"),
        "antiquity": feats_named.get("antiquity"),
        "conservation_state": feats_named.get("conservationState"),
        "heating": feats_named.get("heating"),
        "hot_water": feats_named.get("hotWater"),
        "elevator": feats_named.get("elevator") == "YES",
        "furnished": feats_named.get("furnished") == "YES",
        "parking": feats_named.get("parking"),
        "typology": feats_named.get("typology"),
        "energy_rating": (detail.get("energyCertificate") or {}).get("energyEfficiencyRatingType"),
        "address": {
            "municipality": address.get("municipality"),
            "district": address.get("district"),
            "city": address.get("city"),
            "province": address.get("province"),
            "zip_code": address.get("zipCode"),
            "upper_level": address.get("upperLevel"),
        },
        "coordinates": {
            "latitude": real_estate["coordinates"]["latitude"],
            "longitude": real_estate["coordinates"]["longitude"],
        },
        "amenities": real_estate.get("extras", []),
        "description_es": (real_estate.get("descriptions") or {}).get("es-ES"),
        "image_urls": [m["src"] for m in real_estate.get("multimedia", []) if m.get("type") == "image"],
        "publisher_name": (detail.get("publisher") or {}).get("name"),
    }
