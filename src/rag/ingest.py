"""RAG corpus ingestion — fetch / read NBP reports, chunk, embed, store.

Run once, then again only when the corpus changes:

    uv run python -m src.rag.ingest             # ingest documents not yet stored
    uv run python -m src.rag.ingest --rebuild   # wipe the store and re-ingest all

Two kinds of source documents:
  - the static.nbp.pl PDFs listed in corpus_manifest.toml (downloaded here)
  - any PDFs dropped into data/corpus/ — the bot-walled cyclical reports a
    human downloads in a browser (see the README)

Idempotent: a document whose `source` is already in the store is skipped
unless `--rebuild` is given. This is integration code — verified by a live
run against Postgres + Voyage, not by unit tests.
"""

from __future__ import annotations

import argparse
import io
import logging
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

import httpx
from pypdf import PdfReader

from src.config import ROOT, settings
from src.rag import store
from src.rag.chunking import chunk_text
from src.rag.embed import embed_texts

log = logging.getLogger(__name__)

_MANIFEST = Path(__file__).parent / "corpus_manifest.toml"
_CORPUS_DIR = ROOT / "data" / "corpus"
_FETCH_TIMEOUT_S = 60.0


@dataclass(frozen=True)
class _Document:
    """A corpus document: a manifest URL to download or a local PDF to read."""

    source: str  # stable id — the `source` column + retrieval attribution
    location: str  # URL (manifest) or filesystem path (local drop)
    is_url: bool


def _load_documents() -> list[_Document]:
    """Gather corpus documents: manifest URLs + any PDFs in data/corpus/."""
    docs: list[_Document] = []
    manifest = tomllib.loads(_MANIFEST.read_text(encoding="utf-8"))
    for entry in manifest.get("document", []):
        docs.append(_Document(source=entry["title"], location=entry["url"], is_url=True))
    if _CORPUS_DIR.is_dir():
        for pdf in sorted(_CORPUS_DIR.glob("*.pdf")):
            docs.append(_Document(source=pdf.stem, location=str(pdf), is_url=False))
    return docs


def _extract_text(doc: _Document) -> str:
    """Download or read the document and extract its text with pypdf."""
    if doc.is_url:
        response = httpx.get(
            doc.location,
            follow_redirects=True,
            timeout=_FETCH_TIMEOUT_S,
            headers={"User-Agent": "realestate-agent corpus ingestion"},
        )
        response.raise_for_status()
        data = response.content
    else:
        data = Path(doc.location).read_bytes()
    reader = PdfReader(io.BytesIO(data))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest the NBP market-report corpus.")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Wipe the store and re-ingest every document.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    documents = _load_documents()
    if not documents:
        log.error("No documents — corpus_manifest.toml is empty and data/corpus/ has no PDFs.")
        return 1

    conn = store.connect()
    try:
        store.ensure_schema(conn)
        if args.rebuild:
            store.clear_all(conn)
        already = set() if args.rebuild else store.ingested_sources(conn)

        ingested = 0
        for doc in documents:
            if doc.source in already:
                log.info("skip (already ingested): %s", doc.source)
                continue
            log.info("ingesting: %s (%s)", doc.source, doc.location)
            text = _extract_text(doc)
            chunks = chunk_text(
                text,
                target_chars=settings.rag.chunk_target_chars,
                overlap_chars=settings.rag.chunk_overlap_chars,
            )
            if not chunks:
                log.warning("no extractable text — skipping: %s", doc.source)
                continue
            embeddings = embed_texts(chunks, input_type="document")
            store.replace_document(conn, doc.source, chunks, embeddings)
            log.info("  stored %d chunks", len(chunks))
            ingested += 1

        log.info(
            "done — %d ingested, %d skipped, %d documents total",
            ingested,
            len(documents) - ingested,
            len(documents),
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
