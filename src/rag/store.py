"""pgvector store for the RAG corpus — schema and idempotent inserts.

Integration code: verified by a live smoke-run against Postgres, not unit
tests (mocking psycopg would assert the mocks, not the integration). Kept
deliberately thin — SQL and connection handling, no algorithms; the real
logic lives in chunking.py and embed.py.

Queries are literal strings: psycopg's typed API rejects a runtime-built
query string (the same thing that blocks SQL injection). The one dynamic
piece — the embedding dimension in the CREATE TABLE — is composed via
`psycopg.sql`, since a column type modifier can't be a bound parameter.
"""

from __future__ import annotations

import psycopg
from pgvector.psycopg import register_vector
from psycopg import sql

from src.config import require_database_url, settings


def connect() -> psycopg.Connection:
    """Open a Postgres connection with the pgvector type adapter registered."""
    conn = psycopg.connect(require_database_url())
    register_vector(conn)
    return conn


def ensure_schema(conn: psycopg.Connection) -> None:
    """Create the pgvector extension, the chunks table, and the HNSW index.

    Idempotent — safe to call on every ingestion run.
    """
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.execute(
        sql.SQL(
            "CREATE TABLE IF NOT EXISTS market_report_chunks ("
            "id BIGSERIAL PRIMARY KEY, "
            "source TEXT NOT NULL, "
            "chunk_index INTEGER NOT NULL, "
            "content TEXT NOT NULL, "
            "embedding vector({dim}) NOT NULL, "
            "UNIQUE (source, chunk_index))"
        ).format(dim=sql.Literal(settings.rag.embedding_dim))
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS market_report_chunks_embedding_idx "
        "ON market_report_chunks USING hnsw (embedding vector_cosine_ops)"
    )
    conn.commit()


def ingested_sources(conn: psycopg.Connection) -> set[str]:
    """Return the `source`s already in the store — drives ingestion idempotency."""
    rows = conn.execute("SELECT DISTINCT source FROM market_report_chunks").fetchall()
    return {row[0] for row in rows}


def clear_all(conn: psycopg.Connection) -> None:
    """Remove every chunk — used by `ingest --rebuild`."""
    conn.execute("TRUNCATE market_report_chunks")
    conn.commit()


def replace_document(
    conn: psycopg.Connection,
    source: str,
    chunks: list[str],
    embeddings: list[list[float]],
) -> None:
    """Replace all stored chunks for `source` with the given chunks + vectors.

    Delete-then-insert so a re-ingest of one document leaves no stale chunks.
    """
    rows = [
        (source, index, chunk, embedding)
        for index, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True))
    ]
    with conn.cursor() as cur:
        cur.execute("DELETE FROM market_report_chunks WHERE source = %s", (source,))
        cur.executemany(
            "INSERT INTO market_report_chunks "
            "(source, chunk_index, content, embedding) VALUES (%s, %s, %s, %s)",
            rows,
        )
    conn.commit()
