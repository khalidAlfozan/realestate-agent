"""Tests for the hand-rolled agent loop.

The Anthropic client is fully mocked — no API calls in CI. We use
MagicMock to fabricate `Message`-shaped responses with the attribute
access pattern the loop relies on (`response.content[i].type`,
`response.stop_reason`, `response.usage.input_tokens`, etc.).
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from src.agent import (
    _execute_tool,
    _format_tool_names,
    build_analysis_request,
    run_agent,
    strip_memo_preamble,
)

# --------------------------------------------------------------------------- #
# Helpers — fake Anthropic Messages with the shape the loop reads.
# --------------------------------------------------------------------------- #


def _fake_usage(in_tokens: int = 100, out_tokens: int = 50) -> MagicMock:
    usage = MagicMock()
    usage.input_tokens = in_tokens
    usage.output_tokens = out_tokens
    usage.cache_read_input_tokens = 0
    usage.cache_creation_input_tokens = 0
    return usage


def _fake_text_response(text: str) -> MagicMock:
    """Build a fake Message with stop_reason=end_turn carrying one text block."""
    msg = MagicMock()
    msg.stop_reason = "end_turn"
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = text
    msg.content = [text_block]
    msg.usage = _fake_usage()
    return msg


def _fake_tool_use_response(
    name: str, args: dict[str, Any], tool_use_id: str = "toolu_01"
) -> MagicMock:
    """Build a fake Message with stop_reason=tool_use carrying one tool_use block."""
    msg = MagicMock()
    msg.stop_reason = "tool_use"
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = name
    tool_block.input = args
    tool_block.id = tool_use_id
    msg.content = [tool_block]
    msg.usage = _fake_usage()
    return msg


def _fake_unexpected_stop_response() -> MagicMock:
    msg = MagicMock()
    msg.stop_reason = "max_tokens"
    msg.content = []
    msg.usage = _fake_usage()
    return msg


def _fake_multi_tool_use_response(calls: list[tuple[str, str]]) -> MagicMock:
    """Build a fake tool_use Message with one tool_use block per (name, id)."""
    blocks = []
    for name, tool_use_id in calls:
        block = MagicMock()
        block.type = "tool_use"
        block.name = name
        block.id = tool_use_id
        block.input = {}
        blocks.append(block)
    msg = MagicMock()
    msg.stop_reason = "tool_use"
    msg.content = blocks
    msg.usage = _fake_usage()
    return msg


# --------------------------------------------------------------------------- #
# _execute_tool — the dispatcher around the FUNCTIONS registry.
# --------------------------------------------------------------------------- #


class TestExecuteTool:
    def test_dispatches_to_registered_function(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_get(url: str) -> dict[str, Any]:
            return {"price_pln": 1_290_000, "url": url}

        monkeypatch.setattr("src.agent.FUNCTIONS", {"get_property_details": fake_get})

        result = _execute_tool("get_property_details", {"url": "https://example.com/x"})

        parsed = json.loads(result)
        assert parsed["price_pln"] == 1_290_000
        assert parsed["url"] == "https://example.com/x"

    def test_unknown_tool_returns_error_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("src.agent.FUNCTIONS", {})

        result = _execute_tool("nonexistent_tool", {})

        assert json.loads(result) == {"error": "Unknown tool: nonexistent_tool"}

    def test_tool_exception_returned_as_error_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exceptions in tools must be returned to the model, not propagated —
        otherwise the agent loop dies and the model can't adapt."""

        def boom(**kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("CDN blocked the request")

        monkeypatch.setattr("src.agent.FUNCTIONS", {"flaky": boom})

        result = _execute_tool("flaky", {"foo": "bar"})

        parsed = json.loads(result)
        assert "error" in parsed
        assert "RuntimeError" in parsed["error"]
        assert "CDN blocked" in parsed["error"]

    def test_pydantic_return_serialised_via_model_dump_json(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pydantic returns must use model_dump_json so they round-trip cleanly
        — calling json.dumps on a BaseModel would fail."""

        class FakeResult(BaseModel):
            price: int
            currency: str

        def fake_tool() -> FakeResult:
            return FakeResult(price=1_000_000, currency="PLN")

        monkeypatch.setattr("src.agent.FUNCTIONS", {"fake": fake_tool})

        result = _execute_tool("fake", {})

        assert json.loads(result) == {"price": 1_000_000, "currency": "PLN"}

    def test_dict_return_serialised_via_json_dumps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Plain-dict returns (calculate_gross_yield etc.) keep working."""

        def fake_yield() -> dict[str, Any]:
            return {"annual_rent_pln": 75_000, "gross_yield_pct": 5.81}

        monkeypatch.setattr("src.agent.FUNCTIONS", {"yld": fake_yield})

        result = _execute_tool("yld", {})

        assert json.loads(result) == {"annual_rent_pln": 75_000, "gross_yield_pct": 5.81}

    def test_non_ascii_strings_not_escaped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Polish characters in tool results must round-trip as UTF-8, not \\uXXXX."""

        def fake_tool() -> dict[str, str]:
            return {"district": "Śródmieście"}

        monkeypatch.setattr("src.agent.FUNCTIONS", {"t": fake_tool})

        result = _execute_tool("t", {})

        assert "Śródmieście" in result
        assert "\\u" not in result


# --------------------------------------------------------------------------- #
# run_agent — the main loop.
# --------------------------------------------------------------------------- #


class TestRunAgent:
    def test_returns_text_immediately_when_first_response_is_end_turn(self) -> None:
        client = MagicMock()
        client.messages.create.return_value = _fake_text_response("Final memo.")

        result = run_agent(client, "Analyse this URL")

        assert result.memo == "Final memo."
        assert client.messages.create.call_count == 1

    def test_executes_tool_then_returns_final_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The classic agentic flow: tool_use → execute → tool_result → end_turn."""

        def fake_tool(url: str) -> dict[str, str]:
            return {"price": "1M PLN"}

        monkeypatch.setattr("src.agent.FUNCTIONS", {"get_property_details": fake_tool})

        responses = [
            _fake_tool_use_response("get_property_details", {"url": "x"}, "toolu_01"),
            _fake_text_response("# Investment Memo: ..."),
        ]
        # Snapshot per-call message state at call time. `call_args_list` records
        # by-reference, so subsequent mutations to the messages list would
        # invalidate any direct inspection.
        snapshots: list[dict[str, Any]] = []

        def side_effect(**kwargs: Any) -> MagicMock:
            messages = kwargs["messages"]
            last = messages[-1]
            snapshots.append(
                {
                    "roles": [m["role"] for m in messages],
                    "last_role": last["role"],
                    "last_content_first_block_type": (
                        last["content"][0].get("type")
                        if isinstance(last["content"], list) and last["content"]
                        else None
                    ),
                    "last_tool_use_id": (
                        last["content"][0].get("tool_use_id")
                        if isinstance(last["content"], list) and last["content"]
                        else None
                    ),
                }
            )
            return responses.pop(0)

        client = MagicMock()
        client.messages.create.side_effect = side_effect

        result = run_agent(client, "Analyse this URL")

        assert result.memo == "# Investment Memo: ..."
        assert client.messages.create.call_count == 2

        # First call: just the initial user message
        assert snapshots[0]["roles"] == ["user"]
        # Second call: initial user + assistant tool_use response + user tool_result
        assert snapshots[1]["roles"] == ["user", "assistant", "user"]
        assert snapshots[1]["last_content_first_block_type"] == "tool_result"
        assert snapshots[1]["last_tool_use_id"] == "toolu_01"

    def test_executes_multiple_tool_calls_in_one_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sonnet 4.6 fires parallel tool calls in one response; the loop must
        execute all of them and bundle the results into a single user message."""

        def fake_a(**_: Any) -> dict[str, str]:
            return {"a": "result_a"}

        def fake_b(**_: Any) -> dict[str, str]:
            return {"b": "result_b"}

        monkeypatch.setattr("src.agent.FUNCTIONS", {"tool_a": fake_a, "tool_b": fake_b})

        # Build a tool_use response with TWO tool_use blocks in content. We assign
        # attributes after construction because MagicMock(name=...) sets the mock's
        # repr name, NOT the .name attribute the agent loop reads.
        block_a = MagicMock()
        block_a.type = "tool_use"
        block_a.name = "tool_a"
        block_a.id = "toolu_a"
        block_a.input = {}
        block_b = MagicMock()
        block_b.type = "tool_use"
        block_b.name = "tool_b"
        block_b.id = "toolu_b"
        block_b.input = {}
        msg_with_two_tools = MagicMock()
        msg_with_two_tools.stop_reason = "tool_use"
        msg_with_two_tools.content = [block_a, block_b]
        msg_with_two_tools.usage = _fake_usage()

        responses = [msg_with_two_tools, _fake_text_response("Done.")]
        snapshots: list[list[dict[str, Any]]] = []

        def side_effect(**kwargs: Any) -> MagicMock:
            # Snapshot the last user message's tool_result blocks at call time.
            last = kwargs["messages"][-1]
            snapshots.append(list(last["content"]) if isinstance(last["content"], list) else [])
            return responses.pop(0)

        client = MagicMock()
        client.messages.create.side_effect = side_effect

        result = run_agent(client, "Analyse")

        assert result.memo == "Done."
        # Second call's last user message should have BOTH tool_results bundled.
        ids = {block["tool_use_id"] for block in snapshots[1]}
        assert ids == {"toolu_a", "toolu_b"}

    def test_unexpected_stop_reason_raises(self) -> None:
        """If the model returns max_tokens (or anything other than tool_use /
        end_turn), surface it instead of looping silently."""
        client = MagicMock()
        client.messages.create.return_value = _fake_unexpected_stop_response()

        with pytest.raises(RuntimeError, match="Unexpected stop_reason"):
            run_agent(client, "Analyse")

    def test_max_iterations_exceeded_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If the model keeps requesting tool calls forever, bail out with a clear
        error rather than spending tokens indefinitely."""

        def fake_tool(**_: Any) -> dict[str, str]:
            return {"keep": "going"}

        monkeypatch.setattr("src.agent.FUNCTIONS", {"infinite": fake_tool})

        client = MagicMock()
        # Client always returns tool_use, never end_turn.
        client.messages.create.side_effect = lambda **_: _fake_tool_use_response("infinite", {})

        with pytest.raises(RuntimeError, match="Agent exceeded max_iterations=3"):
            run_agent(client, "Analyse", max_iterations=3)

        # Should have made exactly max_iterations calls before bailing.
        assert client.messages.create.call_count == 3

    def test_run_result_accumulates_metrics_across_iterations(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The RunResult must sum tokens / tool_calls / cost across all iterations,
        not just report the final one."""

        def fake_tool(**_: Any) -> dict[str, str]:
            return {"data": "x"}

        monkeypatch.setattr("src.agent.FUNCTIONS", {"t": fake_tool})

        # Build two responses with distinct token counts so we can verify summing.
        first = _fake_tool_use_response("t", {})
        first.usage.input_tokens = 100
        first.usage.output_tokens = 50
        # Two tool_use blocks in the first response → 2 tool calls.
        block_a = MagicMock(type="tool_use", name="t", id="a", input={})
        block_a.type = "tool_use"
        block_a.name = "t"
        block_a.id = "a"
        block_a.input = {}
        block_b = MagicMock()
        block_b.type = "tool_use"
        block_b.name = "t"
        block_b.id = "b"
        block_b.input = {}
        first.content = [block_a, block_b]

        second = _fake_text_response("done")
        second.usage.input_tokens = 200
        second.usage.output_tokens = 75

        client = MagicMock()
        client.messages.create.side_effect = [first, second]

        result = run_agent(client, "Analyse")

        assert result.iterations == 2
        assert result.tool_calls == 2  # only first iteration had tool_use blocks
        assert result.input_tokens == 300  # 100 + 200
        assert result.output_tokens == 125  # 50 + 75
        assert result.cost_usd > 0  # some real cost computed against Sonnet pricing
        assert result.elapsed_s >= 0

    def test_empty_text_block_returns_empty_string(self) -> None:
        """Defensive: end_turn with no text block should return empty string,
        not raise."""
        client = MagicMock()
        msg = MagicMock()
        msg.stop_reason = "end_turn"
        msg.content = []  # No text block — odd but possible
        msg.usage = _fake_usage()
        client.messages.create.return_value = msg

        result = run_agent(client, "Analyse")

        assert result.memo == ""


class TestBuildAnalysisRequest:
    def test_includes_the_url_and_warsaw_framing(self) -> None:
        """Both entry points (CLI, Streamlit) call this — the agent must get the
        URL plus the long-term-rental framing regardless of where it was invoked."""
        url = "https://www.otodom.pl/pl/oferta/test-ID01"
        msg = build_analysis_request(url)
        assert url in msg
        assert "Warsaw" in msg
        assert "rental" in msg.lower()


class TestStripMemoPreamble:
    def test_strips_text_before_the_marker(self) -> None:
        memo = "Done — writing the memo now.\n\n# Investment Memo: X\n\nBody."
        assert strip_memo_preamble(memo).startswith("# Investment Memo:")

    def test_passes_through_when_marker_is_absent(self) -> None:
        """No marker (shouldn't happen) — return unchanged so the operator sees
        whatever the model produced rather than an empty string."""
        memo = "Some unexpected output with no marker."
        assert strip_memo_preamble(memo) == memo

    def test_unchanged_when_already_starts_with_marker(self) -> None:
        memo = "# Investment Memo: Clean\n\nBody."
        assert strip_memo_preamble(memo) == memo


class TestConcurrentToolExecution:
    """The agent emits a batch of tool_use blocks in one response; run_agent
    must execute them concurrently (the tools are independent and I/O-bound)."""

    def test_batch_runs_concurrently_not_sequentially(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Three tools each wait on a shared 3-party barrier. They can only all
        clear it if executed concurrently — sequential execution would block the
        first tool until the barrier times out (surfacing as an error JSON in
        the tool result, which this test asserts does NOT happen)."""
        barrier = threading.Barrier(3, timeout=5)

        def _make_barrier_tool(label: str) -> Any:
            def tool(**_: Any) -> dict[str, str]:
                barrier.wait()  # returns only if all 3 tools run at once
                return {"label": label}

            return tool

        monkeypatch.setattr(
            "src.agent.FUNCTIONS",
            {
                "tool_a": _make_barrier_tool("a"),
                "tool_b": _make_barrier_tool("b"),
                "tool_c": _make_barrier_tool("c"),
            },
        )

        responses = [
            _fake_multi_tool_use_response(
                [("tool_a", "toolu_a"), ("tool_b", "toolu_b"), ("tool_c", "toolu_c")]
            ),
            _fake_text_response("Done."),
        ]
        snapshots: list[list[dict[str, Any]]] = []

        def side_effect(**kwargs: Any) -> MagicMock:
            last = kwargs["messages"][-1]
            snapshots.append(list(last["content"]) if isinstance(last["content"], list) else [])
            return responses.pop(0)

        client = MagicMock()
        client.messages.create.side_effect = side_effect

        result = run_agent(client, "Analyse")

        assert result.memo == "Done."
        # snapshots[1] is the bundled tool_result batch. If the barrier had
        # timed out (sequential execution), each result would be an error JSON.
        batch = snapshots[1]
        assert len(batch) == 3
        for block in batch:
            assert "error" not in block["content"]
            assert '"label"' in block["content"]

    def test_tool_results_preserve_block_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Even when a later tool finishes first, tool_results stay in the
        original tool_use block order — deterministic transcripts."""

        def slow_tool(**_: Any) -> dict[str, str]:
            time.sleep(0.1)
            return {"speed": "slow"}

        def fast_tool(**_: Any) -> dict[str, str]:
            return {"speed": "fast"}

        monkeypatch.setattr("src.agent.FUNCTIONS", {"slow_tool": slow_tool, "fast_tool": fast_tool})

        responses = [
            # slow block first, fast block second — fast will finish first.
            _fake_multi_tool_use_response(
                [("slow_tool", "toolu_slow"), ("fast_tool", "toolu_fast")]
            ),
            _fake_text_response("Done."),
        ]
        snapshots: list[list[dict[str, Any]]] = []

        def side_effect(**kwargs: Any) -> MagicMock:
            last = kwargs["messages"][-1]
            snapshots.append(list(last["content"]) if isinstance(last["content"], list) else [])
            return responses.pop(0)

        client = MagicMock()
        client.messages.create.side_effect = side_effect

        run_agent(client, "Analyse")

        assert [block["tool_use_id"] for block in snapshots[1]] == ["toolu_slow", "toolu_fast"]


class TestFormatToolNames:
    def test_single_tool_rendered_plain(self) -> None:
        assert _format_tool_names(["get_property_details"]) == "get_property_details"

    def test_repeated_tool_collapsed_with_count(self) -> None:
        """A rent + sale comparables batch calls one tool twice — show it once."""
        assert _format_tool_names(["a", "a", "b"]) == "a (x2), b"

    def test_first_occurrence_order_preserved(self) -> None:
        assert _format_tool_names(["b", "a", "b"]) == "b (x2), a"


class TestProgressCallback:
    """on_progress feeds the Streamlit live progress display."""

    def test_reports_thinking_per_model_call_and_tools_per_batch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_tool(**_: Any) -> dict[str, bool]:
            return {"ok": True}

        monkeypatch.setattr("src.agent.FUNCTIONS", {"get_property_details": fake_tool})
        responses = [
            _fake_tool_use_response("get_property_details", {"url": "x"}, "toolu_01"),
            _fake_text_response("# Investment Memo: X"),
        ]
        client = MagicMock()
        client.messages.create.side_effect = lambda **_: responses.pop(0)

        events: list[str] = []
        run_agent(client, "Analyse", on_progress=events.append)

        # Two model calls → two 'thinking' lines, numbered.
        thinking = [e for e in events if "thinking" in e.lower()]
        assert len(thinking) == 2
        assert "step 1" in thinking[0].lower()
        assert "step 2" in thinking[1].lower()
        # The feed names the agent (the product), not the underlying model.
        assert "agent" in thinking[0].lower()
        assert "claude" not in thinking[0].lower()
        # One tool batch → one 'Running:' line naming the tool.
        running = [e for e in events if e.startswith("Running:")]
        assert running == ["Running: get_property_details"]

    def test_running_line_collapses_repeated_tool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The rent + sale comparables batch (same tool twice) shows once."""

        def fake(**_: Any) -> dict[str, bool]:
            return {"ok": True}

        monkeypatch.setattr("src.agent.FUNCTIONS", {"find_comparable_properties": fake})
        responses = [
            _fake_multi_tool_use_response(
                [
                    ("find_comparable_properties", "toolu_a"),
                    ("find_comparable_properties", "toolu_b"),
                ]
            ),
            _fake_text_response("Done."),
        ]
        client = MagicMock()
        client.messages.create.side_effect = lambda **_: responses.pop(0)

        events: list[str] = []
        run_agent(client, "Analyse", on_progress=events.append)

        running = [e for e in events if e.startswith("Running:")]
        assert running == ["Running: find_comparable_properties (x2)"]
