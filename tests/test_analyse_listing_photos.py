"""Tests for analyse_listing_photos.

Two layers of mocking:
- `pytest-httpx` mocks the image-download fetches we now do ourselves
  (the tool no longer asks Anthropic to fetch URLs server-side).
- `MagicMock` injected via the `client=` kwarg replaces the Anthropic
  client so we never make real API calls in CI.

Real end-to-end coverage of the vision sub-call happens in the
smoke-test (manual, in PR description), not in CI.
"""

from __future__ import annotations

import base64
from unittest.mock import MagicMock

import httpx
import pytest
from pytest_httpx import HTTPXMock

from src.config import settings
from src.models import _PhotoAnalysisLLM
from src.tools.analyse_listing_photos import (
    _build_user_content,
    analyse_listing_photos,
)

# Tiny valid JPEG byte sequence — magic bytes + minimal SOI/EOI markers.
# Anthropic doesn't actually decode it (we mock the client), but the
# tool's media-type check requires content-type=image/jpeg.
_FAKE_JPEG = b"\xff\xd8\xff" + b"\x00" * 10 + b"\xff\xd9"


def _fake_client(parsed: _PhotoAnalysisLLM) -> MagicMock:
    """Build a MagicMock Anthropic client whose `.messages.parse()` returns `parsed`."""
    client = MagicMock()
    client.messages.parse.return_value = MagicMock(parsed_output=parsed)
    return client


def _ok_parsed() -> _PhotoAnalysisLLM:
    """Default LLM output for tests that don't care what comes back."""
    return _PhotoAnalysisLLM(
        overall_condition="good",
        confidence="medium",
        summary="x",
        observations=[],
        red_flags=[],
    )


def _mock_image_ok(httpx_mock: HTTPXMock) -> None:
    """Register a reusable mock that returns a valid JPEG for any image URL."""
    httpx_mock.add_response(
        content=_FAKE_JPEG,
        headers={"content-type": "image/jpeg"},
        is_reusable=True,
    )


def test_caps_photos_at_max(httpx_mock: HTTPXMock) -> None:
    """If the listing has 18 photos and max_photos=6, only 6 should be sent."""
    _mock_image_ok(httpx_mock)
    parsed = _PhotoAnalysisLLM(
        overall_condition="good",
        confidence="medium",
        summary="Looks renovated.",
        observations=["new floors", "modern kitchen"],
        red_flags=[],
    )
    client = _fake_client(parsed)
    urls = [f"https://images.example.com/{i}.jpg" for i in range(18)]

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
    # Should now be inline base64, not URLs
    for block in image_blocks:
        assert block["source"]["type"] == "base64"
        assert block["source"]["media_type"] == "image/jpeg"


def test_uses_default_max_when_unspecified(httpx_mock: HTTPXMock) -> None:
    _mock_image_ok(httpx_mock)
    client = _fake_client(_ok_parsed())
    urls = [f"https://images.example.com/{i}.jpg" for i in range(20)]

    result = analyse_listing_photos(image_urls=urls, client=client)

    assert result.photos_analysed == settings.vision.default_max_photos


def test_passes_property_context_into_instruction(httpx_mock: HTTPXMock) -> None:
    """The vision model needs the seller's claims to verify against."""
    _mock_image_ok(httpx_mock)
    client = _fake_client(_ok_parsed())

    analyse_listing_photos(
        image_urls=["https://images.example.com/a.jpg"],
        property_context="1959 brick block, ground floor, seller claims fully renovated",
        client=client,
    )

    _args, kwargs = client.messages.parse.call_args
    text_blocks = [b for b in kwargs["messages"][0]["content"] if b.get("type") == "text"]
    assert len(text_blocks) == 1
    assert "1959 brick block" in text_blocks[0]["text"]
    assert "fully renovated" in text_blocks[0]["text"]


def test_uses_haiku_model_with_structured_output(httpx_mock: HTTPXMock) -> None:
    _mock_image_ok(httpx_mock)
    client = _fake_client(_ok_parsed())

    result = analyse_listing_photos(image_urls=["https://images.example.com/a.jpg"], client=client)

    _args, kwargs = client.messages.parse.call_args
    assert kwargs["model"] == "claude-haiku-4-5"
    assert kwargs["output_format"] is _PhotoAnalysisLLM
    assert result.model_used == "claude-haiku-4-5"


def test_image_data_is_base64_encoded_in_message(httpx_mock: HTTPXMock) -> None:
    """The bytes we downloaded must be base64-encoded into the message —
    if we sent URLs Anthropic would re-fetch and the CDN would block."""
    _mock_image_ok(httpx_mock)
    client = _fake_client(_ok_parsed())

    analyse_listing_photos(image_urls=["https://images.example.com/a.jpg"], client=client)

    _args, kwargs = client.messages.parse.call_args
    image_block = kwargs["messages"][0]["content"][0]
    expected_b64 = base64.standard_b64encode(_FAKE_JPEG).decode("ascii")
    assert image_block["source"]["data"] == expected_b64


def test_propagates_red_flags(httpx_mock: HTTPXMock) -> None:
    """Red flags from the vision model must reach the tool output for the memo's §6."""
    _mock_image_ok(httpx_mock)
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

    result = analyse_listing_photos(image_urls=["https://images.example.com/a.jpg"], client=client)

    assert len(result.red_flags) == 2
    assert "bathroom" in result.red_flags[0].lower()


def test_raises_on_empty_url_list() -> None:
    """No httpx_mock needed — short-circuits before any fetch."""
    with pytest.raises(ValueError, match="at least one image URL"):
        analyse_listing_photos(image_urls=[], client=_fake_client(_ok_parsed()))


def test_skips_failed_image_fetches_continues_with_rest(httpx_mock: HTTPXMock) -> None:
    """One bad URL shouldn't sink the whole analysis."""
    httpx_mock.add_response(
        url="https://images.example.com/good1.jpg",
        content=_FAKE_JPEG,
        headers={"content-type": "image/jpeg"},
    )
    httpx_mock.add_response(
        url="https://images.example.com/bad.jpg",
        status_code=403,
    )
    httpx_mock.add_response(
        url="https://images.example.com/good2.jpg",
        content=_FAKE_JPEG,
        headers={"content-type": "image/jpeg"},
    )
    client = _fake_client(_ok_parsed())

    result = analyse_listing_photos(
        image_urls=[
            "https://images.example.com/good1.jpg",
            "https://images.example.com/bad.jpg",
            "https://images.example.com/good2.jpg",
        ],
        client=client,
    )

    assert result.photos_analysed == 2  # the bad one was skipped


def test_raises_when_all_image_fetches_fail(httpx_mock: HTTPXMock) -> None:
    """If we can't download any photos, fail loud — don't make a useless API call."""
    httpx_mock.add_response(status_code=403, is_reusable=True)
    client = _fake_client(_ok_parsed())

    with pytest.raises(RuntimeError, match=r"Could not fetch any of the .* image URLs"):
        analyse_listing_photos(
            image_urls=[
                "https://images.example.com/a.jpg",
                "https://images.example.com/b.jpg",
            ],
            client=client,
        )
    # Confirm we never bothered the Anthropic API
    client.messages.parse.assert_not_called()


def test_skips_unsupported_media_types(httpx_mock: HTTPXMock) -> None:
    """Anthropic only accepts jpeg/png/gif/webp — anything else gets dropped."""
    httpx_mock.add_response(
        url="https://images.example.com/svg.svg",
        content=b"<svg></svg>",
        headers={"content-type": "image/svg+xml"},
    )
    httpx_mock.add_response(
        url="https://images.example.com/jpg.jpg",
        content=_FAKE_JPEG,
        headers={"content-type": "image/jpeg"},
    )
    client = _fake_client(_ok_parsed())

    result = analyse_listing_photos(
        image_urls=[
            "https://images.example.com/svg.svg",
            "https://images.example.com/jpg.jpg",
        ],
        client=client,
    )

    assert result.photos_analysed == 1


def test_handles_image_fetch_timeout(httpx_mock: HTTPXMock) -> None:
    """Network timeouts shouldn't crash the tool; they get logged + skipped."""
    httpx_mock.add_exception(
        httpx.TimeoutException("timeout"),
        url="https://images.example.com/slow.jpg",
    )
    httpx_mock.add_response(
        url="https://images.example.com/fast.jpg",
        content=_FAKE_JPEG,
        headers={"content-type": "image/jpeg"},
    )
    client = _fake_client(_ok_parsed())

    result = analyse_listing_photos(
        image_urls=[
            "https://images.example.com/slow.jpg",
            "https://images.example.com/fast.jpg",
        ],
        client=client,
    )

    assert result.photos_analysed == 1


def test_raises_on_unparsable_response(httpx_mock: HTTPXMock) -> None:
    """If Haiku returns no parsed_output (refusal, max_tokens), fail loud."""
    _mock_image_ok(httpx_mock)
    client = MagicMock()
    client.messages.parse.return_value = MagicMock(parsed_output=None)

    with pytest.raises(RuntimeError, match="no parsed_output"):
        analyse_listing_photos(image_urls=["https://images.example.com/a.jpg"], client=client)


def test_build_user_content_orders_images_before_instruction() -> None:
    """Photos must come first; the instruction comes after them so the model
    reads them in order, then sees the question."""
    images = [("image/jpeg", b"\xff\xd8\xffaaa"), ("image/png", b"\x89PNGbbb")]
    content = _build_user_content(images, property_context="some context")

    assert content[0]["type"] == "image"
    assert content[0]["source"]["type"] == "base64"
    assert content[0]["source"]["media_type"] == "image/jpeg"
    assert content[1]["type"] == "image"
    assert content[1]["source"]["media_type"] == "image/png"
    assert content[2]["type"] == "text"
    assert "some context" in content[2]["text"]
