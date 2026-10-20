from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect import CouncilConnectScraper


@register_scraper
class NedlandsScraper(CouncilConnectScraper):
    """City of Nedlands—documents on each meeting's own page.

    Council meetings only. A year runs to 35–50 meetings, each a request:
    Agenda Briefing Forums, the audit and CEO committees, the arts
    committees. Ordinary and Special Council meetings, through their own
    year pages, are ~25 requests a production year—more than most councils,
    because Nedlands holds a Special meeting most months (9 by October 2026).

    Left out on purpose: the Council Committee, which until 2021 took the
    Planning & Development reports—including the council's recommendations
    to the JDAP—ahead of the Ordinary meeting. It has not met since
    2021 (the two 2024 entries filed under it are Foreshore Management
    Steering Committee meetings), and production reads only the current
    year, so reading it would cost a request every night and find nothing.
    Its 2020–2021 meetings are the history this gives up.
    """

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }

    # One production year, measured 19 Oct 2026 from a home IP: 48 s (25
    # requests, one per Council meeting). Orders dispatch only (slowest
    # first); see BaseScraper.expected_seconds.
    expected_seconds = 48

    def __init__(self):
        super().__init__("nedlands", "WA", "https://www.nedlands.wa.gov.au")
