import datetime
import re
from typing import Optional

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.councilconnect import CouncilConnectArchive
from aus_council_scrapers.resolve import ResolveScraper

SITE = "https://www.eastpilbara.wa.gov.au"


@register_scraper
class EastPilbaraScraper(ResolveScraper):
    # The Shire moved its Council meetings to Resolve for the 26 July 2024
    # Ordinary Meeting, the tenant's first event. Meetings from 2012 to July
    # 2024 are in the CouncilConnect module the site still serves at
    # /council-meetings/past/<year>, read by `other_meetings`. The module
    # carries on listing meetings after the move, but with the minutes alone
    # or nothing (August to December 2024), so it is read only for meetings
    # before 26 July 2024. Production asks for a year that is all Resolve,
    # so the module, behind Cloudflare on the Shire's own site, costs it
    # nothing.
    tenant = "eastpilbara"
    resolve_from = datetime.date(2024, 7, 26)

    # Ordinary and special Council meetings, which the tenant types alike
    # and tells apart only by the event name. Left out is the Audit, Risk and
    # Improvement Committee; each kept meeting costs a request to learn
    # which documents it has.
    meeting_types = re.compile(r"^Council Meeting$")
    # Named as the CouncilConnect module names the same meetings, so a
    # meeting type reads the same either side of the move; a special
    # meeting becomes "Special Council Meeting" (see `_SPECIAL` in
    # resolve.py).
    meeting_type_names = {"Council Meeting": "Ordinary Council Meeting"}

    # The tenant dates the August 2024 Ordinary Meeting Thursday 22 August.
    # Its agenda and minutes both say Friday 23 August 2024 at 10:30am, as
    # does the CouncilConnect module (checked 20 Oct 2026).
    event_dates = {72: "2024-08-23"}

    def __init__(self):
        super().__init__("east_pilbara", "WA")

    def _record(self, event: dict, today: datetime.date) -> Optional[ScraperReturn]:
        # The General Electors' Meetings (7 February 2025, 6 February 2026)
        # are filed under the Council Meeting type, beside a special Council
        # meeting on the same morning. An electors' meeting decides nothing,
        # and it would otherwise come out named as a Council meeting.
        # Checked before the detail call, so it is free.
        if _ELECTORS.search(event.get("name") or ""):
            return None
        return super()._record(event, today)

    def other_meetings(self, wanted: set[int]) -> list[ScraperReturn]:
        before = self.before_resolve(wanted)
        if not before:
            return []
        # The per-type year listings, one or two pages each; a meeting page
        # per meeting carries its documents.
        results = CouncilConnectArchive(
            self,
            SITE,
            _ARCHIVE_TYPES,
            wrong_documents=_WRONG_DOCUMENTS,
            untimed_before=_TIMES_FROM,
        ).read(set(before), before=self.resolve_from)
        for record in results:
            if record.webpage_url in _ARCHIVE_WHEN:
                record.date, record.time = _ARCHIVE_WHEN[record.webpage_url]
        return results


_ELECTORS = re.compile(r"\belectors?'?\b", re.IGNORECASE)

# The module's Council meeting types, named as the module's checkboxes name
# them. Left out are the audit, airport, plant and emergency management
# committees and the electors' meetings.
_ARCHIVE_TYPES = {
    "ordinary-council-meeting": "Ordinary Council Meeting",
    "special-council-meeting": "Special Council Meeting",
}

# Documents the module files against the wrong meeting, checked by reading
# them.
_WRONG_DOCUMENTS = {
    f"{SITE}/council-meetings/ordinary-council-meeting/22-july-2022/216/documents/"
    "confirmed-ordinary-minutes-july-22-2022-audit-committee.pdf": (
        "the Audit, Risk and Governance Committee's minutes of the same day, "
        "filed under the Council meeting's Minutes heading; the Council's own "
        "are further down the page"
    ),
}

# The module's time field is first filled in October 2021, and its 2021
# times are upload stamps: 19 November and 17 December say 11:15 AM and 3:05
# PM, where both agendas say 10:30AM, and the 22 October special meeting says
# 5:00 PM against its agenda's 12.30pm. From 2022 the field agrees with the
# agenda for every meeting but one, corrected below (each timed meeting's
# agenda read 20 Oct 2026; 3 November 2022 and 30 June 2023 give no time on
# their first pages). So meetings before 2022 carry no time.
_TIMES_FROM = datetime.date(2022, 1, 1)

# Meetings whose date or time field is wrong in the module, by meeting page,
# each checked against the agenda (read 20 Oct 2026). The 25 August 2023
# Ordinary Meeting is dated Thursday 24 August at 9:58pm; its heading,
# filenames and agenda say Friday 25 August 2023 at 10.30am in Nullagine.
# The 25 March 2022 one says 10:00 AM; its agenda says 10:30AM.
_ARCHIVE_WHEN = {
    f"{SITE}/council-meetings/ordinary-council-meeting/"
    "25-august-2023-ordinary-council-meeting/257": ("2023-08-25", "10:30 AM"),
    f"{SITE}/council-meetings/ordinary-council-meeting/25-march-2022/212": (
        "2022-03-25",
        "10:30 AM",
    ),
}
