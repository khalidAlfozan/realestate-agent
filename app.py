"""Streamlit entry point for the realestate-agent.

A thin UI layer over the same pipeline the CLI drives: validate the URL,
run the agent, strip any preamble, render the memo. All real logic lives
in `src/` and is tested there — this module is glue.

Run locally:
    uv run streamlit run app.py
"""

from __future__ import annotations

import anthropic
import streamlit as st

from src.agent import build_analysis_request, run_agent, strip_memo_preamble
from src.config import require_anthropic_api_key
from src.url_validation import InvalidOtodomURLError, validate_otodom_listing_url

st.set_page_config(page_title="Warsaw Rental Investment Analyst", layout="centered")

st.title("Warsaw Rental Investment Analyst")
st.caption(
    "Paste an Otodom listing URL. An AI agent (Claude + 7 tools) fetches the "
    "listing, pulls rent/sale comparables, district market stats, GUS "
    "demographics and nearby amenities, reviews the photos, and writes a "
    "structured long-term-rental investment memo."
)

url = st.text_input(
    "Otodom listing URL",
    placeholder="https://www.otodom.pl/pl/oferta/...",
)
run_clicked = st.button("Analyse", type="primary")

if run_clicked:
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

    with st.spinner("Analysing — the agent runs ~7 tools, this usually takes 30-60s..."):
        try:
            result = run_agent(client, build_analysis_request(url))
        except Exception as exc:
            # A UI boundary must never surface a raw traceback to the user.
            st.error(f"The analysis failed — {type(exc).__name__}: {exc}")
            st.stop()

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
