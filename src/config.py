"""Project config: typed Settings hierarchy with layered overrides.

Single source of truth for runtime configuration (model IDs, timeouts,
photo defaults, etc). What used to be scattered constants across half
a dozen modules now lives here.

Layered precedence (lowest to highest):
1. Defaults — declared in the Settings classes below.
2. `realestate-agent.toml` at the project root — for project-wide
   overrides committed to version control.
3. Environment variables prefixed `RA_`, with `__` for nesting —
   for ad-hoc / per-run overrides without editing files.
   E.g. `RA_AGENT__MODEL=claude-opus-4-7` overrides `agent.model`.
4. `.env` at the project root — secrets only (`ANTHROPIC_API_KEY`).
   Loaded by `load_dotenv` before Settings reads env vars, so the
   .env values appear in `os.environ` as if they'd been exported.

Secrets (notably the Anthropic API key) are deliberately NOT in the
TOML file — they live only in `.env` (which is gitignored) or real
env vars. This is the standard secrets-out-of-config pattern.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import find_dotenv, load_dotenv
from pydantic import BaseModel, ConfigDict
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "src" / "prompts"
TOML_CONFIG_FILE = ROOT / "realestate-agent.toml"

# Load .env BEFORE BaseSettings reads env vars. override=True so a stale
# shell-level ANTHROPIC_API_KEY="" can't shadow the real value in .env.
_env_path = ROOT / ".env"
load_dotenv(_env_path if _env_path.is_file() else find_dotenv(usecwd=True), override=True)


class _Section(BaseModel):
    """Strict base for nested config sections — typo in field name fails at parse time."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class AgentSettings(_Section):
    """Settings for the main agent loop (Claude Sonnet 4.6 by default)."""

    model: str = "claude-sonnet-4-6"
    max_tokens: int = 8192
    # Effort controls thinking depth + overall token spend on Sonnet 4.6.
    # `medium` is the recommended balance for tool-heavy agentic flows.
    effort: Literal["low", "medium", "high", "max"] = "medium"


class VisionSettings(_Section):
    """Settings for the photo-analysis sub-call (Claude Haiku 4.5 by default)."""

    model: str = "claude-haiku-4-5"
    max_tokens: int = 1024
    # Cap on photos sent per call — caps cost. The agent can override per-call.
    default_max_photos: int = 20
    # Per-image fetch timeout when downloading from Otodom's CDN to base64.
    fetch_timeout_s: float = 15.0


class ScrapingSettings(_Section):
    """Settings for the HTTP scraping path (Otodom listings + search results)."""

    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    request_timeout_s: float = 15.0


class GusBdlSettings(_Section):
    """Settings for GUS BDL (Bank Danych Lokalnych) API.

    The API key itself is a secret — read via `require_gus_bdl_api_key()`,
    not stored here.
    """

    base_url: str = "https://bdl.stat.gov.pl/api/v1"
    request_timeout_s: float = 10.0


class Settings(BaseSettings):
    """Top-level settings, layered: TOML file < env vars (RA_ prefix).

    Use `from src.config import settings` and read `settings.agent.model` etc.
    Avoid mutating; for tests, monkeypatch the specific fields instead.
    """

    model_config = SettingsConfigDict(
        toml_file=str(TOML_CONFIG_FILE),
        env_prefix="RA_",
        env_nested_delimiter="__",
        extra="forbid",
    )

    agent: AgentSettings = AgentSettings()
    vision: VisionSettings = VisionSettings()
    scraping: ScrapingSettings = ScrapingSettings()
    gus_bdl: GusBdlSettings = GusBdlSettings()
    # The marker the CLI / eval harness uses to strip preamble before printing
    # the memo. Exposed here so the two consumers can't drift.
    memo_preamble_marker: str = "# Investment Memo:"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Order matters — earlier sources win on conflict.
        # init kwargs > env vars > .env file > TOML file > defaults
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


# Single instance, instantiated at import time. Reading is cheap; writing
# isn't supported — use env vars / TOML to override.
settings = Settings()


def require_anthropic_api_key() -> str:
    """Return the Anthropic API key, raising a helpful error if missing.

    Secrets are NOT part of `Settings` — they live only in `.env` (gitignored)
    or real env vars. Call this at the point of client construction so a
    missing key surfaces with a clear message rather than as an opaque API
    auth error.
    """
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Create a .env file at the project root "
            "(`cp .env.example .env`) and add a key from "
            "https://console.anthropic.com/settings/keys"
        )
    return key


def require_gus_bdl_api_key() -> str:
    """Return the GUS BDL API key, raising a helpful error if missing.

    Same secrets-out-of-config pattern as the Anthropic key. The key is sent
    as the X-ClientId header on every BDL request.
    """
    key = os.environ.get("GUS_BDL_API_KEY", "")
    if not key:
        raise RuntimeError(
            "GUS_BDL_API_KEY is not set. Register a free key at "
            "https://api.stat.gov.pl/Home/BdlApi and add it to .env."
        )
    return key
