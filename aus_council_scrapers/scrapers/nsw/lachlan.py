"""Lachlan Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds the Council's meetings. The
``dlv_`` year filter offers 2018 and 2020–2026, and each year checked
(2020–2026, October 2026) returned only that year's rows.

Three meeting types are listed: "Ordinary Meeting", "Extraordinary" and,
from 2026, "Public Briefing". A public briefing is an information session
held before a Council meeting ("The public briefing session will be held on
Wednesday 14 October 2026 from 2.00pm"), whose one paper is a
committee-of-the-whole briefing agenda. It is not a meeting of the Council
that decides anything, and each listed meeting costs a payload request, so
``meeting_types`` keeps the Ordinary and Extraordinary meetings only.

Papers are filed under headings—"Agenda", "Attachments", "Draft Minutes",
"Recording"—each paper a "Download PDF" link, so ``papers_by = "heading"``.

``page_size`` and ``year_filtered_first_page`` were checked (October 2026):
a ``(pagesize=50)`` page held all 13 of 2026's rows to date, and the
filtered page carries the full year dropdown. A production year is one
listing request plus one payload per Council meeting.
"""

import re

from bs4 import BeautifulSoup

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.opencities import ListingRow, OpenCitiesMeetingsScraper


@register_scraper
class LachlanScraper(OpenCitiesMeetingsScraper):
    # One production year (2026), measured 20 Oct 2026 from a home IP: 10
    # requests (one listing page and 9 payloads), 19 s. Orders dispatch only
    # (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 19

    list_name = "OC CL Public Meetings"
    papers_by = "heading"
    page_size = 100
    year_filtered_first_page = True
    meeting_types = re.compile(r"^(?:ordinary|extraordinary)\b", re.IGNORECASE)

    def __init__(self):
        super().__init__(
            "lachlan",
            "NSW",
            "https://www.lachlan.nsw.gov.au/Council/Council-Information/"
            "Council-Meetings/Minutes-and-Agendas",
        )

    def build_return(
        self, content: BeautifulSoup, row: ListingRow
    ) -> ScraperReturn | None:
        record = super().build_return(content, row)
        # The payload's time is "12:00 AM" on four meetings (25 March 2020, 25
        # May, 29 June and 24 August 2022): a time left unset, not a midnight
        # meeting. Reporting it would claim a time nobody published, so the
        # record carries none, as gosnells does.
        if record is not None and record.time == "12:00 AM":
            record.time = None
        return record
