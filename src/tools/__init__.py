"""Tool registry: each tool bundles its Anthropic schema with its callable.

Order matters — tools are part of the cached request prefix, so keep the
order stable.

Single source of truth: define tools in TOOLS, then SCHEMAS and FUNCTIONS
are derived. This makes a typo in a schema name vs. a registry key
structurally impossible.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, NamedTuple

from anthropic.types import ToolParam

from .analyse_listing_photos import SCHEMA as _PHOTOS_SCHEMA
from .analyse_listing_photos import analyse_listing_photos
from .calculate_gross_yield import SCHEMA as _GROSS_YIELD_SCHEMA
from .calculate_gross_yield import calculate_gross_yield
from .find_comparable_properties import SCHEMA as _COMPARABLES_SCHEMA
from .find_comparable_properties import find_comparable_properties
from .get_district_demographics import SCHEMA as _DISTRICT_DEMOGRAPHICS_SCHEMA
from .get_district_demographics import get_district_demographics
from .get_district_market_stats import SCHEMA as _DISTRICT_STATS_SCHEMA
from .get_district_market_stats import get_district_market_stats
from .get_property_details import SCHEMA as _PROPERTY_DETAILS_SCHEMA
from .get_property_details import get_property_details


class Tool(NamedTuple):
    schema: ToolParam
    fn: Callable[..., Any]


TOOLS: list[Tool] = [
    Tool(_PROPERTY_DETAILS_SCHEMA, get_property_details),
    Tool(_COMPARABLES_SCHEMA, find_comparable_properties),
    Tool(_DISTRICT_STATS_SCHEMA, get_district_market_stats),
    Tool(_DISTRICT_DEMOGRAPHICS_SCHEMA, get_district_demographics),
    Tool(_PHOTOS_SCHEMA, analyse_listing_photos),
    Tool(_GROSS_YIELD_SCHEMA, calculate_gross_yield),
]

SCHEMAS: list[ToolParam] = [t.schema for t in TOOLS]
FUNCTIONS: dict[str, Callable[..., Any]] = {t.schema["name"]: t.fn for t in TOOLS}
