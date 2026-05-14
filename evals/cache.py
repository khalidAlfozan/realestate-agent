"""File-based memo cache keyed by case id + system-prompt hash.

The hash means a system-prompt change auto-invalidates all cached memos
(re-running the agent on next eval), which is the regression-detection
behaviour we want — a prompt change should be re-evaluated, not silently
served from cache.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent / "cache"


def _hash_prompt(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]


def cache_path(case_id: str, system_prompt: str) -> Path:
    return CACHE_DIR / f"{case_id}-{_hash_prompt(system_prompt)}.md"


def load(case_id: str, system_prompt: str) -> str | None:
    path = cache_path(case_id, system_prompt)
    return path.read_text() if path.is_file() else None


def save(case_id: str, system_prompt: str, memo: str) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path(case_id, system_prompt).write_text(memo)
