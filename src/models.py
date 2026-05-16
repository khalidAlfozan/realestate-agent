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


class DistrictDemographics(_Frozen):
    """Result of `get_district_demographics` — annual GUS BDL stats for a Warsaw dzielnica.

    All metric fields are nullable: BDL doesn't always have data for every
    (district, variable, year) combination. Missing fields render as a skipped
    line in the memo rather than crashing the agent loop. Each metric carries
    its own `_year` because BDL release cadence differs by topic — population
    annually, dwellings annually but with longer lag, migration annually.
    """

    district: str
    bdl_unit_id: str
    fetched_at: str

    population: int | None = None
    population_year: int | None = None

    dwellings: int | None = None
    dwellings_year: int | None = None

    net_migration: int | None = None
    net_migration_year: int | None = None

    # Area + population gives density; agent computes the ratio in §2.
    area_km2: float | None = None
    area_km2_year: int | None = None

    # Supply-side signal: faster pipeline → more rent compression. Normalised
    # by population so it's comparable across dzielnice of different sizes.
    new_dwellings_per_1000_residents: float | None = None
    new_dwellings_per_1000_residents_year: int | None = None

    # REGON-registered businesses per 1000 residents — proxy for commercial
    # vitality / nearby-jobs density. High in central districts, lower in the
    # outer ring.
    businesses_per_1000_residents: float | None = None
    businesses_per_1000_residents_year: int | None = None


class NearbyAmenity(_Frozen):
    """One amenity within the search radius — name, distance from subject, location."""

    name: str | None = None
    distance_m: int
    lat: float
    lon: float


class AmenityCategory(_Frozen):
    """Counts + nearest examples for one amenity kind (subway, tram, bus, school, park).

    `count` is raw OSM element count within the radius. Bus/tram stops are often
    duplicated by direction (e.g. 'Leszno 01' + 'Leszno 02' as two OSM nodes), so
    `count` may overstate distinct stop locations. The `nearest` list is deduped
    by stripped name (the trailing ' 01' / ' 02' platform suffix is removed) to
    show distinct locations.
    """

    count: int
    nearest: list[NearbyAmenity]


class NearbyAmenities(_Frozen):
    """Result of `get_nearby_amenities` — counts + nearest examples for amenity
    types within walking distance of a property.

    All five categories are always present; categories with no matches return
    `count=0, nearest=[]`. Useful for §2 of the memo to anchor walkability /
    transit / schools / green-space claims in concrete distances rather than
    impressions.

    Two radii: `radius_m` is the walkability radius for transit + parks;
    `school_radius_m` is wider, because a school's catchment is larger than
    the distance someone will walk to a tram stop. `subway`/`tram`/`bus`/`park`
    counts are within `radius_m`; `school` counts are within `school_radius_m`.
    """

    latitude: float
    longitude: float
    radius_m: int
    school_radius_m: int
    fetched_at: str

    subway: AmenityCategory
    tram: AmenityCategory
    bus: AmenityCategory
    school: AmenityCategory
    park: AmenityCategory


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


class MarketReportExcerpt(_Frozen):
    """One retrieved chunk from the NBP market-report corpus."""

    source: str
    content: str
    similarity: float


class MarketReportSearchResult(_Frozen):
    """Result of `search_market_reports` — the query and its nearest corpus chunks.

    `excerpts` are ordered nearest-first. `similarity` is `1 - cosine distance`
    (pgvector's `<=>` operator), so higher means a closer match — easier for the
    agent to read than a raw distance.
    """

    query: str
    excerpts: list[MarketReportExcerpt]

    @classmethod
    def from_rows(cls, query: str, rows: list[tuple[str, str, float]]) -> MarketReportSearchResult:
        """Build the result from raw `(source, content, cosine_distance)` rows.

        Converting cosine distance to similarity is the one piece of real logic
        on the search path; keeping it here makes it unit-testable without a live
        database (the tool itself is integration code, verified by a live run).
        """
        return cls(
            query=query,
            excerpts=[
                MarketReportExcerpt(
                    source=source, content=content, similarity=round(1.0 - distance, 4)
                )
                for source, content, distance in rows
            ],
        )
