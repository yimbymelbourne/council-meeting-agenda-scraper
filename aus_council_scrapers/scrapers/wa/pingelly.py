import datetime
import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.wa.councilconnect_shires import (
    ShireCouncilConnectScraper,
)

# In 2020–2021 the module filed five meetings' agendas under an "Attachment"
# heading as a link called just "Document" ("20200715-document.pdf"), with
# the attachments bundle beside it as "Document 1". The base never reads an
# attachment group, so those meetings had minutes only. All five were read
# (15 July, 19 August, 16 September and 21 October 2020, 21 April 2021);
# each opens "Council Agenda ... Ordinary Council Meeting <date>", and
# "Document 1" (15 July 2020) opens "Attachments". So only the bare
# "Document" is taken, and only from that heading.
_ATTACHMENT_GROUP = re.compile(r"^\s*attachments?\s*$", re.IGNORECASE)
_BARE_DOCUMENT = re.compile(r"^\s*document\s*$", re.IGNORECASE)

_MEETINGS = (
    "https://www.pingelly.wa.gov.au/council-meetings/ordinary-meeting-of-council"
)
# The November 2023 Ordinary meeting was put back a week, and the module
# keeps both pages: 15 November with the agenda only, and 22 November
# "(Rescheduled)" with the minutes only. It was held once, on the 22nd: the
# 22 November minutes confirm 18 and 25 October as the previous meetings,
# with no 15 November, and they follow the 15 November agenda item by item
# (both read, 20 Oct 2026). So the agenda goes on the meeting that was held
# and the 15 November page, a meeting that never sat, is not emitted.
_MOVED_MEETINGS = {
    f"{_MEETINGS}/ordinary-meeting-of-council-15-november-2023/212": (
        f"{_MEETINGS}/ordinary-meeting-of-council-22-november-2023-(rescheduled)/211"
    ),
}


@register_scraper
class PingellyScraper(ShireCouncilConnectScraper):
    """Shire of Pingelly—documents on each meeting's own page.

    Council meetings only. Every meeting costs a request, so the audit
    committee and the electors' meetings are left out; neither is where
    planning decisions are made.

    The upcoming page is a table of every meeting the module has ever had
    scheduled, ~200 links, but each link's title carries its date ("... -
    21/10/2026"), so the base fetches only the Council meetings close
    enough to have papers. Meeting slugs are generic
    (`/ordinary-council-meeting/353`), so dates come from the page.

    Every meeting entered before 2025 has the module's time of "6:00 PM",
    a default: the agendas and minutes checked say 2 pm (15 July 2020, 21
    April 2021, 15 June 2022, 22 November 2023, 15 May 2024), 5 pm (25
    October 2023) and 7 pm (16 December 2024). Those meetings are emitted
    with no time. From 2025 the module's times are the meetings' own (6 pm
    on 22 January 2025 is the agenda's).
    """

    placeholder_time = ("6:00 PM", datetime.date(2025, 1, 1))

    meeting_types = {
        "ordinary-meeting-of-council": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }

    # One production year, measured 20 Oct 2026 from a home IP: 25 s for
    # 13 requests (the type listings, one per Council meeting of the year
    # and the upcoming page). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 25

    def __init__(self):
        super().__init__("pingelly", "WA", "https://www.pingelly.wa.gov.au")

    def _fix_document(self, group, label, url):
        group, label, url = super()._fix_document(group, label, url)
        if _ATTACHMENT_GROUP.match(group or "") and _BARE_DOCUMENT.match(label):
            return "Agenda", "Agenda", url
        return group, label, url

    def scraper(self):
        results = super().scraper()
        by_page = {meeting.webpage_url: meeting for meeting in results}
        for moved_url, held_url in _MOVED_MEETINGS.items():
            moved, held = by_page.get(moved_url), by_page.get(held_url)
            if not (moved and held):
                continue
            held.agenda_url = held.agenda_url or moved.agenda_url
            held.minutes_url = held.minutes_url or moved.minutes_url
            held.download_url = held.agenda_url or held.minutes_url
            results.remove(moved)
        return results
