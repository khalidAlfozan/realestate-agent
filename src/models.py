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


class DistrictMarketSide(_Frozen):
    """Stats for one side (rent or sale) of a district market snapshot."""

    search_url: str
    sample_count: int
    total_listings_in_district: int | None = None
    median_pln_per_m2: int | None = None
    p25_pln_per_m2: int | None = None
    p75_pln_per_m2: int | None = None


class DistrictMarketStats(_Frozen):
    """Result of `get_district_market_stats` — district-wide rent + sale snapshot.

    Distinct from `find_comparable_properties` (which filters to the subject's
    rooms/surface segment): this is the broader district baseline. The gap
    between this and the comp set tells the agent whether the subject sits in
    a premium or discount segment within its district. `total_listings_in_district`
    is a supply signal — deep markets compress yield, thin markets widen
    bid-ask spreads.
    """

    district: str
    fetched_at: str
    rent: DistrictMarketSide
    sale: DistrictMarketSide


class _PhotoAnalysisLLM(_Frozen):
    """The strict shape the Haiku sub-call must produce (passed to messages.parse)."""

    overall_condition: Literal["excellent", "good", "fair", "poor", "unclear"]
    confidence: Literal["high", "medium", "low"]
    summary: str
    observations: list[str]
    red_flags: list[str]


class PhotoAnalysis(_Frozen):
    """Result of `analyse_listing_photos` — LLM judgement + bookkeeping.

    `photos_analysed` is added by the tool (not by the LLM) so the agent
    knows how many of the available images were actually inspected and can
    discount the assessment's confidence if only a few photos were seen.
    """

    overall_condition: Literal["excellent", "good", "fair", "poor", "unclear"]
    confidence: Literal["high", "medium", "low"]
    summary: str
    observations: list[str]
    red_flags: list[str]
    photos_analysed: int
    model_used: str
