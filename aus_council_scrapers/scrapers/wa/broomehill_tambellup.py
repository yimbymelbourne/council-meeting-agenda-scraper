from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.wa.councilconnect_shires import (
    ShireCouncilConnectScraper,
)


@register_scraper
class BroomehillTambellupScraper(ShireCouncilConnectScraper):
    """Shire of Broomehill-Tambellup—documents on each meeting's own page.

    Council meetings only. Every meeting costs a request, and since 2025 the
    shire also files its audit, Bush Fire Advisory, LEMC and CEO review
    committees and the electors' meeting: 19 meetings and 22 requests for
    2026 with all of them, none of them where planning decisions are made.

    Early 2020 meetings have minutes only; what sits beside them is the
    minutes' attachments (one, 19 March 2020, uploaded as
    "agenda-attachments-...") and is rightly left out.
    """

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }

    # One production year, measured 20 Oct 2026 from a home IP: 26 s for
    # 13 requests (the type listings, one per Council meeting of the year
    # and the upcoming page). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 26

    def __init__(self):
        super().__init__("broomehill_tambellup", "WA", "https://www.shirebt.wa.gov.au")
