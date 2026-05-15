"""CLI entry point: takes an Otodom URL, prints the agent's memo to stdout.

Run from the project root:
    uv run python -m src <otodom-url>
"""

from __future__ import annotations

import logging
import sys

import anthropic

from src.agent import run_agent
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
    memo = run_agent(
        client, f"Analyse this Warsaw property as a long-term rental investment: {url}"
    )
    # Belt-and-suspenders for the system prompt's "no preamble" rule:
    # Sonnet 4.6 occasionally prepends a transition acknowledgment ("All
    # tools done, writing the memo now") at the end of long tool chains.
    # Strip anything before the memo's actual start.
    marker = "# Investment Memo:"
    if marker in memo:
        memo = memo[memo.index(marker) :]
    print(memo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
