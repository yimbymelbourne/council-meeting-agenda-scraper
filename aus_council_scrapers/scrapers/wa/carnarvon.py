import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.wa.councilconnect_tidy import (
    WATidyCouncilConnectScraper,
)

# A Downloads group holding the agenda under the bare meeting code: "OCM May
# 2025 - FINAL" beside "OCM May 2025 - Schedules - FINAL" and the minutes.
_BARE_AGENDA = re.compile(r"^\s*(?:OCM|SCM)\b", re.IGNORECASE)
_NOT_BARE_AGENDA = re.compile(r"minut|schedul|attach|notes|forum", re.IGNORECASE)

# Since 2026 every label opens with the meeting's date written with dots:
# "2026.09.22 - Agenda & Schedules - OCM". The base reads a label that opens
# with dotted numbers as an item number ("13.7 Attachment 1 ...") and drops
# it, which threw away every 2026 agenda and set of minutes but two.
_LEADING_DOTTED_DATE = re.compile(r"^\s*\d{4}\.\d{1,2}\.\d{1,2}\s*-?\s*")


@register_scraper
class CarnarvonScraper(WATidyCouncilConnectScraper):
    """Shire of Carnarvon—documents on each meeting's own page.

    Council meetings and the one planning body the Shire files here. A year
    runs to 50–60 meetings: Agenda Forums and Briefings (councillor
    run-throughs of the coming agenda, not decisions), the audit, major
    projects, awards and community growth fund committees, community
    meetings. Each costs a request. Ordinary and Special Council meetings,
    through their own year pages, were 21 meetings in 2025.

    The Regional Joint Development Assessment Panel type holds one meeting
    (4 January 2024, a DA for Coral Bay) and is read because a JDAP decides
    development applications. It costs one empty listing request a year.

    An Ordinary meeting page also carries "AFM Notes", the agenda forum's
    notes, which name neither agenda nor minutes and are never picked.
    """

    meeting_types = {
        "ordinary-meeting-of-council": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
        "regional-joint-development-assessment-panel": (
            "Regional Joint Development Assessment Panel"
        ),
    }

    name_by_type = True

    # One production year, measured 20 Oct 2026 from a home IP: 37 s for
    # 18 requests. Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 37

    def __init__(self):
        super().__init__("carnarvon", "WA", "https://www.carnarvon.wa.gov.au")

    def _pick_documents(self, links):
        links = [
            (group, _LEADING_DOTTED_DATE.sub("", label), url)
            for group, label, url in links
        ]
        agenda_url, minutes_url = super()._pick_documents(links)
        if agenda_url is None:
            # Only from a group that is not the minutes': the 17 and 24
            # September 2020 Special meetings have one paper each, "SCM - 17
            # - September - 2020" under "Minutes", and it is their minutes.
            bare = [
                url
                for group, label, url in links
                if url.lower().endswith(".pdf")
                and url != minutes_url
                and not re.search(r"minut", group or "", re.IGNORECASE)
                and _BARE_AGENDA.search(label)
                and not _NOT_BARE_AGENDA.search(label)
            ]
            if len(bare) == 1:
                agenda_url = bare[0]
        return agenda_url, minutes_url
