"""Tests for platform fingerprinting.

Pure string matching, so it is worth pinning down directly — a signature that
silently stops matching would send someone off to write a parser for a
platform already handled by a ten-line subclass.
"""

from aus_council_scrapers.platforms import (
    detect,
    is_js_challenge,
    platform_links,
)


def test_detects_infocouncil_from_the_url_alone():
    """Councils often link straight out to the platform, so the URL is a
    signature in its own right."""
    found = detect("", "https://burwood.infocouncil.biz/?year=2024")
    assert [p.name for p in found] == ["InfoCouncil"]


def test_detects_infocouncil_from_markup():
    html = '<table id="grdMenu"><a class="bpsGridPDFLink" href="x.pdf">Agenda</a></table>'
    assert [p.name for p in detect(html)] == ["InfoCouncil"]


def test_detects_opencities():
    html = '<div class="accordion-list-item-container" data-cvid="123"></div>'
    assert [p.name for p in detect(html)] == ["OpenCities"]


def test_detects_docspublished():
    found = detect("", "https://docspublished.com.au/CityofParramatta")
    assert [p.name for p in found] == ["docspublished"]


def test_unknown_platform_returns_nothing():
    assert detect("<html><body><h1>Meetings</h1></body></html>") == []


def test_finds_platform_links_on_a_council_page():
    """A council's own page frequently just links to the platform."""
    html = '<a href="https://bayside.infocouncil.biz/Default.aspx">Business papers</a>'
    assert platform_links(html) == {"bayside.infocouncil.biz"}


def test_platform_links_ignores_unrelated_hosts():
    assert platform_links('<a href="https://www.google.com/">Search</a>') == set()


def test_recognises_a_cloudflare_challenge():
    """Distinct from a plain 403: no User-Agent gets past this one."""
    assert is_js_challenge({"cf-mitigated": "challenge", "Server": "cloudflare"})
    assert is_js_challenge({"Server": "cloudflare"})


def test_recognises_an_aws_waf_challenge():
    """The dangerous one: 202 and an empty body, so nothing raises.

    `melbourne` answered this to every header set we tried, which is why a
    scraper built on `fetch_with_requests` there found nothing and looked
    merely unfinished rather than blocked.
    """
    assert is_js_challenge({"x-amzn-waf-action": "challenge", "Server": "CloudFront"})


def test_plain_403_is_not_a_cloudflare_challenge():
    assert not is_js_challenge({"Server": "nginx"})
    assert not is_js_challenge({})


def test_every_platform_reference_exists():
    """A reference scraper that has been renamed would send someone to a file
    that is not there."""
    import os

    from aus_council_scrapers.platforms import PLATFORMS

    for platform in PLATFORMS:
        if platform.reference:
            assert os.path.exists(platform.reference), (
                f"{platform.name} points at {platform.reference}, which is missing"
            )
