"""Tests for src.config — Settings hierarchy + the require_* secret boundaries."""

from __future__ import annotations

import pytest

from src.config import (
    Settings,
    require_anthropic_api_key,
    require_database_url,
    require_voyage_api_key,
    settings,
)


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


def test_voyage_key_returned_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOYAGE_API_KEY", "pa-voyage-fake")
    assert require_voyage_api_key() == "pa-voyage-fake"


def test_voyage_key_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="VOYAGE_API_KEY is not set"):
        require_voyage_api_key()


def test_database_url_returned_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
    assert require_database_url() == "postgresql://localhost/test"


def test_database_url_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
        require_database_url()


class TestSettings:
    """The typed Settings hierarchy — defaults, structure, env var overrides."""

    def test_defaults_load_when_no_overrides(self) -> None:
        s = Settings()
        assert s.agent.model == "claude-sonnet-4-6"
        assert s.agent.max_tokens == 16384
        assert s.agent.effort == "medium"
        assert s.vision.model == "claude-haiku-4-5"
        assert s.vision.default_max_photos == 20
        assert s.scraping.user_agent.startswith("Mozilla/5.0")
        assert s.memo_preamble_marker == "# Investment Memo:"
        # RAG section — model and the pgvector column dimension must agree.
        assert s.rag.voyage_model == "voyage-3.5"
        assert s.rag.embedding_dim == 1024
        assert s.rag.chunk_overlap_chars < s.rag.chunk_target_chars

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
