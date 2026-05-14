"""Tool: analyse_listing_photos — Haiku 4.5 vision sub-call over the listing photos.

We use Haiku (not Sonnet) here because property-photo condition assessment
is the kind of cheap classification subtask Haiku is good at — it's ~3-5x
cheaper than Sonnet for vision and quality is sufficient.

The Anthropic client is constructed inside the tool when not passed in;
tests inject a mock client via the `client` kwarg.
"""

from __future__ import annotations

from typing import Any, cast

import anthropic
from anthropic.types import MessageParam, ToolParam

from src.config import require_anthropic_api_key
from src.models import PhotoAnalysis, _PhotoAnalysisLLM

# Haiku 4.5 is cheap, fast, and capable enough for vision-based condition
# classification. Sonnet would be overkill here.
MODEL_VISION = "claude-haiku-4-5"
MAX_TOKENS_VISION = 1024
DEFAULT_MAX_PHOTOS = 6

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
                    f"Default {DEFAULT_MAX_PHOTOS}. Higher costs more."
                ),
                "minimum": 1,
                "maximum": 20,
                "default": DEFAULT_MAX_PHOTOS,
            },
        },
        "required": ["image_urls"],
        "additionalProperties": False,
    },
}


def _build_user_content(image_urls: list[str], property_context: str) -> list[dict[str, Any]]:
    """Assemble the multimodal user message: photos first, then the instruction."""
    content: list[dict[str, Any]] = [
        {"type": "image", "source": {"type": "url", "url": url}} for url in image_urls
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
    max_photos: int = DEFAULT_MAX_PHOTOS,
    client: anthropic.Anthropic | None = None,
) -> PhotoAnalysis:
    if not image_urls:
        raise ValueError("analyse_listing_photos requires at least one image URL")

    selected = image_urls[:max_photos]
    api_client = client or anthropic.Anthropic(api_key=require_anthropic_api_key())

    messages = [{"role": "user", "content": _build_user_content(selected, property_context)}]
    response = api_client.messages.parse(
        model=MODEL_VISION,
        max_tokens=MAX_TOKENS_VISION,
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
        photos_analysed=len(selected),
        model_used=MODEL_VISION,
    )
