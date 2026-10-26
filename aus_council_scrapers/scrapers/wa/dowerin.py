from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.wa.wheatbelt_councilconnect import (
    WheatbeltCouncilConnectScraper,
)


@register_scraper
class DowerinScraper(WheatbeltCouncilConnectScraper):
    """Shire of Dowerin—documents on each meeting's own page.

    Council meetings only. A year runs to 20–35 meetings across every type,
    each a request: the Audit, Asset and Works, Local Emergency Management,
    Bush Fire Advisory, Road Verge and Australia Day Honours committees and
    the electors' meeting, none of which decides planning matters. 2026
    took 25 requests reading every type.

    Each meeting page carries the previous meeting's unconfirmed minutes as
    "Attachment 7.1A - UNCONFIRMED - Minutes ...", under the page's
    Attachments heading, which the base never reads.
    """

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }

    # One production year, measured 20 Oct 2026 from a home IP: 34 s
    # (19 requests—the year listings, the upcoming page and a page per
    # meeting). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 34

    def __init__(self):
        super().__init__("dowerin", "WA", "https://www.dowerin.wa.gov.au")
