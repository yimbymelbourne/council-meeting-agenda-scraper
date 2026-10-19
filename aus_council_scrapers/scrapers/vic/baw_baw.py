import re
from typing import Optional

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class BawBawScraper(ResolveScraper):
    # Baw Baw's Council-Meetings page links its Resolve portal, which holds
    # the whole record back to 2010.
    tenant = "bawbaw"

    # Everything Baw Baw files is an "Ordinary Council" event, except the
    # briefings it moved to "Councillor Briefing OLD". About 12 meetings a
    # year since 2024, so a production year is about 14 requests.
    meeting_types = re.compile(r"^Ordinary Council$")

    # A future-dated "test live stream" event, 12 July 2028. It is
    # unpublished, so it is dropped anyway; this keeps it out if anyone
    # ever publishes it.
    skip_events = frozenset({1091})

    def __init__(self):
        super().__init__("baw_baw", "VIC")

    def _record(self, event, today) -> Optional[ScraperReturn]:
        # The "Ordinary Council" type also carries events that are not
        # council meetings: officer and community briefings, community
        # participation time, the VEC's declaration of the poll and
        # swearing-in ceremonies. Dropping them by name here, before the
        # detail call, also saves that call's request.
        if _NOT_A_MEETING.search(event.get("name") or ""):
            return None
        record = super()._record(event, today)
        if record and record.time == "12:00 AM":
            # The events migrated from the old system up to March 2020
            # carry no time of day, which the API gives as midnight.
            record.time = None
        return record

    def _meeting_name(self, event: dict) -> str:
        name = event.get("name") or ""
        # The statutory meeting elects the mayor each November; confidential
        # meetings are closed council meetings held before an ordinary one,
        # with their own public agenda and minutes. Without these the type
        # names both "Ordinary Council".
        if re.search(r"\bstatutory\b", name, re.IGNORECASE):
            return "Statutory Council"
        if re.search(r"\bconfidential\b", name, re.IGNORECASE):
            return "Confidential Council"
        if re.search(r"\bmayoral election\b", name, re.IGNORECASE):
            return "Special Council"
        # A hearing of submissions (on the budget, or on the council plan
        # and other strategic documents) is run as a formal meeting of
        # council, with prayer, declarations of interest, a report and
        # confirmed minutes (5 March 2025, event 1759). Councillors hear
        # submitters and decide nothing; the budget is adopted at a later
        # meeting. So it is kept, under its own name, for a reader to
        # filter out.
        if re.search(r"\bhearing of\b", name, re.IGNORECASE):
            return "Hearing of Submissions"
        return super()._meeting_name(event)


_NOT_A_MEETING = re.compile(
    r"briefing|participation time|declaration of polls?|swearing",
    re.IGNORECASE,
)
