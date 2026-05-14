"""Tests for src.config — specifically the require_anthropic_api_key boundary."""

from __future__ import annotations

import pytest

from src import config
from src.config import require_anthropic_api_key


def test_returns_key_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-fake")
    assert require_anthropic_api_key() == "sk-ant-fake"


def test_raises_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY is not set"):
        require_anthropic_api_key()
