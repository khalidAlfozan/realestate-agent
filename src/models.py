"""Domain models — validated I/O boundaries for the tools.

We keep these in a single module because the same shapes are returned by
multiple tools (PropertyDetails by `get_property_details`, Comparable by
`find_comparable_properties`) and consumed by the agent loop. Centralising
the schema here makes the contract explicit.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Frozen(BaseModel):
    """Strict base: forbid extra fields, freeze instances after construction.

    Forbidding extras catches typos in field names at parse-time. Frozen
    instances make the agent loop's appended messages safe to share.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class Address(_Frozen):
    street: str | None = None
    district: str | None = None
    subdistrict: str | None = None
    city: str | None = None
    province: str | None = None
    postal_code: str | None = None


class Coordinates(_Frozen):
    latitude: float | None = None
    longitude: float | None = None


class PropertyDetails(_Frozen):
    """Full data extracted from a single Otodom listing page."""

    url: str
    id: str
    title: str | None = None

    price_pln: int | None = None
    price_per_m2_pln: int | None = None
    monthly_community_fee_pln: int | None = None

    surface_m2: float | None = None
    rooms: int | None = None
    floor: str | None = None
    total_floors: int | None = None
    build_year: int | None = None
    building_type: str | None = None
    building_material: str | None = None
    construction_status: str | None = None
    windows_type: str | None = None
    heating: str | None = None
    ownership_form: str | None = None
    market: str | None = None
    free_from: str | None = None

    address: Address
    coordinates: Coordinates

    amenities: list[str] = []
    description_pl: str | None = None
    image_urls: list[str] = []
    advert_type: str | None = None
    created_at: str | None = None


class Comparable(_Frozen):
    """A single comparable from an Otodom search result."""

    id: str
    url: str
    title: str | None = None

    monthly_rent_pln: int | None = None
    monthly_community_fee_pln: int | None = None
    pln_per_m2_rent: int | None = None
    surface_m2: float | None = None
    rooms: int | None = None
    floor: int | None = None
    is_private_owner: bool | None = None


class ComparablesResult(_Frozen):
    """Result of `find_comparable_properties` — comparables + summary stats.

    The summary statistics save the agent from having to compute statistics
    in prose. Median + p25/p75 over `pln_per_m2_rent` is more robust to
    outliers than a mean.
    """

    search_url: str
    transaction_type: Literal["rent", "sale"]
    district: str
    rooms_filter: list[int]
    surface_min_m2: float
    surface_max_m2: float

    count: int
    comparables: list[Comparable]

    median_rent_pln: int | None = None
    median_pln_per_m2: int | None = None
    p25_pln_per_m2: int | None = None
    p75_pln_per_m2: int | None = None
