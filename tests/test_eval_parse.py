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

## 3. Market backdrop
NBP's 2024-Q1 report shows Warsaw price growth cooling and rental rates softening q/q.

## 4. Condition assessment
Seller claims fully renovated. **Photo-derived condition: EXCELLENT (high confidence, 8 photos analysed).**
The visual evidence supports the seller's narrative.

## 5. Comparables

### Rentals (for monthly-rent estimate)
- **Comp set:** 37 rentals from `find_comparable_properties(transaction_type="rent")` for Wola, 3–5 rooms, 58–88 m².
- Median: 115 PLN/m² · p25–p75: 83–125 PLN/m².
- Implied monthly rent: 6 424 PLN.

### Sales (for asking-price fairness)
- **Comp set:** 32 sales from `find_comparable_properties(transaction_type="sale")` for the same filters.
- Median: 19 548 PLN/m².
- **Verdict: ~10% discount to the comp median.**

## 6. Financial analysis
- Asking price: 1 290 000 PLN.
- Estimated monthly rent: 6 424 PLN.
- Annual rent: 77 088 PLN.
- **Gross yield: 5.98%** (from `calculate_gross_yield`).
- **Verdict:** the gross yield sits within the typical Warsaw 5–7% range.

## 7. Risks and sensitivities
- **Limited ownership liquidity risk:** Spółdzielcze własnościowe complicates financing.
- **Ground floor discount.** Vacancy risk is real.
- **Czynsz 12.7 PLN/m².** Within normal range but a fixed drag.

## 8. Recommendation

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

    def test_photos_count_handles_alternate_phrasing(self) -> None:
        """The agent phrases the §4 count as 'N photos analysed', 'N photos,
        high confidence', or 'N images' — match the number, not the wording."""
        assert parse_memo("Photo analysis (17 photos, high confidence)").photos_analysed == 17
        assert parse_memo("based on 6 images analysed").photos_analysed == 6

    def test_photos_analysed_handles_images_phrasing(self) -> None:
        """For CGI-rendering (off-plan) listings the agent writes 'N images
        analysed' rather than 'N photos analysed' — the parser accepts both."""
        memo = "Photo-derived condition: EXCELLENT (high confidence, 7 images analysed)."
        assert parse_memo(memo).photos_analysed == 7

    def test_extracts_rent_comp_count(self) -> None:
        result = parse_memo(_SAMPLE_MEMO)
        assert result.rent_comp_count == 37

    def test_extracts_sale_comp_count(self) -> None:
        result = parse_memo(_SAMPLE_MEMO)
        assert result.sale_comp_count == 32

    def test_risks_text_captures_section_7_only(self) -> None:
        """The risks_text field is used for substring-matching assertions —
        it must include §7 content but not bleed into §8."""
        result = parse_memo(_SAMPLE_MEMO)
        assert "spółdzielcze" in result.risks_text.lower()
        assert "ground floor" in result.risks_text.lower()
        # §8 content should NOT appear (would let "Borderline" leak in).
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
        memo = "## 8. Recommendation\n\n**Verdict:** Walk.\n**Confidence:** High."
        result = parse_memo(memo)
        assert result.verdict == "Walk"
        assert result.confidence == "High"

    def test_handles_buy_verdict(self) -> None:
        memo = "## 8. Recommendation\n\n**Verdict:** Buy.\n**Confidence:** Low."
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
            "## 8. Recommendation\n\n"
            "**Verdict: Borderline — leaning Buy, subject to legal due diligence.**\n"
            "**Confidence: Medium.**"
        )
        result = parse_memo(memo)
        assert result.verdict == "Borderline"
        assert result.confidence == "Medium"

    def test_handles_whole_bold_walk_verdict(self) -> None:
        memo = (
            "## 8. Recommendation\n\n"
            "**Verdict: Walk — overpriced for condition.**\n**Confidence: High.**"
        )
        result = parse_memo(memo)
        assert result.verdict == "Walk"
        assert result.confidence == "High"

    def test_verdict_scoped_to_recommendation_section(self) -> None:
        """The agent also writes bolded '**Verdict:**' sub-labels in §5 (price
        fairness) and §6 (yield). Verdict/confidence must be read from §8, not
        from the first '**Verdict**' match in the memo."""
        memo = (
            "## 5. Comparables\n"
            "- **Verdict: significant premium** vs the comp-set median.\n\n"
            "## 6. Financial analysis\n"
            "- **Verdict:** the gross yield is acceptable on paper.\n\n"
            "## 8. Recommendation\n\n"
            "**Verdict:** Walk — overpriced for the segment.\n"
            "**Confidence:** High.\n"
        )
        result = parse_memo(memo)
        assert result.verdict == "Walk"
        assert result.confidence == "High"

    def test_comp_counts_handle_listings_phrasing(self) -> None:
        """The agent phrases the §5 count as 'rentals', 'sale listings', or
        just 'listings'. The parser anchors on 'Comp set:' + the number."""
        memo = (
            "## 5. Comparables\n\n"
            "### Rentals (for monthly-rent estimate)\n"
            "- Comp set: 40 rental listings from the rent search.\n\n"
            "### Sales (for asking-price fairness)\n"
            "- **Comp set:** 28 listings from the sale search.\n"
        )
        result = parse_memo(memo)
        assert result.rent_comp_count == 40
        assert result.sale_comp_count == 28

    def test_comp_counts_handle_thin_segment_phrasing(self) -> None:
        """For a thin segment the agent writes 'Comp set: only N listings'.
        The parser must skip interstitial words and grab the first number."""
        memo = (
            "## 5. Comparables\n\n"
            "### Rentals\n- Comp set: only 6 rentals from the search.\n\n"
            "### Sales\n- **Comp set: only 4 listings** in the segment.\n"
        )
        result = parse_memo(memo)
        assert result.rent_comp_count == 6
        assert result.sale_comp_count == 4
