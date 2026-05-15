"""Tests for src.url_validation."""

from __future__ import annotations

import pytest

from src.url_validation import InvalidOtodomURLError, validate_otodom_listing_url


class TestValidUrls:
    """Real URLs we've used end-to-end during development should all pass."""

    @pytest.mark.parametrize(
        "url",
        [
            # Wola — the listing we've iterated on throughout development
            "https://www.otodom.pl/pl/oferta/metro-4-pok-po-gen-remoncie-bliska-wola-centrum-ID4B8mI",
            # Wesoła / Stara Miłosna — the outer-Warsaw listing that surfaced the district bug
            "https://www.otodom.pl/pl/oferta/dzien-otwarty-dla-rodziny-lub-inwestycja-ID4B4PJ",
            # Other listings the user ran during development
            "https://www.otodom.pl/pl/oferta/super-lokalizacja-piekny-widok-4pok-101-2m2-ID4ATVZ",
            "https://www.otodom.pl/pl/oferta/okazyjna-cena-panoramiczny-apartament-dla-rodziny-lub-pod-kancelarie-ID4BfgR",
        ],
    )
    def test_real_otodom_listings_pass(self, url: str) -> None:
        # Should not raise.
        validate_otodom_listing_url(url)

    def test_apex_domain_without_www_passes(self) -> None:
        validate_otodom_listing_url("https://otodom.pl/pl/oferta/some-flat-ID12345")

    def test_query_string_does_not_break_validation(self) -> None:
        validate_otodom_listing_url(
            "https://www.otodom.pl/pl/oferta/some-flat-ID12345?utm_source=email"
        )

    def test_trailing_slash_accepted(self) -> None:
        validate_otodom_listing_url("https://www.otodom.pl/pl/oferta/some-flat-ID12345/")

    def test_url_with_leading_trailing_whitespace_accepted(self) -> None:
        """Pasted URLs sometimes carry whitespace from the clipboard."""
        validate_otodom_listing_url("  https://www.otodom.pl/pl/oferta/some-flat-ID12345  ")


class TestInvalidUrls:
    def test_empty_string_rejected(self) -> None:
        with pytest.raises(InvalidOtodomURLError, match="non-empty"):
            validate_otodom_listing_url("")

    def test_whitespace_only_rejected(self) -> None:
        with pytest.raises(InvalidOtodomURLError, match="non-empty"):
            validate_otodom_listing_url("   ")

    def test_non_string_input_rejected(self) -> None:
        with pytest.raises(InvalidOtodomURLError, match="non-empty"):
            validate_otodom_listing_url(None)  # type: ignore[arg-type]

    def test_wrong_scheme_rejected(self) -> None:
        with pytest.raises(InvalidOtodomURLError, match="scheme"):
            validate_otodom_listing_url("ftp://www.otodom.pl/pl/oferta/foo-ID1")

    def test_no_scheme_rejected(self) -> None:
        with pytest.raises(InvalidOtodomURLError, match="scheme"):
            validate_otodom_listing_url("www.otodom.pl/pl/oferta/foo-ID1")

    def test_wrong_host_rejected(self) -> None:
        """The case the user actually hit — pasting a different site."""
        with pytest.raises(InvalidOtodomURLError, match="host"):
            validate_otodom_listing_url("https://www.marca.com")

    def test_competitor_site_rejected(self) -> None:
        with pytest.raises(InvalidOtodomURLError, match="host"):
            validate_otodom_listing_url("https://www.idealista.com/inmueble/107003496/")

    def test_otodom_homepage_rejected(self) -> None:
        with pytest.raises(InvalidOtodomURLError, match="path"):
            validate_otodom_listing_url("https://www.otodom.pl/")

    def test_otodom_search_results_rejected(self) -> None:
        """Search-results URLs structurally aren't listings."""
        with pytest.raises(InvalidOtodomURLError, match="path"):
            validate_otodom_listing_url(
                "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/mazowieckie/warszawa/warszawa/warszawa/wola"
            )

    def test_oferta_path_without_id_rejected(self) -> None:
        """Path looks like /pl/oferta/... but is missing the -ID<chars> suffix."""
        with pytest.raises(InvalidOtodomURLError, match="path"):
            validate_otodom_listing_url("https://www.otodom.pl/pl/oferta/just-a-slug")

    def test_english_path_rejected_for_now(self) -> None:
        """We don't (yet) support /en/ paths. If we ever do, this test should
        be replaced rather than deleted — it's a contract assertion."""
        with pytest.raises(InvalidOtodomURLError, match="path"):
            validate_otodom_listing_url("https://www.otodom.pl/en/offer/some-flat-ID1")

    def test_capitalised_host_accepted(self) -> None:
        """Hostname comparison is case-insensitive per RFC 3986."""
        # Should not raise.
        validate_otodom_listing_url("https://WWW.OTODOM.PL/pl/oferta/foo-ID1")
