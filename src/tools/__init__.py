"""Tool registry: schemas + executor map for the agent loop.

Order matters — tools are part of the cached request prefix, so keep this list stable.
"""
from .calculate_gross_yield import SCHEMA as _GROSS_YIELD_SCHEMA, calculate_gross_yield
from .get_property_details import SCHEMA as _PROPERTY_DETAILS_SCHEMA, get_property_details

TOOLS = [
    _PROPERTY_DETAILS_SCHEMA,
    _GROSS_YIELD_SCHEMA,
]

TOOL_FUNCTIONS = {
    "get_property_details": get_property_details,
    "calculate_gross_yield": calculate_gross_yield,
}
