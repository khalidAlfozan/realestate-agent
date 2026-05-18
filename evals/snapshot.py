"""Tool-result snapshots — keeping eval cases reproducible.

A case's first run records every tool call's `(name, args) -> result` to
`snapshots/<case_id>.json`. Later runs replay from that file, so a case
survives its Otodom listing delisting and re-runs against fixed tool inputs.

Only the *tools* are frozen — the agent's own LLM calls always run live.
That is the point: the eval-gated prompt pass re-runs the reasoning against
the same tool inputs to see whether the memo improves.

A snapshot miss (e.g. a prompt change issues a market-report query the
snapshot does not hold) falls back to a live call. Replay never writes the
snapshot back, so running the suite cannot dirty a committed fixture —
refresh one deliberately with `run_evals --rerecord`.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import src.agent as agent

SNAPSHOTS_DIR = Path(__file__).resolve().parent / "snapshots"


def _key(name: str, arguments: dict[str, Any]) -> str:
    """Stable lookup key for one tool call — name plus order-independent args."""
    return f"{name}|{json.dumps(arguments, sort_keys=True, ensure_ascii=False)}"


def snapshot_path(case_id: str) -> Path:
    return SNAPSHOTS_DIR / f"{case_id}.json"


def has_snapshot(case_id: str) -> bool:
    return snapshot_path(case_id).is_file()


@contextmanager
def recording(case_id: str) -> Iterator[None]:
    """Run live, recording every tool result to the case's snapshot file."""
    recorded: dict[str, str] = {}
    lock = threading.Lock()
    real = agent._execute_tool

    def record(name: str, arguments: dict[str, Any]) -> str:
        result = real(name, arguments)
        with lock:
            recorded[_key(name, arguments)] = result
        return result

    agent._execute_tool = record
    try:
        yield
    finally:
        agent._execute_tool = real
    # Write only on clean completion. If the body raised (network drop, a
    # max_tokens stop, ...) the recording is partial — writing it would make
    # has_snapshot() true, so later runs would replay the incomplete fixture
    # instead of re-recording. Leaving no file is the safe state.
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_path(case_id).write_text(
        json.dumps(recorded, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )


@contextmanager
def replaying(case_id: str) -> Iterator[None]:
    """Serve tool results from the case's snapshot; a miss falls back to a
    live call. Read-only — never writes the snapshot back."""
    recorded: dict[str, str] = json.loads(snapshot_path(case_id).read_text())
    real = agent._execute_tool

    def replay(name: str, arguments: dict[str, Any]) -> str:
        hit = recorded.get(_key(name, arguments))
        return hit if hit is not None else real(name, arguments)

    agent._execute_tool = replay
    try:
        yield
    finally:
        agent._execute_tool = real
