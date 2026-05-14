"""Pydantic models for the eval harness — cases, parsed memos, results."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Expected(_Frozen):
    """Assertions to apply to a parsed memo. All fields optional — only the
    ones you set are checked. A case with an empty Expected always passes
    (useful for "just record the output, don't grade it yet")."""

    # Verdict / confidence — list of acceptable values; actual must be in the list.
    verdict_in: list[str] | None = None
    confidence_in: list[str] | None = None

    # Yield range — actual must satisfy min <= x <= max if both set.
    gross_yield_pct_min: float | None = None
    gross_yield_pct_max: float | None = None

    # Tool-coverage assertions — make sure the agent actually used the tools.
    photos_analysed_min: int | None = None
    rent_comp_count_min: int | None = None
    sale_comp_count_min: int | None = None

    # Substrings that must appear in §6 (Risks). Case-insensitive.
    risks_must_include: list[str] = []


class EvalCase(_Frozen):
    """One ground-truth case — a URL plus what we expect the memo to say."""

    id: str
    url: str
    notes: str = ""
    expected: Expected = Field(default_factory=Expected)


class ParsedMemo(_Frozen):
    """Structured extraction of a memo's key fields. None when the regex
    didn't match — usually a sign the memo template changed."""

    verdict: str | None = None
    confidence: str | None = None
    gross_yield_pct: float | None = None
    photo_condition: str | None = None
    photos_analysed: int | None = None
    rent_comp_count: int | None = None
    sale_comp_count: int | None = None
    risks_text: str = ""  # the whole §6 body, for substring matching


class EvalCheck(_Frozen):
    """One assertion's outcome."""

    name: str
    passed: bool
    expected: Any
    actual: Any
    note: str = ""


class EvalResult(BaseModel):
    """Aggregate result for one case — parsed memo + per-assertion outcomes.

    Not frozen because we build it up via .model_copy(update=...). Acceptable.
    """

    case_id: str
    parsed: ParsedMemo
    checks: list[EvalCheck]
    cached: bool = False

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)
