"""Run the agent against ground-truth cases and report which assertions pass.

Usage:
    uv run python -m evals.run_evals                 # run all cases
    uv run python -m evals.run_evals --case wola-1959  # one case by id
    uv run python -m evals.run_evals --no-cache      # force re-run
    uv run python -m evals.run_evals --verbose       # also print full memos
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import anthropic
from pydantic import TypeAdapter

from evals import cache as memo_cache
from evals.models import EvalCase, EvalCheck, EvalResult, Expected, ParsedMemo
from evals.parse_memo import parse_memo
from src.agent import SYSTEM_PROMPT, run_agent
from src.config import require_anthropic_api_key

CASES_FILE = Path(__file__).resolve().parent / "cases.json"
MEMO_PREAMBLE_MARKER = "# Investment Memo:"


def load_cases() -> list[EvalCase]:
    """Load cases.json, validated by Pydantic."""
    raw = json.loads(CASES_FILE.read_text())
    return TypeAdapter(list[EvalCase]).validate_python(raw)


def run_eval_case(
    client: anthropic.Anthropic, case: EvalCase, *, no_cache: bool = False
) -> tuple[str, bool]:
    """Run the agent on one case, returning (memo, was_cached). Caches by
    case_id + system_prompt hash so prompt changes invalidate the cache."""
    if not no_cache:
        cached = memo_cache.load(case.id, SYSTEM_PROMPT)
        if cached:
            return cached, True

    user_message = f"Analyse this Warsaw property as a long-term rental investment: {case.url}"
    memo = run_agent(client, user_message)
    # Belt-and-suspenders preamble strip (mirrors src.cli's behaviour).
    if MEMO_PREAMBLE_MARKER in memo:
        memo = memo[memo.index(MEMO_PREAMBLE_MARKER) :]
    memo_cache.save(case.id, SYSTEM_PROMPT, memo)
    return memo, False


def evaluate(case: EvalCase, parsed: ParsedMemo) -> list[EvalCheck]:
    """Apply each Expected assertion that's set; skip the ones that aren't."""
    e = case.expected
    checks: list[EvalCheck] = []

    if e.verdict_in is not None:
        checks.append(_check_in("verdict", e.verdict_in, parsed.verdict))
    if e.confidence_in is not None:
        checks.append(_check_in("confidence", e.confidence_in, parsed.confidence))

    if e.gross_yield_pct_min is not None or e.gross_yield_pct_max is not None:
        checks.append(_check_in_range("gross_yield_pct", parsed.gross_yield_pct, e))

    if e.photos_analysed_min is not None:
        checks.append(_check_min("photos_analysed", e.photos_analysed_min, parsed.photos_analysed))
    if e.rent_comp_count_min is not None:
        checks.append(_check_min("rent_comp_count", e.rent_comp_count_min, parsed.rent_comp_count))
    if e.sale_comp_count_min is not None:
        checks.append(_check_min("sale_comp_count", e.sale_comp_count_min, parsed.sale_comp_count))

    if e.risks_must_include:
        for needle in e.risks_must_include:
            checks.append(
                EvalCheck(
                    name=f"risks_include({needle!r})",
                    passed=needle.lower() in parsed.risks_text.lower(),
                    expected=needle,
                    actual="(found)"
                    if needle.lower() in parsed.risks_text.lower()
                    else "(missing)",
                )
            )

    return checks


def _check_in(name: str, allowed: list[str], actual: str | None) -> EvalCheck:
    return EvalCheck(
        name=name,
        passed=actual is not None and actual in allowed,
        expected=f"one of {allowed}",
        actual=actual,
    )


def _check_min(name: str, minimum: int, actual: int | None) -> EvalCheck:
    return EvalCheck(
        name=name,
        passed=actual is not None and actual >= minimum,
        expected=f">= {minimum}",
        actual=actual,
    )


def _check_in_range(name: str, actual: float | None, e: Expected) -> EvalCheck:
    if actual is None:
        return EvalCheck(name=name, passed=False, expected="numeric", actual=None)
    if e.gross_yield_pct_min is not None and actual < e.gross_yield_pct_min:
        return EvalCheck(
            name=name, passed=False, expected=f">= {e.gross_yield_pct_min}", actual=actual
        )
    if e.gross_yield_pct_max is not None and actual > e.gross_yield_pct_max:
        return EvalCheck(
            name=name, passed=False, expected=f"<= {e.gross_yield_pct_max}", actual=actual
        )
    bounds = []
    if e.gross_yield_pct_min is not None:
        bounds.append(f">= {e.gross_yield_pct_min}")
    if e.gross_yield_pct_max is not None:
        bounds.append(f"<= {e.gross_yield_pct_max}")
    return EvalCheck(name=name, passed=True, expected=" and ".join(bounds), actual=actual)


def print_case_result(case: EvalCase, result: EvalResult) -> None:
    """Pretty-print one case result to stdout."""
    cached_tag = " [cached]" if result.cached else ""
    status = "PASS" if result.passed else "FAIL"
    print(f"\n== {case.id}{cached_tag}: {status} ==")
    print(f"  url: {case.url}")
    if case.notes:
        print(f"  notes: {case.notes}")
    print(
        f"  parsed: verdict={result.parsed.verdict}, "
        f"confidence={result.parsed.confidence}, "
        f"yield={result.parsed.gross_yield_pct}%, "
        f"photos={result.parsed.photos_analysed}, "
        f"rent_comps={result.parsed.rent_comp_count}, "
        f"sale_comps={result.parsed.sale_comp_count}"
    )

    if not result.checks:
        print("  (no assertions configured — recorded only)")
    for check in result.checks:
        mark = "✓" if check.passed else "✗"
        print(f"  {mark} {check.name}: actual={check.actual!r}, expected={check.expected!r}")


def print_summary(results: list[EvalResult]) -> None:
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print(f"\n== SUMMARY ==\n  {passed} / {total} cases passed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the agent against ground-truth eval cases.")
    parser.add_argument("--case", help="Run only the case with this id.")
    parser.add_argument("--no-cache", action="store_true", help="Force re-run even if cached.")
    parser.add_argument(
        "--verbose", action="store_true", help="Also print the full memo for each case."
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    cases = load_cases()
    if args.case:
        cases = [c for c in cases if c.id == args.case]
        if not cases:
            print(f"No case with id={args.case!r} in {CASES_FILE}", file=sys.stderr)
            return 2

    if not cases:
        print(f"No cases in {CASES_FILE} — add some to evaluate.", file=sys.stderr)
        return 0

    client = anthropic.Anthropic(api_key=require_anthropic_api_key())

    results: list[EvalResult] = []
    for case in cases:
        memo, was_cached = run_eval_case(client, case, no_cache=args.no_cache)
        parsed = parse_memo(memo)
        checks = evaluate(case, parsed)
        result = EvalResult(case_id=case.id, parsed=parsed, checks=checks, cached=was_cached)
        results.append(result)
        print_case_result(case, result)
        if args.verbose:
            print("\n--- memo ---")
            print(memo)
            print("--- end memo ---\n")

    print_summary(results)
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
