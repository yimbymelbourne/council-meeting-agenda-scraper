"""Recognise the meeting-publishing platform a council runs.

Councils rarely build their own agenda system — they buy one of a handful,
and several of those already have a base class here. Identifying the platform
before writing a parser is the difference between a ten-line subclass and a
day of BeautifulSoup, so it is the first thing worth checking.

Signatures are matched against both the page body and its URL, because a
council's own site often just links out to the platform rather than
containing its markup.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Platform:
    name: str
    #: Regexes matched case-insensitively against the URL and page body.
    signatures: tuple[str, ...]
    #: What to do about it.
    guidance: str
    #: An existing scraper to copy, if we already handle this platform.
    reference: str | None = None


PLATFORMS: tuple[Platform, ...] = (
    Platform(
        name="InfoCouncil",
        signatures=(r"infocouncil\.biz", r"bpsGridPDFLink", r"grdMenu"),
        guidance=(
            "Subclass InfoCouncilScraper and pass the infocouncil URL. "
            "Usually about ten lines — do not write a parser."
        ),
        reference="aus_council_scrapers/scrapers/nsw/innerwest.py",
    ),
    Platform(
        name="docspublished",
        signatures=(r"docspublished\.com\.au",),
        guidance="JSON API. Copy the request/parse shape from Parramatta.",
        reference="aus_council_scrapers/scrapers/nsw/parramatta.py",
    ),
    Platform(
        name="OpenCities",
        signatures=(
            r"OCServiceHandler\.axd",
            r"ocsvc/Public/meetings",
            r"accordion-list-item-container",
        ),
        guidance=(
            "Meeting detail comes from the OCServiceHandler AJAX endpoint, "
            "keyed by a cvid found on the listing page."
        ),
        reference="aus_council_scrapers/scrapers/vic/banyule.py",
    ),
    Platform(
        name="Granicus/Legistar",
        # Granicus sells several unrelated products, including OpenCities —
        # a general council-website CMS with no connection to Legistar's
        # meeting/agenda system. Every OpenCities site credits it by URL in
        # its own generator meta tag and footer (.../product/opencities,
        # .../solution/govaccess/opencities/), which otherwise satisfies
        # this signature on any OpenCities council regardless of what
        # actually publishes its agendas — confirmed on Logan and Ipswich,
        # both really on eScribe and InfoCouncil respectively. The lookahead
        # excludes only that self-referential branding path; a genuine
        # Granicus agenda URL (a subdomain, or /solution/agenda-management/)
        # is unaffected.
        signatures=(r"granicus\.com(?![\w/-]*opencities)", r"legistar"),
        guidance="No base class yet — first council on this platform gets to write one.",
    ),
    Platform(
        name="Civica",
        signatures=(r"civicaepathway", r"civica\.com"),
        guidance="No base class yet — first council on this platform gets to write one.",
    ),
)

#: Platform links pointing off the council's own domain.
_EXTERNAL_PLATFORM = re.compile(
    r"https?://([a-z0-9-]+\.(?:infocouncil\.biz|docspublished\.com\.au))", re.I
)


def detect(html: str, url: str = "") -> list[Platform]:
    """Return every platform whose signature appears, most specific first."""
    haystack = f"{url}\n{html}"
    return [
        platform
        for platform in PLATFORMS
        if any(re.search(sig, haystack, re.I) for sig in platform.signatures)
    ]


def platform_links(html: str) -> set[str]:
    """Hosts the page links out to that we recognise as platforms."""
    return {match.lower() for match in _EXTERNAL_PLATFORM.findall(html)}


def is_cloudflare_challenge(headers: dict) -> bool:
    """A Cloudflare interstitial needs a real browser.

    No User-Agent gets past it, so a council in this state wants Selenium
    rather than another header experiment.
    """
    lowered = {k.lower(): str(v).lower() for k, v in headers.items()}
    if "cf-mitigated" in lowered:
        return True
    return "cloudflare" in lowered.get("server", "")
