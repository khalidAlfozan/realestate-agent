"""Hand-rolled agent loop using the Anthropic SDK and Claude tool-use.

Run from the project root:
    uv run python -m src.agent <fotocasa-url>
"""
from __future__ import annotations

import json
import sys
from typing import Any

import anthropic

from src.config import ANTHROPIC_API_KEY, MAX_TOKENS, MODEL_AGENT, PROMPTS
from src.tools import TOOL_FUNCTIONS, TOOLS

SYSTEM_PROMPT = (PROMPTS / "system.md").read_text()


def _execute_tool(name: str, arguments: dict[str, Any]) -> str:
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        result = fn(**arguments)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as exc:
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})


def _log_iteration(iteration: int, response: anthropic.types.Message) -> None:
    usage = response.usage
    print(
        f"[iter {iteration}] stop={response.stop_reason} "
        f"in={usage.input_tokens} out={usage.output_tokens} "
        f"cache_read={getattr(usage, 'cache_read_input_tokens', 0)} "
        f"cache_write={getattr(usage, 'cache_creation_input_tokens', 0)}",
        file=sys.stderr,
    )


def run_agent(user_message: str, *, max_iterations: int = 10) -> str:
    """Drive the agent loop until end_turn; return the final assistant text."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]

    for iteration in range(max_iterations):
        # cache_control on the last system block caches tools+system together
        # (tools render before system in the request). Stable prefix → cache hits
        # on every iteration after the first.
        response = client.messages.create(
            model=MODEL_AGENT,
            max_tokens=MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=TOOLS,
            messages=messages,
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


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python -m src.agent <fotocasa-url>", file=sys.stderr)
        return 1
    url = sys.argv[1]
    memo = run_agent(
        f"Analyse this Madrid property as a long-term rental investment: {url}"
    )
    print(memo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
