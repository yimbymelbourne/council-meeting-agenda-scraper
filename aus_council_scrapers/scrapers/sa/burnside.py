import datetime
import re

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.resolve import ResolveScraper
from aus_council_scrapers.resolve_archives import opencities_meetings

# The council's OpenCities meetings listing, which still carries the
# Council Assessment Panel and the Council meetings from before Resolve.
AGENDAS_MINUTES = "https://www.burnside.sa.gov.au/Agendas-Minutes"

PANEL = "Council Assessment Panel"


@register_scraper
class BurnsideScraper(ResolveScraper):
    # One production year, measured 19 Oct 2026 from a home IP: 29 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 29

    # Burnside's Public Meetings page frames its Resolve portal for Council
    # meetings from the tenant's first event, 29 November 2022. Two things
    # stayed on the OpenCities Agendas-Minutes listing: Council meetings
    # before that, and the Council Assessment Panel, which decides
    # development applications and was never moved to Resolve (the tenant
    # has no panel type). Both are read from there; see `other_meetings`.
    tenant = "burnside"
    resolve_from = datetime.date(2022, 11, 29)

    # Ordinary and Special Council. Left out are audit, CEO review and the
    # monthly information and briefing sessions, where nothing is decided;
    # each kept meeting costs a request to learn which documents it has.
    meeting_types = re.compile(r"^(Ordinary|Special) Council Meeting$")

    def __init__(self):
        super().__init__("burnside", "SA")

    def other_meetings(self, wanted: set[int]) -> list[ScraperReturn]:
        # The listing is filtered to one meeting type as well as one year:
        # unfiltered, a year is six pages, mostly workshops and committees.
        # So a production year costs one listing page and then a request per
        # panel meeting—about ten—and the Council rows are asked for only in
        # the years before Resolve.
        results = []
        for year in sorted(wanted):
            results += opencities_meetings(
                self, AGENDAS_MINUTES, year, _ANY, _name, meeting_type=PANEL
            )
        for year in self.before_resolve(wanted):
            results += opencities_meetings(
                self,
                AGENDAS_MINUTES,
                year,
                _ANY,
                _name,
                meeting_type="Council",
                before=self.resolve_from,
            )
        return results


_ANY = re.compile("")


def _name(meeting_type: str, title: str) -> str:
    if meeting_type == PANEL:
        return PANEL
    # The listing types every Council meeting "Council"; only the payload's
    # title line says a meeting was special. The names match the Resolve
    # tenant's own, so a meeting type reads the same across the move.
    if re.search(r"\bspecial\b", title, re.IGNORECASE):
        return "Special Council Meeting"
    return "Ordinary Council Meeting"
