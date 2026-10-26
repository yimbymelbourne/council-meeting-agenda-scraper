import datetime
import re

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.resolve import ResolveScraper
from aus_council_scrapers.scrapers.nsw.infocouncil_history import InfoCouncilHistory

INFOCOUNCIL_URL = "https://portmacquarie.infocouncil.biz/"


@register_scraper
class PortMacquarieHastingsScraper(ResolveScraper):
    # Port Macquarie-Hastings publishes through Resolve from its 19 November
    # 2025 meetings. Everything before is read from InfoCouncil, which the
    # council still serves with its full record from 2012 to October 2025.
    #
    # The tenant also holds copies of the 2020-2023 Council meetings, but
    # not the Development Assessment Panel and nothing for 2024 or January
    # to October 2025. InfoCouncil has every Council meeting the tenant
    # returns for 2020-2023, plus three it does not (20 May 2020, 23
    # September 2020, 6 September 2021). So `resolve_from` drops the copies
    # and one source covers each period. Production asks for a year that is
    # all Resolve, so InfoCouncil costs it nothing.
    tenant = "pmhc"
    resolve_from = datetime.date(2025, 11, 19)

    # Council (extraordinary meetings included) and the Development
    # Assessment Panel, which determines DAs. Left out are the Public Forum,
    # the Sports Council and the Local Transport Forum, which decide nothing
    # on planning. Each kept meeting costs a detail request.
    meeting_types = re.compile(r"^(Ordinary Council|Development Assessment Panel)$")

    # InfoCouncil's names for the same bodies, as Resolve names them. Its
    # grid also lists the Local Traffic Committee, the Sports Council and a
    # dozen advisory groups and sub-committees, which are dropped, and
    # "Ordinary Council - Former Confidential Report" rows, which are
    # reports released after a meeting, not a meeting.
    infocouncil_names = {
        "Ordinary Council": "Ordinary Council",
        "Extra Ordinary Council": "Extraordinary Council",
        "Development Assessment Panel": "Development Assessment Panel",
    }

    def __init__(self):
        super().__init__("port_macquarie_hastings", "NSW")

    def other_meetings(self, wanted: set[int]) -> list[ScraperReturn]:
        years = self.before_resolve(wanted)
        if not years:
            return []
        # One request a year, and no robots.txt on the host (404).
        archive = InfoCouncilHistory(self, INFOCOUNCIL_URL, self.infocouncil_names)
        return archive.meetings(years, before=self.resolve_from)
