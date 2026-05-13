"""Tool: calculate_gross_yield — back-of-envelope rental yield arithmetic."""
from __future__ import annotations

SCHEMA = {
    "name": "calculate_gross_yield",
    "description": (
        "Compute gross rental yield for a property given the asking price and "
        "an estimated monthly rent. Returns gross yield (%) and the implied "
        "annual rent. Pure arithmetic — does NOT estimate rent itself; you "
        "must supply monthly_rent_eur based on comparable Madrid rentals."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "price_eur": {
                "type": "number",
                "description": "Asking price of the property in EUR.",
            },
            "monthly_rent_eur": {
                "type": "number",
                "description": "Estimated achievable monthly rent in EUR.",
            },
        },
        "required": ["price_eur", "monthly_rent_eur"],
        "additionalProperties": False,
    },
}


def calculate_gross_yield(price_eur: float, monthly_rent_eur: float) -> dict:
    annual_rent = monthly_rent_eur * 12
    gross_yield_pct = (annual_rent / price_eur) * 100
    return {
        "annual_rent_eur": round(annual_rent, 2),
        "gross_yield_pct": round(gross_yield_pct, 2),
    }
