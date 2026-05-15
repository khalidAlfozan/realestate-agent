"""Tests for src.config — Settings hierarchy + require_anthropic_api_key boundary."""

from __future__ import annotations

import pytest

from src.config import Settings, require_anthropic_api_key, settings


def test_returns_key_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """The function reads from os.environ at call time so a freshly-set key
    becomes immediately available without re-importing the module."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    assert require_anthropic_api_key() == "sk-ant-fake"


def test_raises_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY is not set"):
        require_anthropic_api_key()


def test_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY is not set"):
        require_anthropic_api_key()


class TestSettings:
    """The typed Settings hierarchy — defaults, structure, env var overrides."""

    def test_defaults_load_when_no_overrides(self) -> None:
        s = Settings()
        assert s.agent.model == "claude-sonnet-4-6"
        assert s.agent.max_tokens == 8192
        assert s.agent.effort == "medium"
        assert s.vision.model == "claude-haiku-4-5"
        assert s.vision.default_max_photos == 20
        assert s.scraping.user_agent.startswith("Mozilla/5.0")
        assert s.memo_preamble_marker == "# Investment Memo:"

    def test_env_var_overrides_nested_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """RA_<SECTION>__<KEY> overrides defaults — the documented pattern
        for ad-hoc per-run tuning without editing files."""
        monkeypatch.setenv("RA_AGENT__MODEL", "claude-opus-4-7")
        monkeypatch.setenv("RA_AGENT__MAX_TOKENS", "16000")
        s = Settings()
        assert s.agent.model == "claude-opus-4-7"
        assert s.agent.max_tokens == 16000
        # Untouched fields keep their defaults.
        assert s.agent.effort == "medium"

    def test_env_var_overrides_top_level_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RA_MEMO_PREAMBLE_MARKER", "# Memo:")
        s = Settings()
        assert s.memo_preamble_marker == "# Memo:"

    def test_module_level_singleton_loaded(self) -> None:
        """The module's `settings` instance is what callers use; verify it
        loads cleanly with whatever's in the environment at import time."""
        assert isinstance(settings, Settings)
        assert settings.agent.model  # non-empty
        assert settings.vision.model  # non-empty
