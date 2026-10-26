from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.wa.councilconnect_tidy import (
    WATidyCouncilConnectScraper,
)


@register_scraper
class DenmarkScraper(WATidyCouncilConnectScraper):
    """Shire of Denmark—documents on each meeting's own page.

    The meetings module has only two types, Ordinary (slug `meeting`, shown
    as plain "Meeting") and Special (`special-meeting`), 13 to 20 meetings a
    year. They are named here rather than read through the all-types
    listing so that a committee type added later does not quietly add a
    request per meeting.

    Headings switched from "Ordinary Council Meeting" to "25 November 2025
    - Ordinary Meeting" part way through, so names come from the type
    (`name_by_type`); the electors' meetings filed under either type keep
    their own names.
    """

    meeting_types = {
        "meeting": "Ordinary Council Meeting",
        "special-meeting": "Special Council Meeting",
    }

    name_by_type = True

    # One production year, measured 20 Oct 2026 from a home IP: 37 s for
    # 16 requests. Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 37

    def __init__(self):
        super().__init__("denmark", "WA", "https://www.denmark.wa.gov.au")
