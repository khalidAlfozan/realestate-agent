"""Hand-rolled agent loop using the Anthropic SDK and Claude tool-use."""

from __future__ import annotations

import json
import logging
from typing import Any, cast

import anthropic
from anthropic.types import MessageParam
from pydantic import BaseModel

from src.config import PROMPTS, settings
from src.tools import FUNCTIONS, SCHEMAS

SYSTEM_PROMPT = (PROMPTS / "system.md").read_text()

log = logging.getLogger(__name__)


def _execute_tool(name: str, arguments: dict[str, Any]) -> str:
    fn = FUNCTIONS.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        result = fn(**arguments)
        if isinstance(result, BaseModel):
            return result.model_dump_json()
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as exc:
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})


def _log_iteration(iteration: int, response: anthropic.types.Message) -> None:
    usage = response.usage
    log.info(
        "iter=%d stop=%s in=%d out=%d cache_read=%d cache_write=%d",
        iteration,
        response.stop_reason,
        usage.input_tokens,
        usage.output_tokens,
        getattr(usage, "cache_read_input_tokens", 0),
        getattr(usage, "cache_creation_input_tokens", 0),
    )


def run_agent(
    client: anthropic.Anthropic,
    user_message: str,
    *,
    max_iterations: int = 10,
) -> str:
    """Drive the agent loop until end_turn; return the final assistant text.

    The Anthropic client is injected so callers (CLI, eval harness, future
    Streamlit UI) can swap in recording / mocking clients without touching
    the loop.
    """
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]

    for iteration in range(max_iterations):
        # cache_control on the last system block caches tools+system together
        # (tools render before system in the request). Stable prefix → cache
        # hits on every iteration after the first.
        response = client.messages.create(
            model=settings.agent.model,
            max_tokens=settings.agent.max_tokens,
            thinking={"type": "adaptive"},
            output_config={"effort": settings.agent.effort},
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=SCHEMAS,
            messages=cast(list[MessageParam], messages),
        )
        _log_iteration(iteration, response)

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            return next(
                (block.text for block in response.content if block.type == "text"),
                "",
            )

        if response.stop_reason != "tool_use":
            raise RuntimeError(f"Unexpected stop_reason: {response.stop_reason!r}")

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": _execute_tool(block.name, block.input),
                    }
                )
        messages.append({"role": "user", "content": tool_results})

    raise RuntimeError(f"Agent exceeded max_iterations={max_iterations}")
