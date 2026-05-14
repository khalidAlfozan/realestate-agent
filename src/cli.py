"""CLI entry point: takes an Otodom URL, prints the agent's memo to stdout.

Run from the project root:
    uv run python -m src <otodom-url>
"""

from __future__ import annotations

import logging
import sys

import anthropic

from src.agent import run_agent
from src.config import ANTHROPIC_API_KEY


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 1:
        print("usage: python -m src <otodom-url>", file=sys.stderr)
        return 1

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    url = args[0]
    memo = run_agent(
        client, f"Analyse this Warsaw property as a long-term rental investment: {url}"
    )
    print(memo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
