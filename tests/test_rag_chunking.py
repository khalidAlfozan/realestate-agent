"""Tests for the RAG corpus chunker (src.rag.chunking).

The chunker is the one piece of the ingestion pipeline that's pure logic
(no Voyage, no Postgres), so it gets real unit tests rather than mocks.
"""

from __future__ import annotations

from src.rag.chunking import chunk_text


def _paragraph(approx_chars: int, word: str = "word") -> str:
    """A paragraph of roughly `approx_chars` characters."""
    word_count = max(1, approx_chars // (len(word) + 1))
    return " ".join([word] * word_count)


def test_empty_text_returns_no_chunks() -> None:
    assert chunk_text("", target_chars=2000, overlap_chars=200) == []


def test_whitespace_only_returns_no_chunks() -> None:
    assert chunk_text("   \n\n   \n  ", target_chars=2000, overlap_chars=200) == []


def test_short_text_is_a_single_chunk() -> None:
    text = "First short paragraph.\n\nSecond short paragraph."
    chunks = chunk_text(text, target_chars=2000, overlap_chars=200)
    assert len(chunks) == 1
    assert "First short paragraph." in chunks[0]
    assert "Second short paragraph." in chunks[0]


def test_long_text_splits_into_multiple_bounded_chunks() -> None:
    """Ten ~500-char paragraphs against a 2000-char target → several chunks,
    each near the target (the carried overlap can push it slightly over)."""
    text = "\n\n".join(_paragraph(500) for _ in range(10))
    chunks = chunk_text(text, target_chars=2000, overlap_chars=200)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 2000 + 200 + 100  # target + overlap + join slack


def test_consecutive_chunks_share_an_overlap() -> None:
    """The tail of one chunk reappears at the start of the next, so a fact on
    a boundary stays retrievable."""
    text = "\n\n".join(f"Paragraph {i}: {_paragraph(500)}" for i in range(8))
    chunks = chunk_text(text, target_chars=1500, overlap_chars=200)
    assert len(chunks) > 1
    assert chunks[0][-100:] in chunks[1]


def test_oversized_paragraph_is_hard_split() -> None:
    """A single paragraph far larger than the target is broken up rather than
    emitted as one giant chunk."""
    huge = _paragraph(5000)
    chunks = chunk_text(huge, target_chars=1000, overlap_chars=100)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 1000 + 100 + 100


def test_no_overlap_when_overlap_is_zero() -> None:
    text = "\n\n".join(_paragraph(500) for _ in range(6))
    chunks = chunk_text(text, target_chars=1000, overlap_chars=0)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 1000 + 100
