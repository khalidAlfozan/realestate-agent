"""Paragraph-aware text chunking for the RAG corpus.

Splits report text into ~`target_chars`-sized chunks on paragraph
boundaries, carrying a short overlap between consecutive chunks so a fact
that straddles a boundary is still retrievable in one piece. Pure functions
— no I/O — so this is the part of the pipeline that gets real unit tests.
"""

from __future__ import annotations

import re

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n+")


def _split_paragraphs(text: str) -> list[str]:
    """Split on blank lines, dropping empty fragments."""
    return [p.strip() for p in _PARAGRAPH_BREAK.split(text) if p.strip()]


def _hard_split(paragraph: str, size: int) -> list[str]:
    """Break an over-long paragraph into <=size pieces on word boundaries.

    A single word longer than `size` becomes its own (oversized) piece —
    it can't be split further without mangling it, and it doesn't happen in
    report prose anyway.
    """
    pieces: list[str] = []
    current = ""
    for word in paragraph.split():
        candidate = f"{current} {word}" if current else word
        if current and len(candidate) > size:
            pieces.append(current)
            current = word
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def chunk_text(text: str, *, target_chars: int, overlap_chars: int) -> list[str]:
    """Chunk `text` into ~`target_chars` pieces, paragraph-aware, with overlap.

    Paragraphs are packed together until the next one would overflow the
    target; the tail of the just-finished chunk (`overlap_chars` of it) is
    carried into the next chunk. Over-long paragraphs are hard-split first.
    Chunks can run slightly over `target_chars` because the carried overlap
    is added on top — that's expected.
    """
    units: list[str] = []
    for para in _split_paragraphs(text):
        if len(para) <= target_chars:
            units.append(para)
        else:
            units.extend(_hard_split(para, target_chars))

    chunks: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current}\n\n{unit}" if current else unit
        if current and len(candidate) > target_chars:
            chunks.append(current)
            tail = current[-overlap_chars:].lstrip() if overlap_chars else ""
            current = f"{tail}\n\n{unit}" if tail else unit
        else:
            current = candidate
    if current.strip():
        chunks.append(current)
    return chunks
