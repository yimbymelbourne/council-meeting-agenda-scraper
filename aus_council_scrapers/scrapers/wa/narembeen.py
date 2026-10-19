from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.wa.wheatbelt_councilconnect import (
    WheatbeltCouncilConnectScraper,
)


@register_scraper
class NarembeenScraper(WheatbeltCouncilConnectScraper):
    """Shire of Narembeen—documents on each meeting's own page.

    Council meetings only. The other types are the Audit Committee and the
    electors' meeting, neither of which decides planning matters; leaving
    them out saves a request each per meeting. Special meetings are filed
    under a type called just "Special Meeting", and headed now "Special
    Council Meeting", now "Special Meeting of Council", now "Special
    Meeting"; every one from 2020 to 2026 is a Special Meeting of Council
    (read 20 Oct 2026), so that name is used throughout (`name_by_type`).
    """

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-meeting": "Special Meeting of Council",
    }

    name_by_type = True

    # One production year, measured 20 Oct 2026 from a home IP: 32 s
    # (17 requests—the year listings, the upcoming page and a page per
    # meeting). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 32

    def __init__(self):
        super().__init__("narembeen", "WA", "https://www.narembeen.wa.gov.au")
