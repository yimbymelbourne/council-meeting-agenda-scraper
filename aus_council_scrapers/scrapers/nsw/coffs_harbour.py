import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class CoffsHarbourScraper(ResolveScraper):
    # Coffs Harbour's Resolve record starts with its 9 February 2023
    # meeting. The 2012-2022 papers are on per-year OpenCities content pages
    # under Archived-Council-meeting-minutes-and-agendas, which this scraper
    # does not read.
    tenant = "coffsharbour"

    # Council only; extraordinary meetings are typed Ordinary Council too.
    # The one other type is the Public Forum held before Council meetings
    # since 2026, where residents address councillors and nothing is
    # decided.
    meeting_types = re.compile(r"^Ordinary Council$")

    # Entered under Sunday 17 September 2023, but its name and agenda say
    # Thursday 14 September 2023.
    event_dates = {205: "2023-09-14"}

    def __init__(self):
        super().__init__("coffs_harbour", "NSW")
