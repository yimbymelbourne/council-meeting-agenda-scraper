import datetime
import re
from typing import Optional

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class NapranumScraper(ResolveScraper):
    # Napranum's council-meetings page links its Resolve portal, which
    # starts with the 8 February 2022 meeting. The 2020–2021 papers are
    # still PDFs on that WordPress page and are not read here yet, so
    # `resolve_from` keeps those years from costing listing calls.
    tenant = "napranum"
    resolve_from = datetime.date(2022, 2, 8)

    # The tenant's three types, all of them the full council: ordinary
    # meetings, special meetings (stored as "Special Meeting " with a
    # trailing space, which the base class strips), and the council sitting
    # as trustee of the shire's Deed of Grant in Trust land, which decides
    # leases and land use. About 14 meetings a year, so a production year is
    # about 16 requests. Naming them keeps a committee the council starts
    # publishing here from adding a request per meeting unasked.
    meeting_types = re.compile(
        r"^(Ordinary General Meeting|Special Meeting|NASC Trustee Meeting)$"
    )

    # Event 467 is the 30 March 2026 meeting that was brought forward to
    # 23 March: it is named "Council Meeting 23 March 2026", has an agenda
    # and packet but no minutes, and its papers are the same business as
    # event 496, whose minutes say the meeting sat on Monday 23 March 2026.
    skip_events = frozenset({467})

    def __init__(self):
        super().__init__("napranum", "QLD")

    def _record(self, event, today) -> Optional[ScraperReturn]:
        record = super()._record(event, today)
        if record and record.time == "12:00 AM":
            # Early-2023 events were entered with no time of day, which
            # the API gives as midnight.
            record.time = None
        return record

    def _meeting_name(self, event: dict) -> str:
        # The type does not tell the meetings apart: special, budget,
        # trustee and post-election meetings are all also filed as
        # "Ordinary General Meeting". Only the free-typed event name does.
        name = event.get("name") or ""
        if re.search(r"\btrustee\b", name, re.IGNORECASE):
            return "NASC Trustee Meeting"
        if re.search(r"post.election", name, re.IGNORECASE):
            return "Post-Election Meeting"
        # The yearly budget adoption, held as its own meeting on an
        # ordinary meeting's afternoon or a day of its own, and named
        # "Budget Meeting 2025/2026", "Special Budget Meeting" or "Special
        # Meeting Draft Budget" from year to year.
        if re.search(r"\bbudget\b", name, re.IGNORECASE):
            return "Budget Meeting"
        if re.search(r"\b(special|extraordinary)\b", name, re.IGNORECASE) or (
            _type(event) == "Special Meeting"
        ):
            return "Special Council Meeting"
        return "Ordinary Council Meeting"


def _type(event: dict) -> str:
    return (event.get("meetingTypeName") or "").strip()
