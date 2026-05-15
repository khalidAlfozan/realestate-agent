"""Tests for the CLI entry point.

The Anthropic client and run_agent are mocked — no API calls in CI.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src import cli

# A structurally-valid Otodom listing URL — used across tests so they
# pass the cli's URL validation guard. Doesn't have to point at a real
# listing because run_agent is mocked.
_VALID_URL = "https://www.otodom.pl/pl/oferta/test-listing-ID01"


def test_no_args_prints_usage_and_exits_nonzero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.main([])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "usage:" in captured.err.lower()


def test_invalid_url_exits_without_calling_run_agent(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point of the validation guard: bad URLs must NOT reach
    run_agent (and therefore must NOT cost any Anthropic tokens)."""
    run_agent_mock = MagicMock()
    monkeypatch.setattr(cli, "run_agent", run_agent_mock)
    monkeypatch.setattr(cli, "require_anthropic_api_key", lambda: "sk-ant-fake")

    exit_code = cli.main(["https://www.marca.com"])

    assert exit_code == 1
    run_agent_mock.assert_not_called()
    err = capsys.readouterr().err
    assert "error:" in err.lower()
    assert "host" in err.lower()


def test_passes_url_to_run_agent_and_prints_returned_memo(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "require_anthropic_api_key", lambda: "sk-ant-fake")

    fake_client = MagicMock()
    monkeypatch.setattr(cli.anthropic, "Anthropic", lambda api_key: fake_client)

    captured_args: dict[str, Any] = {}

    def fake_run_agent(client: Any, user_message: str) -> str:
        captured_args["client"] = client
        captured_args["user_message"] = user_message
        return "# Investment Memo: Test"

    monkeypatch.setattr(cli, "run_agent", fake_run_agent)

    exit_code = cli.main([_VALID_URL])

    assert exit_code == 0
    assert captured_args["client"] is fake_client
    # The CLI wraps the URL in an instruction; verify the URL got through.
    assert _VALID_URL in captured_args["user_message"]
    assert "Warsaw" in captured_args["user_message"]

    captured = capsys.readouterr()
    assert "# Investment Memo: Test" in captured.out


def test_strips_preamble_before_memo_marker(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Belt-and-suspenders: even if the model prepends a transition line,
    the CLI strips everything before '# Investment Memo:'."""
    monkeypatch.setattr(cli, "require_anthropic_api_key", lambda: "sk-ant-fake")
    monkeypatch.setattr(cli.anthropic, "Anthropic", lambda api_key: MagicMock())
    monkeypatch.setattr(
        cli,
        "run_agent",
        lambda client, msg: (
            "All four tools have returned. Writing the memo now.\n\n"
            "---\n\n"
            "# Investment Memo: Wola Listing\n\nBody continues here."
        ),
    )

    exit_code = cli.main([_VALID_URL])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert out.startswith("# Investment Memo:")
    assert "All four tools have returned" not in out
    assert "Body continues here" in out


def test_memo_without_marker_passes_through_unchanged(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the model doesn't produce the marker (shouldn't happen, but defensive),
    don't strip anything — print the raw output so the operator can see what
    went wrong."""
    monkeypatch.setattr(cli, "require_anthropic_api_key", lambda: "sk-ant-fake")
    monkeypatch.setattr(cli.anthropic, "Anthropic", lambda api_key: MagicMock())
    monkeypatch.setattr(cli, "run_agent", lambda client, msg: "Some unexpected output")

    exit_code = cli.main([_VALID_URL])

    assert exit_code == 0
    assert "Some unexpected output" in capsys.readouterr().out


def test_memo_starting_with_marker_is_unchanged(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The happy path: memo starts with the marker; CLI passes it through verbatim."""
    monkeypatch.setattr(cli, "require_anthropic_api_key", lambda: "sk-ant-fake")
    monkeypatch.setattr(cli.anthropic, "Anthropic", lambda api_key: MagicMock())
    memo = "# Investment Memo: Clean Output\n\nBody here."
    monkeypatch.setattr(cli, "run_agent", lambda client, msg: memo)

    exit_code = cli.main([_VALID_URL])

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == memo.strip()
