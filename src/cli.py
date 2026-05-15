"""CLI entry point: takes an Otodom URL, prints the agent's memo to stdout.

Run from the project root:
    uv run python -m src <otodom-url>
"""

from __future__ import annotations

import logging
import sys

import anthropic

from src.agent import build_analysis_request, run_agent, strip_memo_preamble
from src.config import require_anthropic_api_key
from src.url_validation import InvalidOtodomURLError, validate_otodom_listing_url


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 1:
        print("usage: python -m src <otodom-url>", file=sys.stderr)
        return 1

    url = args[0]
    # Fail fast on obvious typos / wrong sites BEFORE constructing the client
    # or hitting the API. Saves both Anthropic tokens and ~10 seconds of latency.
    try:
        validate_otodom_listing_url(url)
    except InvalidOtodomURLError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    client = anthropic.Anthropic(api_key=require_anthropic_api_key())
    result = run_agent(client, build_analysis_request(url))
    print(strip_memo_preamble(result.memo))

    # Run summary to stderr — visible to the operator alongside the memo.
    log = logging.getLogger("src.cli")
    log.info(
        "run_summary iterations=%d tools=%d in=%d out=%d "
        "cache_read=%d cache_write=%d cost_usd=%.4f elapsed_s=%.1f",
        result.iterations,
        result.tool_calls,
        result.input_tokens,
        result.output_tokens,
        result.cache_read_tokens,
        result.cache_write_tokens,
        result.cost_usd,
        result.elapsed_s,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
