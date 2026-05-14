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

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if not ANTHROPIC_API_KEY:
    raise RuntimeError(
        "ANTHROPIC_API_KEY is not set. Create a .env file at the project root "
        "(`cp .env.example .env`) and add a key from "
        "https://console.anthropic.com/settings/keys"
    )

MODEL_AGENT = "claude-sonnet-4-6"
MAX_TOKENS = 8192
