# ruff: noqa: RUF001
# This file's _SAMPLE_MEMO uses Unicode en-dashes and bullet dots
# deliberately because they mirror what the agent actually produces; the
# parser must handle the real shape, not an ASCII-clean approximation.
"""Tests for evals.parse_memo — the regex-based extractor.

The whole point of the eval harness is to flag silent regressions when
the system prompt's memo template drifts. So this test file holds an
example memo that mirrors the expected template output, plus tests for
each field extraction. If a future prompt change makes parse_memo()
stop extracting a field, these tests fail loud.
"""

from __future__ import annotations

from evals.parse_memo import parse_memo

# A representative memo body — close to what the agent has actually been
# producing for the Wola listing in real runs, simplified for clarity.
_SAMPLE_MEMO = """\
# Investment Memo: METRO 4-pok. po gen. Remoncie, Bliska Wola–centrum

**Source:** https://www.otodom.pl/pl/oferta/metro-4-pok-po-gen-remoncie-bliska-wola-centrum-ID4B8mI
**Asking price:** 1 290 000 PLN
**Surface:** 73 m² · 4 rooms
**Location:** ul. Kasprzaka 9, Wola, Warszawa

## 1. Property summary
A 73 m² four-room ground-floor apartment, post-renovation.

## 2. Neighbourhood context
Wola — Warsaw's fastest-growing district.

## 3. Condition assessment
Seller claims fully renovated. **Photo-derived condition: EXCELLENT (high confidence, 8 photos analysed).**
The visual evidence supports the seller's narrative.

## 4. Comparables

### Rentals (for monthly-rent estimate)
- **Comp set:** 37 rentals from `find_comparable_properties(transaction_type="rent")` for Wola, 3–5 rooms, 58–88 m².
- Median: 115 PLN/m² · p25–p75: 83–125 PLN/m².
- Implied monthly rent: 6 424 PLN.

### Sales (for asking-price fairness)
- **Comp set:** 32 sales from `find_comparable_properties(transaction_type="sale")` for the same filters.
- Median: 19 548 PLN/m².
- ~10% discount vs median.

## 5. Financial analysis
- Asking price: 1 290 000 PLN.
- Estimated monthly rent: 6 424 PLN.
- Annual rent: 77 088 PLN.
- **Gross yield: 5.98%** (from `calculate_gross_yield`).

## 6. Risks and sensitivities
- **Limited ownership liquidity risk:** Spółdzielcze własnościowe complicates financing.
- **Ground floor discount.** Vacancy risk is real.
- **Czynsz 12.7 PLN/m².** Within normal range but a fixed drag.

## 7. Recommendation

**Verdict:** Borderline — Buy with conditions.
**Confidence:** Medium.

The property combines a renovated ground-floor unit and an asking price ~10% below the comp median.
"""


class TestParseMemo:
    def test_extracts_verdict_canonical(self) -> None:
        """Even a free-form 'Borderline — Buy with conditions' resolves to 'Borderline'."""
        result = parse_memo(_SAMPLE_MEMO)
        assert result.verdict == "Borderline"

    def test_extracts_confidence(self) -> None:
        result = parse_memo(_SAMPLE_MEMO)
        assert result.confidence == "Medium"

    def test_extracts_gross_yield(self) -> None:
        result = parse_memo(_SAMPLE_MEMO)
        assert result.gross_yield_pct == 5.98

    def test_extracts_photo_condition(self) -> None:
        result = parse_memo(_SAMPLE_MEMO)
        assert result.photo_condition == "EXCELLENT"

    def test_extracts_photos_analysed(self) -> None:
        result = parse_memo(_SAMPLE_MEMO)
        assert result.photos_analysed == 8

    def test_extracts_rent_comp_count(self) -> None:
        result = parse_memo(_SAMPLE_MEMO)
        assert result.rent_comp_count == 37

    def test_extracts_sale_comp_count(self) -> None:
        result = parse_memo(_SAMPLE_MEMO)
        assert result.sale_comp_count == 32

    def test_risks_text_captures_section_6_only(self) -> None:
        """The risks_text field is used for substring-matching assertions —
        it must include §6 content but not bleed into §7."""
        result = parse_memo(_SAMPLE_MEMO)
        assert "spółdzielcze" in result.risks_text.lower()
        assert "ground floor" in result.risks_text.lower()
        # §7 content should NOT appear (would let "Borderline" leak in).
        assert "Borderline" not in result.risks_text

    def test_returns_none_on_missing_fields(self) -> None:
        """If the memo doesn't contain a field, the parser returns None for it
        rather than raising — the eval then flags it as a failed assertion."""
        empty_memo = "# Investment Memo: blank\n\nNo body."
        result = parse_memo(empty_memo)
        assert result.verdict is None
        assert result.confidence is None
        assert result.gross_yield_pct is None
        assert result.photo_condition is None
        assert result.photos_analysed is None
        assert result.rent_comp_count is None
        assert result.sale_comp_count is None

    def test_handles_walk_verdict(self) -> None:
        memo = "## 7. Recommendation\n\n**Verdict:** Walk.\n**Confidence:** High."
        result = parse_memo(memo)
        assert result.verdict == "Walk"
        assert result.confidence == "High"

    def test_handles_buy_verdict(self) -> None:
        memo = "## 7. Recommendation\n\n**Verdict:** Buy.\n**Confidence:** Low."
        result = parse_memo(memo)
        assert result.verdict == "Buy"
        assert result.confidence == "Low"

    def test_handles_alternate_gross_yield_formatting(self) -> None:
        """The agent sometimes formats yield as `**Gross yield:** X%` (split bold)."""
        memo_a = "**Gross yield: 4.42%**"
        memo_b = "**Gross yield:** 4.42%"
        assert parse_memo(memo_a).gross_yield_pct == 4.42
        assert parse_memo(memo_b).gross_yield_pct == 4.42

    def test_handles_whole_bold_verdict_with_qualifier(self) -> None:
        """Real-world variant the agent has produced: the whole 'Verdict: X — ...'
        line is wrapped in a single bold span, not just the label. Without
        this tolerance, the parser silently returns None and the eval reports
        verdict=None (which looks like a regression but is just formatting drift)."""
        memo = (
            "## 7. Recommendation\n\n"
            "**Verdict: Borderline — leaning Buy, subject to legal due diligence.**\n"
            "**Confidence: Medium.**"
        )
        result = parse_memo(memo)
        assert result.verdict == "Borderline"
        assert result.confidence == "Medium"

    def test_handles_whole_bold_walk_verdict(self) -> None:
        memo = "**Verdict: Walk — overpriced for condition.**\n**Confidence: High.**"
        result = parse_memo(memo)
        assert result.verdict == "Walk"
        assert result.confidence == "High"
