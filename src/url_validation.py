"""URL validation for Otodom listings.

Structural-only — we check the URL *looks* like an Otodom listing path
without making any network call. The actual fetch happens later in
`get_property_details`; this guard exists to fail fast on obvious
typos / wrong sites before we spend any Anthropic tokens.

Kept in its own module (rather than inlined in cli.py) so it's easy to
test in isolation and easy to find when a future contributor needs to
extend the rules — e.g. supporting `/en/` paths or related portals.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Otodom listing paths look like:
#   /pl/oferta/<slug>-ID<alphanum>
# where <slug> is lowercase ASCII (Polish diacritics get stripped) and the
# trailing "-ID..." segment is the listing's stable identifier. Examples:
#   /pl/oferta/metro-4-pok-po-gen-remoncie-bliska-wola-centrum-ID4B8mI
#   /pl/oferta/dzien-otwarty-dla-rodziny-lub-inwestycja-ID4B4PJ
_LISTING_PATH_RE = re.compile(r"^/pl/oferta/[a-z0-9][a-z0-9\-]*-ID[A-Za-z0-9]+/?$")

# Both apex and www serve the same content; accept either.
_VALID_HOSTS = frozenset({"otodom.pl", "www.otodom.pl"})

_HELP_LINE = "Expected an Otodom listing URL like https://www.otodom.pl/pl/oferta/<slug>-ID<id>"


class InvalidOtodomURLError(ValueError):
    """Raised when a string doesn't structurally look like an Otodom listing URL.

    A subclass of ValueError so callers that catch ValueError still work; the
    distinct type lets the CLI handle this case specifically (e.g. exit 1
    with a helpful message vs propagating).
    """


def validate_otodom_listing_url(url: str) -> None:
    """Raise InvalidOtodomURLError if `url` doesn't structurally look like a listing.

    This is a fail-fast check — does NOT verify the listing exists. The actual
    HTTP fetch happens later. Validation here saves the cost of an Anthropic
    API call when the user pastes the wrong URL.
    """
    if not isinstance(url, str) or not url.strip():
        raise InvalidOtodomURLError(f"URL must be a non-empty string. {_HELP_LINE}")

    parsed = urlparse(url.strip())

    if parsed.scheme not in {"http", "https"}:
        raise InvalidOtodomURLError(
            f"URL scheme must be http(s); got {parsed.scheme!r}. {_HELP_LINE}"
        )

    if not parsed.hostname or parsed.hostname.lower() not in _VALID_HOSTS:
        raise InvalidOtodomURLError(
            f"URL host must be otodom.pl; got {parsed.hostname!r}. {_HELP_LINE}"
        )

    if not _LISTING_PATH_RE.match(parsed.path):
        raise InvalidOtodomURLError(
            f"URL path doesn't look like a listing; got {parsed.path!r}. {_HELP_LINE}"
        )
