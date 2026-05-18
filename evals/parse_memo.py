"""Extract structured fields from a markdown memo.

The regexes deliberately mirror the system prompt's memo template. If the
template changes and we silently stop extracting a field, the eval will
flag it (assertion fails because actual is None) — which is the regression
behaviour we want.

We extract:
- §4: Photo-derived condition + how many photos were analysed
- §5 Rentals: comp count
- §5 Sales: comp count
- §6: Gross yield %
- §7: full body text (for substring assertions)
- §8: Verdict + Confidence
"""

from __future__ import annotations

import re

from .models import ParsedMemo

# Header lines have **Field:** prefix; tolerate two common bold variants:
#   **Verdict:** Borderline (qualifiers).               <- colon outside bold
#   **Verdict: Borderline — qualifiers.**               <- whole line bolded
# The character class [:\s*]+ swallows whatever sits between "Verdict" and
# the value (any combo of colon, whitespace, asterisks). [^\n*]+ stops the
# capture at a newline OR the closing ** of the whole-bold variant.
_VERDICT_RE = re.compile(
    r"\*\*Verdict[:\s*]+([^\n*]+)",
    re.IGNORECASE,
)
_CONFIDENCE_RE = re.compile(
    r"\*\*Confidence[:\s*]+(Low|Medium|High)",
    re.IGNORECASE,
)

# §6 line — "**Gross yield: 5.81%**" or "**Gross yield:** 5.81%" (the agent
# sometimes formats it both ways).
_GROSS_YIELD_RE = re.compile(
    r"\*\*Gross yield:?\*?\*?\s*([\d.,]+)\s*%",
    re.IGNORECASE,
)

# §4 condition line — "Photo-derived condition: EXCELLENT (high confidence, 8 photos analysed)"
# Sometimes wrapped in **bold** by the agent.
_PHOTO_CONDITION_RE = re.compile(
    r"Photo-derived condition[*:]+\s*\*?\*?(\w+)",
    re.IGNORECASE,
)
_PHOTOS_ANALYSED_RE = re.compile(
    # "photos" for real listings; "images" when the listing is CGI renderings
    # (off-plan units) — the agent picks the honest word for what it analysed.
    r"(\d+)\s+(?:photos?|images?)\s+analysed",
    re.IGNORECASE,
)

# §5 subsection counts — the "Comp set:" bullet opening each subsection,
# e.g. "Comp set: 37 rentals", "**Comp set:** 27 sale listings", or just
# "Comp set: 33 listings". Anchor on "Comp set" + the number; the trailing
# noun (rentals/sales/listings) is phrased inconsistently by the agent.
# DOTALL because we cross newlines from the heading to the bullet.
_RENT_COMP_RE = re.compile(
    r"#+\s*Rentals.*?Comp set[:\s*]*(\d+)",
    re.IGNORECASE | re.DOTALL,
)
_SALE_COMP_RE = re.compile(
    r"#+\s*Sales.*?Comp set[:\s*]*(\d+)",
    re.IGNORECASE | re.DOTALL,
)

# §7 body — everything between "## 7. Risks" and "## 8." (or end of memo).
_RISKS_SECTION_RE = re.compile(
    r"##\s*7\.\s*Risks.*?(?=##\s*8\.|\Z)",
    re.IGNORECASE | re.DOTALL,
)

# §8 body — "## 8. Recommendation" to the end of the memo. Verdict and
# Confidence are extracted from here only: the agent also writes bolded
# "**Verdict:**" sub-labels in §5 (price fairness) and §6 (yield), so a
# whole-memo search would grab one of those instead of the recommendation.
_RECOMMENDATION_SECTION_RE = re.compile(
    r"##\s*8\.\s*Recommendation.*\Z",
    re.IGNORECASE | re.DOTALL,
)


def _to_float(s: str | None) -> float | None:
    if s is None:
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def _to_int(s: str | None) -> int | None:
    if s is None:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _normalise_verdict(raw: str | None) -> str | None:
    """Pick the first canonical verdict word from a free-text verdict line.

    The agent sometimes writes 'Borderline — Buy with conditions' or
    'Walk for leveraged buyers' — we want just 'Borderline' / 'Walk'.
    """
    if raw is None:
        return None
    cleaned = raw.strip().rstrip(".:")
    # Strip surrounding ** if the line was fully bolded.
    cleaned = cleaned.strip("*").strip()
    for canonical in ("Borderline", "Walk", "Buy"):
        if canonical.lower() in cleaned.lower():
            return canonical
    return cleaned or None


def parse_memo(memo: str) -> ParsedMemo:
    rec_match = _RECOMMENDATION_SECTION_RE.search(memo)
    rec_text = rec_match.group(0) if rec_match else ""
    verdict = _normalise_verdict(_first_match(_VERDICT_RE, rec_text))
    confidence_raw = _first_match(_CONFIDENCE_RE, rec_text)
    confidence = confidence_raw.title() if confidence_raw else None

    risks_match = _RISKS_SECTION_RE.search(memo)
    risks_text = risks_match.group(0) if risks_match else ""

    return ParsedMemo(
        verdict=verdict,
        confidence=confidence,
        gross_yield_pct=_to_float(_first_match(_GROSS_YIELD_RE, memo)),
        photo_condition=(_first_match(_PHOTO_CONDITION_RE, memo) or None),
        photos_analysed=_to_int(_first_match(_PHOTOS_ANALYSED_RE, memo)),
        rent_comp_count=_to_int(_first_match(_RENT_COMP_RE, memo)),
        sale_comp_count=_to_int(_first_match(_SALE_COMP_RE, memo)),
        risks_text=risks_text,
    )


def _first_match(pattern: re.Pattern[str], text: str) -> str | None:
    m = pattern.search(text)
    return m.group(1) if m else None
