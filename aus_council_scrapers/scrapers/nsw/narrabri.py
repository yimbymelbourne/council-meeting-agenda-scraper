import re
from typing import Optional

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class NarrabriScraper(ResolveScraper):
    # Narrabri has been on Resolve since November 2017, so the tenant holds
    # its whole record back past EARLIEST_YEAR.
    tenant = "narrabri"

    # Council meetings only: every Ordinary and Extraordinary meeting is
    # filed under the one type "Council", named as such in the event. The
    # tenant's other type is the Local Transport Forum (traffic advice, one
    # unpublished event in 2026). Each kept meeting costs a request to learn
    # which documents it has.
    meeting_types = re.compile(r"^Council$")
    meeting_type_names = {"Council": "Ordinary Council Meeting"}

    # The 20 November 2024 Ordinary meeting lapsed for want of a quorum
    # ("Cancelled due to lack of quorum" in its name, which the base class
    # only catches as a prefix). Its agenda was published but it has no
    # minutes, and its business went to the 27 November extraordinary
    # meeting.
    skip_events = frozenset({456})

    def __init__(self):
        super().__init__("narrabri", "NSW")

    def _record(self, event, today) -> Optional[ScraperReturn]:
        record = super()._record(event, today)
        if record and record.time:
            # Four 1 pm meetings were entered as 1 am (25 September 2018,
            # 12 September 2019, 28 February 2023, 28 May 2024). The 28
            # February 2023 agenda says "1.00pm"; the 28 May 2024 one,
            # generated from the event, repeats "1:00 AM". No council meets
            # before 7 am, so an hour that early is the afternoon.
            match = _EARLY_AM.match(record.time)
            if match:
                record.time = f"{match.group(1)} PM"
        return record

    def _meeting_name(self, event: dict) -> str:
        # "Extaordinary" (6 May 2024) and "Extrardinary" (9 October 2024)
        # would otherwise miss the base class's special-meeting match and
        # read as Ordinary meetings.
        name = _MISSPELT.sub("Extraordinary", event.get("name") or "")
        return super()._meeting_name({**event, "name": name})


_EARLY_AM = re.compile(r"^([1-6]:\d{2}) AM$")
_MISSPELT = re.compile(r"\bext\w*rdinary\b", re.IGNORECASE)
