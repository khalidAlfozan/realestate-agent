"""Tests for analyse_listing_photos.

We don't make real Anthropic API calls — the tool accepts an `client` kwarg
that tests use to inject a mock. Real end-to-end coverage of the vision
sub-call happens in the smoke-test (manual, in PR description), not in CI.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.models import _PhotoAnalysisLLM
from src.tools.analyse_listing_photos import (
    DEFAULT_MAX_PHOTOS,
    _build_user_content,
    analyse_listing_photos,
)


def _fake_client(parsed: _PhotoAnalysisLLM) -> MagicMock:
    """Build a MagicMock Anthropic client whose `.messages.parse()` returns `parsed`."""
    client = MagicMock()
    client.messages.parse.return_value = MagicMock(parsed_output=parsed)
    return client


def test_caps_photos_at_max() -> None:
    """If the listing has 18 photos and max_photos=6, only 6 should be sent."""
    parsed = _PhotoAnalysisLLM(
        overall_condition="good",
        confidence="medium",
        summary="Looks renovated.",
        observations=["new floors", "modern kitchen"],
        red_flags=[],
    )
    client = _fake_client(parsed)
    urls = [f"https://images.otodom.pl/{i}.jpg" for i in range(18)]

    result = analyse_listing_photos(
        image_urls=urls,
        property_context="seller claims renovated",
        max_photos=6,
        client=client,
    )

    assert result.photos_analysed == 6
    assert result.overall_condition == "good"
    # Inspect what got sent to the API
    _args, kwargs = client.messages.parse.call_args
    message = kwargs["messages"][0]
    image_blocks = [b for b in message["content"] if b.get("type") == "image"]
    assert len(image_blocks) == 6


def test_uses_default_max_when_unspecified() -> None:
    client = _fake_client(
        _PhotoAnalysisLLM(
            overall_condition="fair", confidence="low", summary="x", observations=[], red_flags=[]
        )
    )
    urls = [f"https://images.otodom.pl/{i}.jpg" for i in range(20)]

    result = analyse_listing_photos(image_urls=urls, client=client)

    assert result.photos_analysed == DEFAULT_MAX_PHOTOS


def test_passes_property_context_into_instruction() -> None:
    """The vision model needs the seller's claims to verify against."""
    client = _fake_client(
        _PhotoAnalysisLLM(
            overall_condition="excellent",
            confidence="high",
            summary="x",
            observations=[],
            red_flags=[],
        )
    )

    analyse_listing_photos(
        image_urls=["https://images.otodom.pl/a.jpg"],
        property_context="1959 brick block, ground floor, seller claims fully renovated",
        client=client,
    )

    _args, kwargs = client.messages.parse.call_args
    text_blocks = [b for b in kwargs["messages"][0]["content"] if b.get("type") == "text"]
    assert len(text_blocks) == 1
    assert "1959 brick block" in text_blocks[0]["text"]
    assert "fully renovated" in text_blocks[0]["text"]


def test_uses_haiku_model_with_structured_output() -> None:
    client = _fake_client(
        _PhotoAnalysisLLM(
            overall_condition="good",
            confidence="medium",
            summary="x",
            observations=[],
            red_flags=[],
        )
    )

    result = analyse_listing_photos(image_urls=["https://images.otodom.pl/a.jpg"], client=client)

    _args, kwargs = client.messages.parse.call_args
    assert kwargs["model"] == "claude-haiku-4-5"
    assert kwargs["output_format"] is _PhotoAnalysisLLM
    assert result.model_used == "claude-haiku-4-5"


def test_propagates_red_flags() -> None:
    """Red flags from the vision model must reach the tool output for the memo's §6."""
    parsed = _PhotoAnalysisLLM(
        overall_condition="fair",
        confidence="high",
        summary="Photos suggest the renovation is partial — floors are new but bathroom is dated.",
        observations=["new floor", "old bathroom tiles"],
        red_flags=[
            "Bathroom does not look renovated despite seller's claim",
            "Visible water stain on kitchen ceiling",
        ],
    )
    client = _fake_client(parsed)

    result = analyse_listing_photos(image_urls=["https://images.otodom.pl/a.jpg"], client=client)

    assert len(result.red_flags) == 2
    assert "bathroom" in result.red_flags[0].lower()


def test_raises_on_empty_url_list() -> None:
    with pytest.raises(ValueError, match="at least one image URL"):
        analyse_listing_photos(image_urls=[], client=_fake_client(MagicMock()))


def test_raises_on_unparsable_response() -> None:
    """If Haiku returns no parsed_output (refusal, max_tokens), fail loud."""
    client = MagicMock()
    client.messages.parse.return_value = MagicMock(parsed_output=None)

    with pytest.raises(RuntimeError, match="no parsed_output"):
        analyse_listing_photos(image_urls=["https://images.otodom.pl/a.jpg"], client=client)


def test_build_user_content_orders_images_before_instruction() -> None:
    """Photos must come first; the instruction comes after them so the model
    reads them in order, then sees the question."""
    content = _build_user_content(
        ["https://a.jpg", "https://b.jpg"], property_context="some context"
    )
    assert content[0]["type"] == "image"
    assert content[1]["type"] == "image"
    assert content[2]["type"] == "text"
    assert "some context" in content[2]["text"]
