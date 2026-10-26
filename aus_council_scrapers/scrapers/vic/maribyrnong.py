"""Maribyrnong City Council—OpenCities, on `OpenCitiesMeetingsScraper`.

Replaces a one-meeting stub that had never run (its import was commented out
under the old ``council_scrapers`` package path).

The listing moved to ``/About/Council-Meetings/Agendas-and-minutes``; the
``/About-us/Council-and-committee-meetings/...`` address in docs/councils.md
302s here. One list (``OC CL Public Meetings``) holds every meeting, upcoming
ones included—20 October 2026 was listed with its agenda the day before.
Paging inside a filtered year is a plain GET (``(pageindex=N)``), verified on
2025's three pages; no Go-button postback is needed.

Papers are filed under headings—``<h3>Agenda</h3>``, ``<h3>Minutes</h3>``—
with the main link labelled "Download PDF" (or "Download Agenda" before 2021),
so ``papers_by = "heading"``. The Agenda section can also nest a Related
Information list of item attachments ("Agenda Item 9.1 - Attachment 4",
October 2026); heading mode passes nested lists over, so those are never
taken for the agenda. Minutes are "unconfirmed" or "confirmed" only in the
filename, and either is the meeting's minutes.

The filter lists ten meeting types, and each listed meeting costs a payload
request, so the allowlist below keeps Council meetings (Ordinary and Special)
and the City Development committee—the planning committee, as a Special
Committee to 2020 and a Delegated Committee since. It drops Hearing of
Submissions, the Enterprise Maribyrnong committees, the S223, LeadWest and
Inner Melbourne Action Plan committees: 21 rows since 2020 (8 Hearing of
Submissions, 11 Enterprise Maribyrnong, 2 S223; no LeadWest or IMAP rows),
so 21 payload requests over the history. One production year is the unfiltered page, the filtered pages and
one payload per kept meeting: 13 requests and 24 s for 2026, measured in
October 2026.
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper


@register_scraper
class MaribyrnongScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 19 Oct 2026 from a home IP: 25 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 25

    list_name = "OC CL Public Meetings"
    papers_by = "heading"
    meeting_types = re.compile(
        r"^(?:ordinary|special) council$|^city development", re.IGNORECASE
    )

    def __init__(self):
        super().__init__(
            "maribyrnong",
            "VIC",
            "https://www.maribyrnong.vic.gov.au/About/Council-Meetings/Agendas-and-minutes",
        )
