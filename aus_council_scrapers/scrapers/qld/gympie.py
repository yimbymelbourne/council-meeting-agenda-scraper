import datetime
import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class GympieScraper(ResolveScraper):
    # Gympie's Council-Meetings page links the tenant's /web/ portal. Gympie
    # moved to Resolve for its 24 April 2024 Ordinary meeting. Earlier
    # papers (2010 to April 2024) are on OpenCities pages—the Council-Meetings
    # page itself and its Meetings-Archive—which this scraper does not read
    # yet, so its history starts at the move.
    tenant = "gympie"
    resolve_from = datetime.date(2024, 4, 24)

    # Ordinary meetings, with special and budget meetings filed under the
    # same type ("Special Ordinary Meeting - 2 June 2026", "Special Budget
    # Meeting"). Left out is the monthly "Workshop & Council Briefing",
    # where councillors are briefed and nothing is decided.
    meeting_types = re.compile(r"^Ordinary Meeting$")

    def __init__(self):
        super().__init__("gympie", "QLD")
