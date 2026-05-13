"""Project config: env vars and shared paths."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "src" / "prompts"

# override=True so a stale (or empty) shell-level env var doesn't shadow .env
load_dotenv(ROOT / ".env", override=True)

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

MODEL_AGENT = "claude-sonnet-4-6"
MAX_TOKENS = 8192
