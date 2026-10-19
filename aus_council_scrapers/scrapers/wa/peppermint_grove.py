from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect import CouncilConnectScraper


@register_scraper
class PeppermintGroveScraper(CouncilConnectScraper):
    """Shire of Peppermint Grove—documents on each meeting's own page.

    Council meetings only. Every meeting costs a request, and a year runs to
    about 26 of them, nearly half Agenda Briefing Forums—councillor briefings
    on the coming meeting's agenda, not decisions—plus the Audit Committee
    and the electors' meeting. Reading those would put one production year at
    ~30 requests; Council meetings alone took 13 for 2026.

    The Ordinary meetings were filed as `ordinary-council-meeting` until mid
    2023 and as `ordinary-meeting-of-council` since, so both are read.
    """

    meeting_types = {
        "ordinary-meeting-of-council": "Ordinary Council Meeting",
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }

    # One production year, measured 19 Oct 2026 from a home IP: 26 s (13
    # requests). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 26

    def __init__(self):
        super().__init__(
            "peppermint_grove", "WA", "https://www.peppermintgrove.wa.gov.au"
        )
