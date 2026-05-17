"""Tests for evals.snapshot — the tool-result record/replay the eval harness
uses. evals/ is not coverage-counted, but the snapshot mechanism is what keeps
eval cases reproducible, so the record -> replay round-trip is tested here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import src.agent as agent
from evals import snapshot


def test_key_is_stable() -> None:
    assert snapshot._key("t", {"a": 1}) == snapshot._key("t", {"a": 1})


def test_key_is_arg_order_independent() -> None:
    assert snapshot._key("t", {"a": 1, "b": 2}) == snapshot._key("t", {"b": 2, "a": 1})


def test_record_then_replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The first run records tool results; a re-run replays them without
    touching the live tool."""
    monkeypatch.setattr(snapshot, "SNAPSHOTS_DIR", tmp_path)
    calls: list[str] = []

    def fake_execute(name: str, arguments: dict[str, Any]) -> str:
        calls.append(name)
        return f'{{"tool": "{name}"}}'

    monkeypatch.setattr(agent, "_execute_tool", fake_execute)

    with snapshot.recording("demo"):
        out = agent._execute_tool("get_property_details", {"url": "u1"})
    assert out == '{"tool": "get_property_details"}'
    assert calls == ["get_property_details"]
    assert snapshot.snapshot_path("demo").is_file()

    with snapshot.replaying("demo"):
        replayed = agent._execute_tool("get_property_details", {"url": "u1"})
    assert replayed == '{"tool": "get_property_details"}'
    assert calls == ["get_property_details"]  # replayed from the snapshot, not re-called


def test_replay_miss_falls_back_to_live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A call the snapshot doesn't hold falls back to a live call."""
    monkeypatch.setattr(snapshot, "SNAPSHOTS_DIR", tmp_path)
    calls: list[str] = []

    def fake_execute(name: str, arguments: dict[str, Any]) -> str:
        calls.append(name)
        return "{}"

    monkeypatch.setattr(agent, "_execute_tool", fake_execute)

    with snapshot.recording("demo"):
        agent._execute_tool("get_property_details", {"url": "u1"})
    with snapshot.replaying("demo"):
        agent._execute_tool("search_market_reports", {"query": "unseen"})

    assert calls == ["get_property_details", "search_market_reports"]
