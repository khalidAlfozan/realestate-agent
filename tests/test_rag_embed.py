"""Tests for the Voyage embedding wrapper (src.rag.embed).

The Voyage client is mocked — no API calls, no key needed beyond what the
tests set. We verify the batching logic and the input-order guarantee; the
real embedding quality is Voyage's concern, not ours to test.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import voyageai

from src.rag.embed import embed_texts


def test_empty_input_returns_empty_without_calling_the_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No texts → no client constructed (so no key needed) → empty result."""

    def _must_not_construct(*_: Any, **__: Any) -> Any:
        raise AssertionError("Voyage client must not be built for empty input")

    monkeypatch.setattr(voyageai, "Client", _must_not_construct)
    assert embed_texts([], input_type="document") == []


def test_embeds_texts_in_input_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOYAGE_API_KEY", "fake-key")
    calls: list[tuple[int, str]] = []

    def _fake_embed(texts: list[str], model: str, input_type: str) -> Any:
        calls.append((len(texts), input_type))
        return SimpleNamespace(embeddings=[[float(len(t))] for t in texts])

    monkeypatch.setattr(voyageai, "Client", lambda api_key: SimpleNamespace(embed=_fake_embed))
    out = embed_texts(["a", "bb", "ccc"], input_type="query")

    assert out == [[1.0], [2.0], [3.0]]
    assert len(calls) == 1
    assert calls[0] == (3, "query")


def test_large_input_is_split_into_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    """>128 texts must be sent in multiple requests, results concatenated in
    the original order."""
    monkeypatch.setenv("VOYAGE_API_KEY", "fake-key")
    batch_sizes: list[int] = []

    def _fake_embed(texts: list[str], model: str, input_type: str) -> Any:
        batch_sizes.append(len(texts))
        return SimpleNamespace(embeddings=[[1.0] for _ in texts])

    monkeypatch.setattr(voyageai, "Client", lambda api_key: SimpleNamespace(embed=_fake_embed))
    out = embed_texts([f"text-{i}" for i in range(130)], input_type="document")

    assert len(out) == 130
    assert batch_sizes == [128, 2]


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-empty input with no key surfaces the helpful config error."""
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="VOYAGE_API_KEY is not set"):
        embed_texts(["something"], input_type="document")
