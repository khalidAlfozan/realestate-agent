"""Tool: search_market_reports — semantic search over the NBP report corpus.

The retrieval (read) side of the RAG layer. `src/rag/ingest.py` embeds the
corpus — National Bank of Poland quarterly housing-market reports and
analytical working papers — into pgvector; this tool embeds the agent's query
the same way (`input_type="query"`) and returns the nearest chunks by cosine
distance.

Integration code: it calls Voyage and queries Postgres, so — like
`src/rag/store.py` — it is verified by a live run, not unit tests. The one
piece of pure logic, the result-shaping, lives in
`MarketReportSearchResult.from_rows` and IS unit-tested.
"""

from __future__ import annotations

from anthropic.types import ToolParam

from src.config import settings
from src.models import MarketReportSearchResult
from src.rag import store
from src.rag.embed import embed_texts

SCHEMA: ToolParam = {
    "name": "search_market_reports",
    "description": (
        "Semantic search over a corpus of National Bank of Poland (NBP) reports on "
        "the Polish housing market: quarterly home-price reports (2021-2024) and "
        "analytical working papers on price cycles, rental-market structure, housing "
        "bubbles, and lending policy. Returns the most relevant excerpts for a "
        "natural-language query. Use it for macro context the per-listing tools do "
        "not cover: where the market sits in the price and rent cycle, supply "
        "dynamics, rental-demand drivers, and systemic risks. Phrase the query as "
        "the topic to retrieve (e.g. 'Warsaw apartment price trend 2023', 'rental "
        "demand drivers', 'housing oversupply risk')."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "A natural-language topic or question to retrieve market-report excerpts for."
                ),
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}


def search_market_reports(query: str) -> MarketReportSearchResult:
    """Embed `query`, retrieve the nearest corpus chunks, and return them ranked."""
    embedding = embed_texts([query], input_type="query")[0]
    conn = store.connect()
    try:
        rows = store.search_chunks(conn, embedding, settings.rag.search_top_k)
    finally:
        conn.close()
    return MarketReportSearchResult.from_rows(query, rows)
