"""Tool: calculate_gross_yield — back-of-envelope rental yield arithmetic."""

from __future__ import annotations

from anthropic.types import ToolParam

SCHEMA: ToolParam = {
    "name": "calculate_gross_yield",
    "description": (
        "Compute gross rental yield for a property given the asking price and "
        "an estimated monthly rent (both in PLN). Returns gross yield (%) and "
        "the implied annual rent. Pure arithmetic — does NOT estimate rent "
        "itself; you must supply monthly_rent_pln based on comparable Warsaw "
        "rentals. Note: 'gross' yield ignores the monthly community fee "
        "(czynsz administracyjny); you should also surface that figure "
        "separately when discussing net economics in the memo."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "price_pln": {
                "type": "number",
                "description": "Asking price of the property in PLN.",
            },
            "monthly_rent_pln": {
                "type": "number",
                "description": "Estimated achievable monthly rent in PLN.",
            },
        },
        "required": ["price_pln", "monthly_rent_pln"],
        "additionalProperties": False,
    },
}


def calculate_gross_yield(price_pln: float, monthly_rent_pln: float) -> dict:
    annual_rent = monthly_rent_pln * 12
    gross_yield_pct = (annual_rent / price_pln) * 100
    return {
        "annual_rent_pln": round(annual_rent, 2),
        "gross_yield_pct": round(gross_yield_pct, 2),
    }
