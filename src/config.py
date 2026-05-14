"""Project config: env vars and shared paths."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "src" / "prompts"

# Look for .env at the project root first; fall back to walking up from CWD
# (so a worktree or subdirectory can share the main repo's .env).
# override=True so a stale shell-level ANTHROPIC_API_KEY="" can't shadow it.
_env_path = ROOT / ".env"
load_dotenv(_env_path if _env_path.is_file() else find_dotenv(usecwd=True), override=True)

# Defaults to "" (not None and not raised) so importing this module is safe in
# environments without a key — notably CI test runs that don't need API access.
# Code that actually constructs an Anthropic client should call
# `require_anthropic_api_key()` to fail loudly at the point of use.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

MODEL_AGENT = "claude-sonnet-4-6"
MAX_TOKENS = 8192


def require_anthropic_api_key() -> str:
    """Return the API key, raising a helpful error if it's missing.

    Use this at the point of client construction (CLI startup, tool functions
    that lazily build a client) rather than reading the constant directly —
    this way modules can be imported in test/CI contexts without a key.
    """
    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Create a .env file at the project root "
            "(`cp .env.example .env`) and add a key from "
            "https://console.anthropic.com/settings/keys"
        )
    return ANTHROPIC_API_KEY
