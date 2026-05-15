"""Tool: get_nearby_amenities — transit / schools / parks within walking
distance of a property, via OpenStreetMap Overpass API.

Property-level (lat/lon) instead of district-level — transit signal is
much stronger for a specific address ("180m from Metro Płocka") than
for a district average. The subject's coordinates are already in
PropertyDetails.coordinates from get_property_details.

Why OSM and not the Warsaw municipal API: api.um.warszawa.pl is geo-blocked
outside Poland. CI on US runners and reviewers cloning the repo from
anywhere outside PL would all hit a wall. OSM has identical Warsaw coverage
for transit/schools/parks (well-tagged thanks to the active PL OSM
community), no key, globally reachable.

One Overpass query per call. The query covers all five amenity kinds
in a single round-trip. Results are categorised into subway / tram /
bus / school / park by tag priority; an interchange node tagged for
both subway and tram counts as subway (highest priority).

Transit and parks are searched within the caller's `radius_m` (a
walkability distance); schools use a wider catchment radius, because a
500m disc systematically under-reports schools — a family will travel
further to a school than anyone walks to a tram stop. The two radii are
reported separately on the result.

Why a project-specific User-Agent: Overpass returns 406 Not Acceptable for
both empty and browser-looking UAs (it's an API for apps, not browsers).
We send an app-style UA that identifies the project per OSM etiquette.
"""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from anthropic.types import ToolParam

from src.config import settings
from src.models import AmenityCategory, NearbyAmenities, NearbyAmenity

# Default search radius. 500m ≈ 6-min walk — the standard "really walkable"
# threshold in walkability research. Agent can override (e.g. 800m for a
# more relaxed "general convenience" radius).
_DEFAULT_RADIUS_M = 500

# Schools are searched at a wider radius than transit / parks: a family
# routinely travels further to a school than anyone walks to a tram stop,
# so a 500m disc systematically under-reports schools (a school-dense
# district can show zero). Schools use max(radius_m, this) so a caller
# asking for a wide transit radius never gets a NARROWER school search.
_SCHOOL_MIN_RADIUS_M = 1200

# Cap on nearest examples per category — keeps the payload tight. The agent
# only needs the closest few of each kind, not every bus stop in a 500m disc.
_TOP_N_NEAREST = 3

# Strip trailing platform suffix from Warsaw stop names so 'Leszno 01' and
# 'Leszno 02' (two directions of the same stop) collapse into one entry in
# the nearest list. Match: optional space, 1-3 digits, end of string.
_PLATFORM_SUFFIX_RE = re.compile(r"\s+\d{1,3}$")

# Project-identifying User-Agent. Overpass rejects browser-looking UAs (the
# scraping.user_agent we send to Otodom would 406 here). OSM etiquette is
# to identify the app + a contact URL.
_OVERPASS_USER_AGENT = "realestate-agent (+https://github.com/khalidAlfozan/realestate-agent)"

_KIND = Literal["subway", "tram", "bus", "school", "park"]

SCHEMA: ToolParam = {
    "name": "get_nearby_amenities",
    "description": (
        "Get transit stops, schools, and parks within walking distance of a "
        "property, via OpenStreetMap. Returns five categories (subway, tram, "
        "bus, school, park), each with a count of OSM elements and the closest "
        "few named examples with their distance in metres from the subject. "
        "Transit and parks are searched within radius_m (a walkability "
        "distance); schools are searched at a wider catchment radius "
        "(reported separately as school_radius_m), since families travel "
        "further to a school than to a tram stop. Use for §2 (Neighbourhood "
        "context) to ground transit-access and walkability claims in concrete "
        "distances. Pass the subject's lat/lon from "
        "get_property_details.coordinates. Default radius 500m (~6-min walk); "
        "use 800-1000m for a more relaxed 'general convenience' assessment."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "latitude": {
                "type": "number",
                "description": "Subject property latitude (WGS84). From get_property_details.",
                "minimum": -90,
                "maximum": 90,
            },
            "longitude": {
                "type": "number",
                "description": "Subject property longitude (WGS84). From get_property_details.",
                "minimum": -180,
                "maximum": 180,
            },
            "radius_m": {
                "type": "integer",
                "description": (
                    "Search radius in metres. Default 500m ≈ 6-min walk. "
                    "Use 800-1000m for general convenience."
                ),
                "minimum": 100,
                "maximum": 2000,
                "default": _DEFAULT_RADIUS_M,
            },
        },
        "required": ["latitude", "longitude"],
        "additionalProperties": False,
    },
}


def _build_query(latitude: float, longitude: float, radius_m: int, school_radius_m: int) -> str:
    """One Overpass query covering all five amenity kinds.

    Transit + parks use `radius_m`; the two school clauses use the wider
    `school_radius_m`. We query both `node` and `way`/`relation` for
    amenity=school and leisure=park because these are often mapped as
    polygons (ways) rather than points. `out center tags` returns a centroid
    for ways/relations so we can compute distance the same way as for nodes.
    """
    return f"""[out:json][timeout:25];
(
  node(around:{radius_m},{latitude},{longitude})["public_transport"="stop_position"];
  node(around:{radius_m},{latitude},{longitude})["highway"="bus_stop"];
  node(around:{radius_m},{latitude},{longitude})["railway"="tram_stop"];
  node(around:{radius_m},{latitude},{longitude})["station"="subway"];
  node(around:{radius_m},{latitude},{longitude})["railway"="subway_entrance"];
  node(around:{school_radius_m},{latitude},{longitude})["amenity"="school"];
  way(around:{school_radius_m},{latitude},{longitude})["amenity"="school"];
  way(around:{radius_m},{latitude},{longitude})["leisure"="park"];
  relation(around:{radius_m},{latitude},{longitude})["leisure"="park"];
);
out center tags;
"""


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """Great-circle distance in metres. Standard haversine; rounded to int."""
    r = 6_371_000  # Earth radius in metres
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)))


def _categorise(tags: dict[str, str]) -> _KIND | None:
    """Map OSM tags to one of our five kinds, by priority.

    Priority: subway > tram > bus > school > park. An interchange node
    tagged for both subway and tram counts as subway — the highest-tier
    transit a tenant cares about at this location.
    """
    if (
        tags.get("station") == "subway"
        or tags.get("railway") == "subway_entrance"
        or tags.get("subway") == "yes"
    ):
        return "subway"
    if tags.get("railway") == "tram_stop" or tags.get("tram") == "yes":
        return "tram"
    if tags.get("highway") == "bus_stop" or tags.get("bus") == "yes":
        return "bus"
    if tags.get("amenity") == "school":
        return "school"
    if tags.get("leisure") == "park":
        return "park"
    return None


def _element_coords(element: dict[str, Any]) -> tuple[float, float] | None:
    """Pull coordinates from an OSM element. Nodes have lat/lon directly;
    ways/relations have them in a `center` block when queried with `out center`."""
    if "lat" in element and "lon" in element:
        return (float(element["lat"]), float(element["lon"]))
    center = element.get("center") or {}
    if "lat" in center and "lon" in center:
        return (float(center["lat"]), float(center["lon"]))
    return None


def _dedupe_by_stripped_name(amenities: list[NearbyAmenity]) -> list[NearbyAmenity]:
    """Collapse 'Leszno 01' / 'Leszno 02' into one entry, keeping the closest."""
    seen: dict[str, NearbyAmenity] = {}
    for a in amenities:
        key = _PLATFORM_SUFFIX_RE.sub("", a.name) if a.name else f"_unnamed_{a.lat}_{a.lon}"
        if key not in seen or a.distance_m < seen[key].distance_m:
            seen[key] = a
    return sorted(seen.values(), key=lambda x: x.distance_m)


def _build_category(
    elements: list[dict[str, Any]],
    subject_lat: float,
    subject_lon: float,
) -> AmenityCategory:
    """Turn a flat list of (already-categorised) OSM elements into an AmenityCategory.

    `count` is raw OSM count (so bus stops with separate platforms-by-direction
    are counted separately, as they really are distinct OSM nodes). `nearest` is
    deduped by name and capped at _TOP_N_NEAREST.
    """
    amenities: list[NearbyAmenity] = []
    for el in elements:
        coords = _element_coords(el)
        if coords is None:
            continue
        lat, lon = coords
        amenities.append(
            NearbyAmenity(
                name=(el.get("tags") or {}).get("name"),
                distance_m=_haversine_m(subject_lat, subject_lon, lat, lon),
                lat=lat,
                lon=lon,
            )
        )

    deduped = _dedupe_by_stripped_name(amenities)
    return AmenityCategory(count=len(elements), nearest=deduped[:_TOP_N_NEAREST])


def get_nearby_amenities(
    latitude: float,
    longitude: float,
    radius_m: int = _DEFAULT_RADIUS_M,
) -> NearbyAmenities:
    # Schools get a wider catchment, but never narrower than the transit radius.
    school_radius_m = max(radius_m, _SCHOOL_MIN_RADIUS_M)
    response = httpx.post(
        settings.overpass.base_url,
        content=_build_query(latitude, longitude, radius_m, school_radius_m),
        headers={
            "User-Agent": _OVERPASS_USER_AGENT,
            "Content-Type": "text/plain",
        },
        timeout=settings.overpass.request_timeout_s,
    )
    response.raise_for_status()
    payload: dict[str, Any] = response.json()
    elements: list[dict[str, Any]] = payload.get("elements") or []

    by_kind: dict[_KIND, list[dict[str, Any]]] = {
        "subway": [],
        "tram": [],
        "bus": [],
        "school": [],
        "park": [],
    }
    for el in elements:
        kind = _categorise(el.get("tags") or {})
        if kind is not None:
            by_kind[kind].append(el)

    return NearbyAmenities(
        latitude=latitude,
        longitude=longitude,
        radius_m=radius_m,
        school_radius_m=school_radius_m,
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
        subway=_build_category(by_kind["subway"], latitude, longitude),
        tram=_build_category(by_kind["tram"], latitude, longitude),
        bus=_build_category(by_kind["bus"], latitude, longitude),
        school=_build_category(by_kind["school"], latitude, longitude),
        park=_build_category(by_kind["park"], latitude, longitude),
    )
