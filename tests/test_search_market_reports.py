"""Tests for the market-report search result-shaping.

The `search_market_reports` tool itself embeds via Voyage and queries
pgvector — integration code verified by a live run, not unit tests (see the
coverage omit list). What is pure and testable is `from_rows`: the
cosine-distance-to-similarity conversion and the nearest-first ordering.
"""

from __future__ import annotations

from src.models import MarketReportSearchResult


def test_from_rows_converts_cosine_distance_to_similarity() -> None:
    rows = [("nbp-quarterly-2023-Q2", "prose about Warsaw rents", 0.25)]
    result = MarketReportSearchResult.from_rows("warsaw rental market", rows)

    assert result.query == "warsaw rental market"
    assert len(result.excerpts) == 1
    excerpt = result.excerpts[0]
    assert excerpt.source == "nbp-quarterly-2023-Q2"
    assert excerpt.content == "prose about Warsaw rents"
    assert excerpt.similarity == 0.75


def test_from_rows_preserves_nearest_first_order() -> None:
    """Rows arrive ordered nearest-first; the result keeps that order."""
    rows = [
        ("doc-a", "closest", 0.10),
        ("doc-b", "middle", 0.30),
        ("doc-c", "farthest", 0.50),
    ]
    result = MarketReportSearchResult.from_rows("q", rows)

    assert [e.source for e in result.excerpts] == ["doc-a", "doc-b", "doc-c"]
    assert [e.similarity for e in result.excerpts] == [0.9, 0.7, 0.5]


def test_from_rows_with_no_matches_returns_empty_excerpts() -> None:
    result = MarketReportSearchResult.from_rows("nothing relevant", [])

    assert result.query == "nothing relevant"
    assert result.excerpts == []
