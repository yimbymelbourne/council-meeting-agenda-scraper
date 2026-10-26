import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect_tidy import TidyCouncilConnectScraper

# The 2016 meetings are headed "Confirmed Minutes for Ordinary Council
# Meeting": the name of the document that was uploaded, not of the meeting.
_DOCUMENT_PREFIX = re.compile(
    r"^\s*(?:un)?confirmed\s+minutes\s+(?:for|of)\s+(?:the\s+)?", re.IGNORECASE
)


@register_scraper
class PortHedlandScraper(TidyCouncilConnectScraper):
    """Town of Port Hedland—documents on each meeting's own page.

    Council meetings only. A year also holds the Audit, Risk and Compliance
    (now Improvement) Committee, the Airport Committee and electors'
    meetings, and every meeting costs a request; Ordinary and Special
    Council meetings alone keep a production year at ~20.

    Special meetings are filed under two types, "special-council-meetings"
    and "special-council-meeting", so both are read and both are named
    "Special Council Meeting".
    """

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
        "special-council-meetings": "Special Council Meeting",
    }
    # The /past index starts at 2016; nothing older is in the module.
    first_year = 2016

    # One production year, measured 20 Oct 2026 from a home IP: 35 s (17
    # requests). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 35

    def __init__(self):
        super().__init__("port_hedland", "WA", "https://www.porthedland.wa.gov.au")

    def _name(self, heading, type_slug, labels):
        return super()._name(_DOCUMENT_PREFIX.sub("", heading or ""), type_slug, labels)
