"""Tests for the Streamlit entry point (app.py).

Uses Streamlit's official AppTest harness — runs the script in-process and
inspects the rendered element tree. We cover the boot path and the URL-
validation guard; neither needs an API key or touches the agent (validation
fails fast, before the client is built). The happy path is covered indirectly:
app.py is thin glue over run_agent / strip_memo_preamble, both tested in
test_agent.py.
"""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

_APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")


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
