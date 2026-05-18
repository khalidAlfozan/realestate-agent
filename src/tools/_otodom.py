"""Shared Otodom helpers used by multiple tools.

Centralised so the Polish-diacritic map and percentile maths live in one
place — tools that build search URLs or summarise listing arrays should
import from here rather than re-implement.
"""

from __future__ import annotations

# Diacritic-stripping table for Polish district slugs (lowercase only).
_PL_DIACRITICS = str.maketrans(
    {"ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n", "ó": "o", "ś": "s", "ź": "z", "ż": "z"}
)


def district_slug(name: str) -> str:
    """Normalise a Warsaw district name to its Otodom URL slug."""
    slug = name.lower().translate(_PL_DIACRITICS).replace(" ", "-")
    # Otodom slugs the two hyphenated Warsaw districts — Praga-Południe and
    # Praga-Północ — with a doubled hyphen (e.g. "praga--poludnie"); the
    # single-hyphen form 404s. They are the only Warsaw districts whose name
    # contains a hyphen, so doubling every hyphen is correct for this input.
    return slug.replace("-", "--")


def percentile(values: list[int], p: float) -> int | None:
    """p-th percentile (linear interpolation) of a non-empty list. None if empty."""
    if not values:
        return None
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (p / 100)
    lo, hi = int(k), int(k) + 1
    if hi >= len(sorted_vals):
        return sorted_vals[-1]
    return round(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo))
