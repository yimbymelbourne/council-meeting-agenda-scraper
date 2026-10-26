"""Leeton Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds every meeting: Ordinary,
Extraordinary and Special meetings of the Council, and nothing else, so no
``meeting_types`` filter is needed. The ``dlv_`` year filter was checked
against every year it offers from 2021 to 2026 (October 2026): each returned
only that year's rows. It also offers 2018, which is before
``EARLIEST_YEAR`` and is not read; 2019 and 2020 are not offered at all.

Papers are filed under headings, each paper a "Download PDF" link, so
``papers_by = "heading"``. The headings carry the meeting in them—"Agenda
August 2026 Ordinary Council Meeting", "Agenda- May 2025 ...", "Minutes -
...", "Minutes (confirmed)"—beside "Separate Attachments" and item headings
such as "ITEM 8.2.1 QUARTERLY BUDGET ...", which the start-anchored heading
rules leave alone. From 2022 to 2024 the agenda was usually one file with
its attachments bound in, headed "Agenda and Attachments"—which the base
class takes as the agenda—but five times otherwise: "Agenda &
Attachments" (twice), "Main Agenda & Attachments", "Council Meeting Agenda
and Attachments" and "April 2023 Ordinary Council Meeting - Agenda &
Attachments". `papers` rewrites those to the plain form first, so they are
not passed over as attachment books. In September 2025 the agenda is four
files, "Agenda (Part 1)" to "(Part 4)"; Part 1 is reported.

There is no separate upcoming list. On 20 October 2026 the newest row was
the 29 September 2026 meeting, so a meeting seems to be listed only once
its papers are posted.

``page_size`` and ``year_filtered_first_page`` were both checked (October
2026): a ``(pagesize=50)`` page held all 13 of 2025's rows, and the filtered
page carries the full year dropdown. So a production year is one listing
request plus one payload per meeting.

Six 2025 meetings (25 February to 29 July) carry a payload time of "06:30
AM". Their agendas say 6:30 pm (10 June and 29 July checked), so the
payload flipped AM and PM and that time is dropped. The 7:00 AM (1 July
2024) and 7:30 AM (3 October 2025) Extraordinary meetings are real: their
agendas say the same. From April 2026 the payload gives 6:00 PM, which is
the public forum's start; the agenda puts the meeting itself at 6:30 pm.
That is the time the council published for the event, so it is kept.

robots.txt disallows a few per-meeting pages under this listing (the 27 April
2022 meeting's), none of which the scraper requests: it reads the listing and
the ``OCServiceHandler.axd`` payloads only.
"""

import re

from bs4 import BeautifulSoup

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.opencities import ListingRow, OpenCitiesMeetingsScraper

# The agenda with attachments bound in, under one of the headings the base
# class does not recognise as that: "&" for "and", or the meeting named
# first. A body prefix of any other kind ("Additional Agenda and
# Attachments", "Item 7.2 - Supplementary Agenda & Attachments") is a second
# paper and is left as it is.
_BOUND_AGENDA = re.compile(
    r"^(?:main\s+|council\s+meeting\s+|.*\bmeeting\s*-\s*)?"
    r"agenda\s*(?:&|and)\s*attachments$",
    re.IGNORECASE,
)


@register_scraper
class LeetonScraper(OpenCitiesMeetingsScraper):
    # One production year (2026), measured 20 Oct 2026 from a home IP: 9
    # requests (one listing page and 8 payloads), 17 s. Orders dispatch only
    # (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 17

    list_name = "OC CL Public Meetings"
    papers_by = "heading"
    page_size = 100
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "leeton",
            "NSW",
            "https://www.leeton.nsw.gov.au/Your-Council/About-Council/"
            "Council-Meetings/Minutes-and-Agendas",
        )

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        for heading in content.select("div.meeting-document > h3"):
            if _BOUND_AGENDA.match(heading.get_text(" ", strip=True)):
                heading.string = "Agenda and Attachments"
        return super().papers(content)

    def build_return(
        self, content: BeautifulSoup, row: ListingRow
    ) -> ScraperReturn | None:
        record = super().build_return(content, row)
        # "06:30 AM" is an AM/PM slip on six 2025 meetings (see the module
        # docstring). Reporting it would claim a dawn meeting nobody held,
        # and correcting it would put our guess in the council's data, so
        # the record carries no time.
        if record is not None and record.time == "06:30 AM":
            record.time = None
        return record
