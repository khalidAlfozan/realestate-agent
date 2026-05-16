"""Tests for the Streamlit entry point (app.py).

Uses Streamlit's official AppTest harness — runs the script in-process and
inspects the rendered element tree. We cover the boot path, the URL-validation
guard, and the password gate; none needs an API key or touches the agent (each
guard stops before the client is built). The happy path is covered indirectly:
app.py is thin glue over run_agent / strip_memo_preamble, both tested in
test_agent.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

_APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture(autouse=True)
def _clear_app_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run every test with a known APP_PASSWORD state — unset, so the gate is
    open — regardless of the developer's local .env. Gate tests re-set it."""
    monkeypatch.delenv("APP_PASSWORD", raising=False)


def test_app_boots_without_error() -> None:
    at = AppTest.from_file(_APP_PATH).run()
    assert not at.exception
    assert at.title[0].value == "Warsaw Rental Investment Analyst"


def test_invalid_url_host_shows_error_and_no_results() -> None:
    """A non-Otodom URL must surface a validation error and never render a memo —
    the guard exists so a bad paste costs zero Anthropic tokens."""
    at = AppTest.from_file(_APP_PATH).run()
    at.text_input[0].set_value("https://www.marca.com")
    at.button[0].click()
    at.run()

    assert at.error
    assert "host" in at.error[0].value.lower()
    # st.stop() fired before the results block — no memo rendered.
    assert not at.exception


def test_empty_url_shows_error() -> None:
    """Clicking Analyse with an empty field is caught by the same guard."""
    at = AppTest.from_file(_APP_PATH).run()
    at.button[0].click()
    at.run()

    assert at.error
    assert "non-empty" in at.error[0].value.lower()


def test_malformed_otodom_path_shows_error() -> None:
    """Right host, wrong path shape (not a /pl/oferta/...-ID... listing)."""
    at = AppTest.from_file(_APP_PATH).run()
    at.text_input[0].set_value("https://www.otodom.pl/pl/wyniki/wynajem")
    at.button[0].click()
    at.run()

    assert at.error
    assert "listing" in at.error[0].value.lower()


def test_password_gate_blocks_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """With APP_PASSWORD set, an unauthenticated visitor sees only a password
    prompt — st.stop() fires before the Analyse button is ever rendered."""
    monkeypatch.setenv("APP_PASSWORD", "letmein")
    at = AppTest.from_file(_APP_PATH).run()

    assert not at.exception
    assert at.text_input  # the password field
    assert len(at.button) == 0  # gated — the Analyse button is unreachable


def test_password_gate_opens_once_authenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    """A session flagged authenticated passes the gate and reaches the app."""
    monkeypatch.setenv("APP_PASSWORD", "letmein")
    at = AppTest.from_file(_APP_PATH).run()  # first run: gated
    at.session_state["authenticated"] = True
    at.run()  # second run: gate open

    assert not at.exception
    assert len(at.button) == 1  # the Analyse button is now reachable


def test_password_gate_rejects_wrong_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PASSWORD", "letmein")
    at = AppTest.from_file(_APP_PATH).run()
    at.text_input[0].set_value("not-the-password")
    at.run()

    assert at.error
    assert "incorrect" in at.error[0].value.lower()
