import datetime
import re

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import (
    InfoCouncilScraper,
    ScraperReturn,
    register_scraper,
)
from aus_council_scrapers.constants import EARLIEST_YEAR
from aus_council_scrapers.opencities import OpenCitiesArchive
from aus_council_scrapers.scrapers.nsw.dotted_time import colon_times

# Parkes's papers up to its move to InfoCouncil: an OpenCities meetings
# listing covering 2013–2022.
ARCHIVE = (
    "https://www.parkes.nsw.gov.au/Council/Council-meetings/"
    "Archive-Business-papers-and-minutes-2013-2022"
)

# The first meeting on InfoCouncil, the 20 December 2022 Ordinary Council
# Meeting. The archive lists it too; from this day InfoCouncil's copy is used.
INFOCOUNCIL_FROM = datetime.date(2022, 12, 20)

# InfoCouncil names an extra meeting of a committee "Extra <committee>",
# which gives "Extra Local Traffic Forum" and, for an extra meeting of the
# Extraordinary Council Meeting committee, "Extra Extraordinary Council
# Meeting".
_EXTRA = re.compile(r"^Extra\s+(?:Extraordinary\s+)?")


@register_scraper
class ParkesScraper(InfoCouncilScraper):
    # The council's Business papers and minutes page frames this grid. Every
    # body is kept: the grid is one request a year whatever it lists. The
    # committee cell carries the venue and supplementary agendas get rows of
    # their own, so the tidy flag is on.
    #
    # Asking for a year the grid does not hold (2020, 2021, 2027) returns the
    # current year's grid instead. Those rows are dated in the current year,
    # so the base class's check that each row's date is in the year asked for
    # already drops them. Meetings before INFOCOUNCIL_FROM come from the
    # OpenCities archive instead—see `scraper`.
    tidy_meeting_rows = True

    def __init__(self):
        super().__init__(
            "parkes",
            "NSW",
            "https://www.parkes.nsw.gov.au",
            "https://parkes.infocouncil.biz/",
        )

    def scraper(self) -> list[ScraperReturn]:
        results = super().scraper()
        for record in results:
            if record.name:
                record.name = _EXTRA.sub("Extraordinary ", record.name)
            # The first InfoCouncil meeting, 20 December 2022, is filed under
            # a committee called just "Council"; its papers are OCM_ files,
            # and every later one is an "Ordinary Council Meeting".
            if record.name == "Council":
                record.name = "Ordinary Council Meeting"

        # The archive is read only for the years before the move, so a
        # production run (the current year) never touches it.
        years_filter = getattr(self, "years_filter", None)
        wanted = (
            set(years_filter)
            if years_filter
            else set(range(EARLIEST_YEAR, clock.current_year() + 3))
        )
        archive_years = {y for y in wanted if y <= INFOCOUNCIL_FROM.year}
        if archive_years:
            results += _ParkesArchive(self, ARCHIVE, _archive_name).read(
                archive_years, before=INFOCOUNCIL_FROM
            )
        # A few rows write the time with a dot ("10.00am"), which the shared
        # time parsing misreads; see dotted_time.
        return colon_times(results)


class _ParkesArchive(OpenCitiesArchive):
    # The archive files the agenda under "Business Paper", beside "Minutes"
    # and "Annexure - ..." headings. Heading mode only knows "Agenda", so the
    # heading is renamed before it is read.
    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        for heading in content.select("div.meeting-document > h3"):
            text = heading.get_text(" ", strip=True)
            if re.match(r"^Business\s+Papers?$", text, re.IGNORECASE):
                heading.string = "Agenda"
        return super().papers(content)


def _archive_name(meeting_type: str, title: str) -> str:
    # The archive's types are "Ordinary Meeting" and "Extraordinary Meeting";
    # named here as InfoCouncil names them, so a meeting type reads the same
    # across the move.
    if re.search(r"extra", meeting_type, re.IGNORECASE):
        return "Extraordinary Council Meeting"
    return "Ordinary Council Meeting"
