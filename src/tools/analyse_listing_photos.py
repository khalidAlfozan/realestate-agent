"""Tool: analyse_listing_photos — Haiku 4.5 vision sub-call over the listing photos.

We use Haiku (not Sonnet) here because property-photo condition assessment
is the kind of cheap classification subtask Haiku is good at — it's ~3-5x
cheaper than Sonnet for vision and quality is sufficient.

Photos are downloaded with our own httpx and sent to the API as base64,
NOT as URLs for the API to fetch. The Otodom CDN
(`ireland.apollo.olxcdn.com`) returns 200 to our requests but blocks /
challenges Anthropic's server-side image fetcher, so URL-mode
consistently fails with `invalid_request_error`. Downloading locally
sidesteps the entire class of "Anthropic can't reach this image" issues.

The Anthropic client is constructed inside the tool when not passed in;
tests inject mock clients via the `client` kwarg and mock httpx via
pytest-httpx.
"""

from __future__ import annotations

import base64
import logging
from typing import Any, cast

import anthropic
import httpx
from anthropic.types import MessageParam, ToolParam

from src.config import require_anthropic_api_key, settings
from src.models import PhotoAnalysis, _PhotoAnalysisLLM

# Anthropic accepts these image media types for vision input.
_ALLOWED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

log = logging.getLogger(__name__)

SCHEMA: ToolParam = {
    "name": "analyse_listing_photos",
    "description": (
        "Inspect listing photos with vision (Claude Haiku 4.5) and return a "
        "structured condition assessment: overall condition (excellent / good "
        "/ fair / poor / unclear), confidence, summary, observations, and red "
        "flags. Use this AFTER get_property_details and find_comparable_properties "
        "but BEFORE writing the memo's section 3. Photos verify or contradict "
        "the seller's claims about renovation and condition."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "image_urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "List of image URLs (typically PropertyDetails.image_urls). "
                    "Only the first `max_photos` will be analysed to bound cost."
                ),
                "minItems": 1,
            },
            "property_context": {
                "type": "string",
                "description": (
                    "Short context about the property to help the vision model "
                    "judge claims in context — e.g. 'seller claims fully "
                    "renovated, 1959 brick block, ground floor, 73 m²'."
                ),
                "default": "",
            },
            "max_photos": {
                "type": "integer",
                "description": (
                    "Cap on how many photos to send to the vision model. "
                    f"Default {settings.vision.default_max_photos}. Higher costs more."
                ),
                "minimum": 1,
                "maximum": 20,
                "default": settings.vision.default_max_photos,
            },
        },
        "required": ["image_urls"],
        "additionalProperties": False,
    },
}


def _fetch_image(url: str) -> tuple[str, bytes] | None:
    """Download one image. Returns (media_type, bytes) on success, None on failure.

    Per-image errors are swallowed with a warning so a single bad URL doesn't
    sink the whole analysis — the caller decides what to do if all fetches fail.
    """
    try:
        response = httpx.get(
            url,
            headers={"User-Agent": settings.scraping.user_agent, "Accept": "image/*"},
            follow_redirects=True,
            timeout=settings.vision.fetch_timeout_s,
        )
        response.raise_for_status()
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        log.warning("Image fetch failed for %s: %s", url, exc)
        return None

    media_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
    if media_type not in _ALLOWED_MEDIA_TYPES:
        log.warning("Unsupported media type %r for %s — skipping", media_type, url)
        return None

    return media_type, response.content


def _build_user_content(
    images: list[tuple[str, bytes]], property_context: str
) -> list[dict[str, Any]]:
    """Assemble the multimodal user message: photos first, then the instruction.

    `images` is a list of (media_type, raw_bytes) tuples — already-downloaded
    image data that we'll base64-encode and send inline (vs. asking Anthropic
    to fetch URLs server-side).
    """
    content: list[dict[str, Any]] = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.standard_b64encode(data).decode("ascii"),
            },
        }
        for media_type, data in images
    ]
    instruction = (
        "You are inspecting listing photos for a Warsaw apartment investment. "
        "Judge what you can actually see — finish quality, age, signs of "
        "renovation or neglect, kitchen/bathroom state, daylight, layout cues. "
        "Be conservative: when uncertain, say 'unclear'.\n\n"
        f"Context (from the seller / listing): {property_context or '(none provided)'}\n\n"
        "Compare what you observe against any seller claims in the context. "
        "Note discrepancies as red flags. Do NOT hallucinate features not visible."
    )
    content.append({"type": "text", "text": instruction})
    return content


def analyse_listing_photos(
    image_urls: list[str],
    property_context: str = "",
    max_photos: int | None = None,
    client: anthropic.Anthropic | None = None,
) -> PhotoAnalysis:
    if max_photos is None:
        max_photos = settings.vision.default_max_photos
    if not image_urls:
        raise ValueError("analyse_listing_photos requires at least one image URL")

    selected_urls = image_urls[:max_photos]
    fetched: list[tuple[str, bytes]] = []
    for url in selected_urls:
        result = _fetch_image(url)
        if result is not None:
            fetched.append(result)

    if not fetched:
        raise RuntimeError(
            f"Could not fetch any of the {len(selected_urls)} image URLs supplied — "
            "check the URLs are reachable and return a supported media type "
            "(jpeg/png/gif/webp)."
        )

    api_client = client or anthropic.Anthropic(api_key=require_anthropic_api_key())

    messages = [{"role": "user", "content": _build_user_content(fetched, property_context)}]
    response = api_client.messages.parse(
        model=settings.vision.model,
        max_tokens=settings.vision.max_tokens,
        messages=cast(list[MessageParam], messages),
        output_format=_PhotoAnalysisLLM,
    )

    parsed = response.parsed_output
    if parsed is None:
        raise RuntimeError(
            "Haiku vision call returned no parsed_output — model may have refused "
            "or hit max_tokens before completing the structured response."
        )

    return PhotoAnalysis(
        overall_condition=parsed.overall_condition,
        confidence=parsed.confidence,
        summary=parsed.summary,
        observations=parsed.observations,
        red_flags=parsed.red_flags,
        photos_analysed=len(fetched),
        model_used=settings.vision.model,
    )
