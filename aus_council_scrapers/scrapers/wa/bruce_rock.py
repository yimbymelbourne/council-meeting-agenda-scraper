from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.wa.wheatbelt_councilconnect import (
    WheatbeltCouncilConnectScraper,
)


@register_scraper
class BruceRockScraper(WheatbeltCouncilConnectScraper):
    """Shire of Bruce Rock—documents on each meeting's own page.

    Council meetings only. Each meeting costs a request, and a year runs to
    20–30 meetings across every type: about half are the Audit and Risk
    Committee and the Works and Services Committee, neither of which
    decides planning matters, plus the electors' meeting. Ordinary and
    Special Council meetings alone keep a production year near the ~20
    request aim.
    """

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }

    # One production year, measured 20 Oct 2026 from a home IP: 25 s
    # (12 requests—the year listings, the upcoming page and a page per
    # meeting). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 25

    def __init__(self):
        super().__init__("bruce_rock", "WA", "https://www.brucerock.wa.gov.au")
