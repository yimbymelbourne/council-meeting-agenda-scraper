import datetime
import re
from typing import Optional

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.resolve import ResolveScraper
from aus_council_scrapers.resolve_archives import opencities_meetings

# The council's OpenCities meetings page, which kept its papers until the
# move to Resolve.
MEETINGS = "https://www.moretonbay.qld.gov.au/Council/Meetings"


@register_scraper
class MoretonBayScraper(ResolveScraper):
    # Moreton Bay moved to Resolve for its 4 September 2024 General Meeting,
    # and its Council/Meetings page frames the tenant's older /web/ portal.
    # Meetings from 2017 to August 2024 are in that page's OpenCities
    # listing, read by `other_meetings`. Production asks for a year that is
    # all Resolve, so the archive costs it nothing.
    tenant = "moretonbay"
    resolve_from = datetime.date(2024, 9, 4)

    # Everything the tenant lists is a General Meeting (fortnightly, where
    # planning decisions are made) or a Special Meeting (budget adoption and
    # the like). The pattern still names both, so a committee the council
    # starts publishing here—the portal grid already shows an Audit
    # Committee the API does not—cannot add a request per meeting to the
    # nightly run unasked.
    meeting_types = re.compile(r"^(General|Special) Meeting$")

    def __init__(self):
        super().__init__("moreton_bay", "QLD")

    def other_meetings(self, wanted: set[int]) -> list[ScraperReturn]:
        # A year is three or four listing pages, nearly all of it General
        # Meetings, so the listing is not filtered by type; each kept
        # meeting is then a request for its papers.
        results = []
        for year in self.before_resolve(wanted):
            results += opencities_meetings(
                self,
                MEETINGS,
                year,
                _ARCHIVE_TYPES,
                _archive_name,
                before=self.resolve_from,
            )
        return results

    def _record(self, event, today) -> Optional[ScraperReturn]:
        record = super()._record(event, today)
        if record and not record.location:
            # General Meetings rotate between Caboolture, Strathpine and
            # Redcliffe, and the council writes the venue into the event
            # name—"General Meeting - 11 March 2026 (Caboolture)"—leaving
            # eventLocation empty.
            venue = _VENUE.search(event.get("name") or "")
            if venue:
                record.location = venue.group(1)
        return record


_VENUE = re.compile(r"\(([A-Z][A-Za-z ]+)\)\s*$")

# The OpenCities listing's types for the same two meetings, over the years:
# "General Meeting (inc Coordination Committee Meeting)" from when the
# committee met in the same sitting, "Community Council Meeting (inc
# General Meeting)" for one held out in the community, "Special General
# Meeting", and the statutory "Post-election Meeting". Left out are the
# Audit Committee and the Delegated Decisions Committee.
_ARCHIVE_TYPES = re.compile(
    r"^(General Meeting|Community Council Meeting|Special|Post-election)",
    re.IGNORECASE,
)


def _archive_name(meeting_type: str, title: str) -> str:
    # Named as the Resolve tenant names them, so a General Meeting reads the
    # same either side of the move.
    if meeting_type.lower().startswith("special"):
        return "Special Meeting"
    if meeting_type.lower().startswith("post-election"):
        return "Post-election Meeting"
    return "General Meeting"
