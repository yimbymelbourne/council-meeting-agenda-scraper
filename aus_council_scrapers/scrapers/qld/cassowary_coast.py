import re
from typing import Optional

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class CassowaryCoastScraper(ResolveScraper):
    # Cassowary Coast's Council-Meetings-and-Agendas page links the Resolve
    # portal for its agendas; the PDFs listed on that page itself are
    # councillor information sessions and workshops, where nothing is
    # decided. The whole record is on Resolve.
    tenant = "cassowarycoast"

    # The council's own name for its ordinary meeting is "Local Government
    # Meeting", and special meetings share that type ("Special Meeting, 16
    # October 2025"). Budget meetings have a type of their own. The Planning
    # Committee is the planning body of the standing committees that met
    # until March 2020; the other six are left out, since each kept meeting
    # costs a request to learn which documents it has.
    meeting_types = re.compile(
        r"^(Local Government Meeting|Budget Meeting|Planning Committee)$"
    )

    # Not `include_unpublished`: in range, the budget meetings of 2023 to
    # 2026 and the special meeting of 9 July 2026 are marked unpublished,
    # and checking them would mean asking DocPreview, which cassowarycoast.resolve.red's
    # robots.txt (`Disallow: /`) rules out. The scraper requests only
    # api.resolve.red and emits the DocPreview links without fetching them.

    def __init__(self):
        super().__init__("cassowary_coast", "QLD")

    def _record(self, event, today) -> Optional[ScraperReturn]:
        record = super()._record(event, today)
        if record and event["id"] in _AGENDA_AS_MINUTES:
            record.minutes_url = None
            record.download_url = record.agenda_url
        return record


# Events whose minutes file is the agenda. Found 20 Oct 2026 by comparing
# the sizes of every kept meeting's packet and minutes: the 22 April 2021
# Local Government Meeting's minutes are its 75-page agenda packet, byte for
# byte the same size and opening "LOCAL GOVERNMENT MEETING AGENDA".
_AGENDA_AS_MINUTES = frozenset({964})
