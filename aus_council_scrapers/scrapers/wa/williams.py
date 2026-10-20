from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.wa.wheatbelt_councilconnect import (
    WheatbeltCouncilConnectScraper,
)


@register_scraper
class WilliamsScraper(WheatbeltCouncilConnectScraper):
    """Shire of Williams—documents on each meeting's own page.

    Every type is read, through the one all-types listing: the only types
    are Ordinary and Special Meeting of Council (the electors' meeting is
    filed under Ordinary), so there are no committees to leave out, and
    one listing is cheaper than one per type.

    From September 2026 the meeting pages link their papers in the page
    body rather than the documents block; the parent class reads them
    there (see `wheatbelt_councilconnect`).
    """

    # The /past index starts at 2021 and /past/2020 404s, which would fail
    # the whole scrape.
    first_year = 2021

    # One production year, measured 20 Oct 2026 from a home IP: 25 s
    # (13 requests—the year listings, the upcoming page and a page per
    # meeting). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 25

    def __init__(self):
        super().__init__("williams", "WA", "https://www.williams.wa.gov.au")
