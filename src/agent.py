"""Hand-rolled agent loop using the Anthropic SDK and Claude tool-use."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, cast

import anthropic
from anthropic.types import MessageParam
from pydantic import BaseModel

from src.config import PROMPTS, settings
from src.cost import compute_cost_usd
from src.tools import FUNCTIONS, SCHEMAS

SYSTEM_PROMPT = (PROMPTS / "system.md").read_text()

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunResult:
    """The full result of a single `run_agent` invocation.

    `memo` is the agent's final text. The other fields are the metrics the
    CLI / eval harness / future dashboards care about. Returning a typed
    object instead of a bare string makes observability a first-class
    concern of the API rather than a side-channel via logs.
    """

    memo: str
    iterations: int
    tool_calls: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    elapsed_s: float


def build_analysis_request(url: str) -> str:
    """Build the user message that kicks off a memo run for an Otodom listing.

    Single source of truth for the run prompt — both the CLI and the Streamlit
    UI call this, so the agent gets an identical instruction regardless of the
    entry point.
    """
    return f"Analyse this Warsaw property as a long-term rental investment: {url}"


def strip_memo_preamble(memo: str) -> str:
    """Drop any text before the memo's `# Investment Memo:` marker.

    Belt-and-suspenders for the system prompt's no-preamble rule: Sonnet 4.6
    occasionally prepends a transition acknowledgment ("All tools done, writing
    the memo now") at the end of a long tool chain. If the marker is absent
    (shouldn't happen), the text is returned unchanged so the operator can see
    whatever the model produced.
    """
    marker = settings.memo_preamble_marker
    if marker in memo:
        return memo[memo.index(marker) :]
    return memo


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


def _log_iteration(
    iteration: int,
    response: anthropic.types.Message,
    tool_calls_this_iter: int,
    cost_usd: float,
) -> None:
    usage = response.usage
    log.info(
        "iter=%d stop=%s in=%d out=%d cache_read=%d cache_write=%d tools=%d cost_usd=%.4f",
        iteration,
        response.stop_reason,
        usage.input_tokens,
        usage.output_tokens,
        getattr(usage, "cache_read_input_tokens", 0),
        getattr(usage, "cache_creation_input_tokens", 0),
        tool_calls_this_iter,
        cost_usd,
    )


def run_agent(
    client: anthropic.Anthropic,
    user_message: str,
    *,
    max_iterations: int = 10,
) -> RunResult:
    """Drive the agent loop until end_turn; return the memo + run metrics.

    The Anthropic client is injected so callers (CLI, eval harness, future
    Streamlit UI) can swap in recording / mocking clients without touching
    the loop. Per-iteration metrics are logged at INFO; the full RunResult
    is returned for callers that want to display / persist them.
    """
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]

    started = time.monotonic()
    total_input = 0
    total_output = 0
    total_cache_read = 0
    total_cache_write = 0
    total_cost = 0.0
    total_tool_calls = 0
    final_text = ""
    iteration = 0

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

        # Count tool_use blocks in this response (= API calls the agent
        # asked us to make on its behalf this iteration).
        tool_calls_this_iter = sum(1 for b in response.content if b.type == "tool_use")

        # Per-iteration cost. Settings.agent.model is the model we billed at.
        iter_cost = compute_cost_usd(settings.agent.model, response.usage)

        _log_iteration(iteration, response, tool_calls_this_iter, iter_cost)

        # Accumulate run-level totals.
        usage = response.usage
        total_input += usage.input_tokens
        total_output += usage.output_tokens
        total_cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0
        total_cache_write += getattr(usage, "cache_creation_input_tokens", 0) or 0
        total_cost += iter_cost
        total_tool_calls += tool_calls_this_iter

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            final_text = next(
                (block.text for block in response.content if block.type == "text"),
                "",
            )
            return RunResult(
                memo=final_text,
                iterations=iteration + 1,
                tool_calls=total_tool_calls,
                input_tokens=total_input,
                output_tokens=total_output,
                cache_read_tokens=total_cache_read,
                cache_write_tokens=total_cache_write,
                cost_usd=total_cost,
                elapsed_s=time.monotonic() - started,
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
