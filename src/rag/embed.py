"""Voyage AI embedding wrapper for the RAG layer.

One function, used by both sides of retrieval: ingestion embeds corpus
chunks (`input_type="document"`), the search tool embeds the query
(`input_type="query"`). Voyage tunes the embedding differently for each.
"""

from __future__ import annotations

from typing import Literal

import voyageai

from src.config import require_voyage_api_key, settings

# Voyage caps the number of texts per request; 128 also keeps a batch well
# under the per-request token limit for ~500-token chunks.
_BATCH_SIZE = 128


def embed_texts(texts: list[str], *, input_type: Literal["document", "query"]) -> list[list[float]]:
    """Embed `texts` with the configured Voyage model, preserving input order.

    Texts are sent in batches to respect the API's per-request limit. Returns
    one vector per input text. An empty input returns an empty list without
    calling the API.
    """
    if not texts:
        return []
    # voyageai doesn't list Client in its __all__; the access is the
    # documented public entry point, so the export warning is a false positive.
    client = voyageai.Client(api_key=require_voyage_api_key())  # pyright: ignore[reportPrivateImportUsage]
    vectors: list[list[float]] = []
    for start in range(0, len(texts), _BATCH_SIZE):
        batch = texts[start : start + _BATCH_SIZE]
        result = client.embed(batch, model=settings.rag.voyage_model, input_type=input_type)
        # Voyage types .embeddings as float-or-int (int only for quantised
        # output dtypes, which we don't request) — coerce to a plain float vector.
        vectors.extend([float(x) for x in vector] for vector in result.embeddings)
    return vectors
