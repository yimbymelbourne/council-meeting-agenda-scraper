from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect_tidy import TidyCouncilConnectScraper


@register_scraper
class DardanupScraper(TidyCouncilConnectScraper):
    """Shire of Dardanup—documents on each meeting's own page.

    Council meetings only. 2025 listed 34 meetings: besides Ordinary and
    Special Council meetings, the audit, emergency management, bushfire
    advisory and integrated planning committees and the electors' meeting.
    Each costs a request, so reading them all would double a production
    year; Ordinary and Special meetings alone are ~20.
    """

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }
    # The /past index starts at 2017; nothing older is in the module.
    first_year = 2017

    # One production year, measured 20 Oct 2026 from a home IP: 36 s (16
    # requests). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 36

    def __init__(self):
        super().__init__("dardanup", "WA", "https://www.dardanup.wa.gov.au")
