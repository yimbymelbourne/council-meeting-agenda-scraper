import datetime
import re

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.resolve import ResolveScraper
from aus_council_scrapers.scrapers.nsw.infocouncil_history import InfoCouncilHistory

INFOCOUNCIL_URL = "https://byron.infocouncil.biz/"


@register_scraper
class ByronScraper(ResolveScraper):
    # Byron publishes through Resolve from its 14 August 2025 Planning
    # Meeting, the tenant's first event. Its meetings from 2015 to the 30
    # June 2025 extraordinary meeting are on InfoCouncil, which the council
    # still serves and `other_meetings` reads. There was no Council meeting
    # in July 2025. Production asks for a year that is all Resolve, so
    # InfoCouncil costs it nothing.
    tenant = "byron"
    resolve_from = datetime.date(2025, 8, 14)

    # Council only. Every Council meeting—ordinary, planning, extraordinary—
    # has the one type, "Council Meeting". Left out are the Public Access
    # Forum, the yearly "Questions on Notice - Public Access" register, the
    # Local Transport Forum, the audit committee and nine advisory
    # committees. The tenant lists about 50 events a year, and each kept one
    # costs a detail request.
    meeting_types = re.compile(r"^Council Meeting$")

    # InfoCouncil's names for the same three meetings, mapped to the names
    # `_meeting_name` gives them on Resolve. Its grid also lists the Local
    # Traffic Committee, the audit committee and about thirty advisory
    # committees and panels, none of which decides anything; they are not
    # here, so they are dropped.
    infocouncil_names = {
        "Council": "Council Ordinary Meeting",
        "Council (Planning)": "Council Planning Meeting",
        "Extra Council": "Council Extraordinary Meeting",
    }

    def __init__(self):
        super().__init__("byron", "NSW")

    def other_meetings(self, wanted: set[int]) -> list[ScraperReturn]:
        years = self.before_resolve(wanted)
        if not years:
            return []
        # One request a year, and no robots.txt on the host (404).
        archive = InfoCouncilHistory(self, INFOCOUNCIL_URL, self.infocouncil_names)
        return archive.meetings(years, before=self.resolve_from)

    def _meeting_name(self, event: dict) -> str:
        # The one type covers two monthly meetings on different Thursdays—a
        # Planning Meeting that determines DAs and planning proposals, and
        # the Ordinary Meeting—so the type name alone would make them read
        # as one body. Only the free-typed event name tells them apart:
        # "Council Planning Meeting - 14 August 2025", "Council Ordinary
        # Meeting - 28 August 2025", "Ordinary Council Meeting - 19 February
        # 2026", "Council Planning & Ordinary Meeting - 11 December 2025",
        # "Council Extraordinary Meeting - 30 April 2026".
        name = event.get("name") or ""
        if re.search(r"\b(extraordinary|special)\b", name, re.IGNORECASE):
            return "Council Extraordinary Meeting"
        planning = re.search(r"\bplanning\b", name, re.IGNORECASE)
        ordinary = re.search(r"\bordinary\b", name, re.IGNORECASE)
        if planning and ordinary:
            return "Council Planning and Ordinary Meeting"
        if planning:
            return "Council Planning Meeting"
        return "Council Ordinary Meeting"
