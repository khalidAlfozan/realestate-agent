"""Streamlit entry point for the realestate-agent.

A thin UI layer over the same pipeline the CLI drives: gate on a shared
password, validate the URL, run the agent, render the memo. All real logic
lives in `src/` and is tested there — this module is glue.

Run locally:
    uv run streamlit run app.py
"""

from __future__ import annotations

import hmac
import os

import anthropic
import streamlit as st

from src.agent import build_analysis_request, run_agent, strip_memo_preamble
from src.config import require_anthropic_api_key
from src.url_validation import InvalidOtodomURLError, validate_otodom_listing_url

# Cap on agent runs per browser session — bounds Anthropic spend if the
# (password-gated) link gets shared around. A page refresh starts a fresh
# session, so this is a spend guardrail, not a hard wall; the password is the
# real access control.
_MAX_RUNS_PER_SESSION = 5


def _load_secrets_into_env() -> None:
    """Copy Streamlit Cloud secrets into os.environ.

    The src/ code reads keys from the environment (via .env locally). On
    Streamlit Community Cloud there is no .env — secrets arrive via st.secrets
    — so bridging them across keeps the Streamlit-agnostic code unchanged.
    """
    try:
        secrets = dict(st.secrets)
    except Exception:
        return  # no secrets store — local dev uses .env, nothing to bridge
    for key in ("ANTHROPIC_API_KEY", "GUS_BDL_API_KEY", "APP_PASSWORD"):
        if key not in os.environ and key in secrets:
            os.environ[key] = str(secrets[key])


def _password_gate() -> None:
    """Halt the script unless the visitor has entered the shared password.

    Open when no APP_PASSWORD is set (local dev). When it is set — i.e. the
    public deployment — this is the real access control; the per-session run
    cap is only a spend guardrail layered on top. `compare_digest` keeps the
    check constant-time.
    """
    expected = os.environ.get("APP_PASSWORD", "")
    if not expected or st.session_state.get("authenticated"):
        return
    st.caption("Private demo — enter the password to continue.")
    entered = st.text_input("Password", type="password")
    if entered and hmac.compare_digest(entered, expected):
        st.session_state["authenticated"] = True
        st.rerun()
    if entered:
        st.error("Incorrect password.")
    st.stop()


st.set_page_config(page_title="Warsaw Rental Investment Analyst", layout="centered")
_load_secrets_into_env()

st.title("Warsaw Rental Investment Analyst")
_password_gate()

st.caption(
    "Paste an Otodom listing URL. An AI agent fetches the "
    "listing, pulls rent/sale comparables, district market stats, GUS "
    "demographics and nearby amenities, reviews the photos, and writes a "
    "structured long-term-rental investment memo."
)
st.caption("Powered by Claude Sonnet 4.6.")

url = st.text_input(
    "Otodom listing URL",
    placeholder="https://www.otodom.pl/pl/oferta/...",
)
run_clicked = st.button("Analyse", type="primary")
st.caption(
    f"Analyses this session: {st.session_state.get('run_count', 0)} / {_MAX_RUNS_PER_SESSION}"
)

if run_clicked:
    # Per-session spend guardrail — checked first, so a capped session can't
    # even reach the agent.
    if st.session_state.get("run_count", 0) >= _MAX_RUNS_PER_SESSION:
        st.warning(
            f"Session limit reached — {_MAX_RUNS_PER_SESSION} analyses per "
            "session. Refresh the page to start a new session."
        )
        st.stop()

    # Fail fast on a bad URL before constructing the client or spending tokens.
    try:
        validate_otodom_listing_url(url)
    except InvalidOtodomURLError as exc:
        st.error(str(exc))
        st.stop()

    try:
        client = anthropic.Anthropic(api_key=require_anthropic_api_key())
    except RuntimeError as exc:
        st.error(str(exc))
        st.stop()

    # This run is about to spend tokens — count it against the cap now, so a
    # run that errors partway still consumes its slot.
    st.session_state["run_count"] = st.session_state.get("run_count", 0) + 1

    # A live feed of the agent's steps — a multi-minute run should never be a
    # blank spinner. run_agent calls on_progress on this (the script) thread,
    # so writing into the status container from the callback is safe.
    with st.status("Analysing the listing...", expanded=True) as status:

        def _report(message: str) -> None:
            status.write(message)

        status.write("This typically takes 3-4 minutes — progress below.")
        try:
            result = run_agent(client, build_analysis_request(url), on_progress=_report)
        except Exception as exc:
            # A UI boundary must never surface a raw traceback to the user.
            status.update(label="Analysis failed", state="error")
            st.error(f"The analysis failed — {type(exc).__name__}: {exc}")
            st.stop()
        status.update(label="Analysis complete", state="complete", expanded=False)

    # Persist across re-runs (e.g. when the download button re-runs the script),
    # so the agent is never accidentally re-invoked for the same click.
    st.session_state["memo"] = strip_memo_preamble(result.memo)
    st.session_state["result"] = result
    st.session_state["analysed_url"] = url

if "result" in st.session_state:
    result = st.session_state["result"]
    memo = st.session_state["memo"]

    st.divider()
    st.caption(f"Analysed: {st.session_state['analysed_url']}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Cost", f"${result.cost_usd:.4f}")
    c2.metric("Iterations", result.iterations)
    c3.metric("Tool calls", result.tool_calls)
    c4.metric("Elapsed", f"{result.elapsed_s:.0f}s")

    with st.expander("Token usage"):
        st.markdown(
            f"- Input: **{result.input_tokens:,}**\n"
            f"- Output: **{result.output_tokens:,}**\n"
            f"- Cache read: **{result.cache_read_tokens:,}**\n"
            f"- Cache write: **{result.cache_write_tokens:,}**"
        )

    st.divider()
    st.markdown(memo)
    st.download_button(
        "Download memo (Markdown)",
        memo,
        file_name="investment-memo.md",
        mime="text/markdown",
    )
