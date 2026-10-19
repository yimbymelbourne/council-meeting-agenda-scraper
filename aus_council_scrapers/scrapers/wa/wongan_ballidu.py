from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.wa.councilconnect_shires import (
    ShireCouncilConnectScraper,
)


@register_scraper
class WonganBalliduScraper(ShireCouncilConnectScraper):
    """Shire of Wongan-Ballidu—documents on each meeting's own page.

    Council meetings only. Every meeting costs a request, so the electors'
    meeting and the Audit, Risk and Improvement Committee (first filed in
    2026) are left out to keep one production year near 15 requests; they
    are not where planning decisions are made. Development applications go
    to the Council itself (a late item on 20 August 2025 was one).

    The meetings module starts in 2021: the /past index lists 2021 onward,
    and /past/2020 is not in it.
    """

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }
    first_year = 2021

    # One production year, measured 20 Oct 2026 from a home IP: 26 s for
    # 13 requests (the type listings, one per Council meeting of the year
    # and the upcoming page). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 26

    def __init__(self):
        super().__init__("wongan_ballidu", "WA", "https://www.wongan.wa.gov.au")
