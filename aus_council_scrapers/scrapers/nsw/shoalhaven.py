import datetime
import re

from aus_council_scrapers.base import (
    InfoCouncilScraper,
    ScraperReturn,
    register_scraper,
)

# Shoalhaven's grid gives the date as "27/10/2026" and no time, which the
# project's DATE_REGEX does not match: it takes "27 Oct 2026" or dashes.
_SLASH_DATE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b")


@register_scraper
class ShoalhavenScraper(InfoCouncilScraper):
    # InfoCouncil holds Shoalhaven's papers from September 2016, older ones
    # are on the council site, and the grid lists every committee on one page
    # a year, so keeping them all costs nothing extra. Supplementary agendas
    # get rows of their own ("Ordinary Meeting Supplementary"), so the tidy
    # flag is on.
    tidy_meeting_rows = True

    def __init__(self):
        super().__init__(
            "shoalhaven",
            "NSW",
            "https://www.shoalhaven.nsw.gov.au",
            "https://shoalhaven.infocouncil.biz/",
        )
        self.date_regex = _SLASH_DATE

    def scraper(self) -> list[ScraperReturn]:
        meetings = super().scraper()
        # The base class's own year check only needs the year, which a
        # slashed date gives whichever way round it is read. But dateutil
        # reads "05/10/2026" month first, as 10 May, so hand back an ISO date
        # rather than the grid's string.
        for meeting in meetings:
            meeting.date = (
                datetime.datetime.strptime(meeting.date, "%d/%m/%Y")
                .date()
                .isoformat()
            )
        return meetings
