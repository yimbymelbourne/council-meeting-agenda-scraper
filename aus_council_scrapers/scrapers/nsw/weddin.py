"""Weddin Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds the Council's Ordinary and
Extraordinary meetings, and nothing else. The ``dlv_`` year filter offers
2018 and 2021–2026; each year checked returned only that year's rows
(October 2026), and 2021's is empty, so the listing starts in 2022.

Papers are filed under headings—"Agenda", "Late Agenda", "Minutes -
Unconfirmed | …", "Minutes - Confirmed | …"—each paper a "Download PDF"
link, so ``papers_by = "heading"``. The late agenda is a second paper and is
never taken as the agenda, and confirmed minutes rank above unconfirmed
ones. `papers` adjusts two headings first:

* "Agenda - Late Report" (20 July, 17 August and 18 May 2023) is the late
  report, not the agenda. Heading mode would rank it beside the plain
  "Agenda" and keep whichever is listed first, which is the real agenda
  today only because of the order; it is renamed so it never counts.
* "Updated Agenda additional item 5.2 (uploaded 23/01/2023 at 6:42PM)" is
  the only agenda the 24 January 2023 Extraordinary Meeting has. It is
  renamed "Agenda (amended)", so it is taken where nothing else is.

A later agenda or minutes replaces the earlier one on the same meeting:

* 20 March 2025 has "Agenda" and "Amended Agenda - Updated as at 18 March
  2025". The amended file was uploaded on 18 March, the plain one on 13
  March.
* 18 May 2023 has "Agenda" (a file named "final_agenda", made on 12 May)
  and "Amended Agenda" (made on 16 May). The two contents pages differ from
  item 5 on.
* 16 November 2023 has "Minutes - Confirmed" and "Minutes - Corrected",
  revised on 22 May 2026.

The base class would report the plain paper each time, and it does not read
a heading that starts "Amended" as an agenda at all. The later paper is the
council's current version, so `papers` makes it the agenda or minutes and
sets the earlier one aside.

A stale 24 January 2022 Extraordinary Meeting row, whose text describes the
24 January 2023 meeting, has no papers and is skipped.

Older minutes (2013–2021) sit on a separate "Archived Minutes" content page,
`/Council/Council-Meetings/Archived-Minutes`, as one "Download Meeting
Minutes (PDF, 3MB)" link per meeting. Those links carry no date, so a
meeting's date could come only from its filename, and several of those name
a month without a day ("minutes-september-2019-no-cc.pdf"). That page is
not read.

Weddin also has a Resolve tenant (``weddin``), which held three meetings in
October 2026 (July to September 2026, one of them unpublished there). The
OpenCities listing has those three with their papers, so it is the record.

``page_size`` and ``year_filtered_first_page`` were checked (October 2026):
a ``(pagesize=50)`` page held all 13 of 2025's rows, and the filtered page
carries the full year dropdown. A production year is one listing request
plus one payload per meeting.
"""

import re

from bs4 import BeautifulSoup

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper

_LATE_REPORT = re.compile(r"^agenda\s*-\s*late\s+reports?\b", re.IGNORECASE)
_UPDATED_AGENDA = re.compile(r"^updated\s+agenda\b", re.IGNORECASE)
_AMENDED_AGENDA = re.compile(r"^amended\s+agenda\b", re.IGNORECASE)
_CORRECTED_MINUTES = re.compile(r"^minutes\s*-\s*corrected\b", re.IGNORECASE)
# The headings a superseding paper replaces: the plain agenda (with or
# without "Final"), and minutes of any status.
_PLAIN_AGENDA = re.compile(r"^(?:final\s+)?agenda\b", re.IGNORECASE)
_ANY_MINUTES = re.compile(r"^minutes\b", re.IGNORECASE)


@register_scraper
class WeddinScraper(OpenCitiesMeetingsScraper):
    # One production year (2026), measured 20 Oct 2026 from a home IP: 11
    # requests (one listing page and 10 payloads), 21 s. Orders dispatch only
    # (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 21

    list_name = "OC CL Public Meetings"
    papers_by = "heading"
    page_size = 100
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "weddin",
            "NSW",
            "https://www.weddin.nsw.gov.au/Council/Council-Meetings/"
            "Agendas-Minutes-for-Council-Meetings",
        )

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        for heading in content.select("div.meeting-document > h3"):
            text = heading.get_text(" ", strip=True)
            if _LATE_REPORT.match(text):
                heading.string = "Late Report - Agenda"
            elif _UPDATED_AGENDA.match(text):
                # The whole heading, not just its first words: the rest
                # ("additional item 5.2") would read as one item's paper.
                heading.string = "Agenda (amended)"
        self._supersede(content, _AMENDED_AGENDA, _PLAIN_AGENDA, "Agenda")
        self._supersede(content, _CORRECTED_MINUTES, _ANY_MINUTES, "Minutes")
        return super().papers(content)

    @staticmethod
    def _supersede(
        content: BeautifulSoup,
        newer: re.Pattern,
        older: re.Pattern,
        paper: str,
    ) -> None:
        """Where a heading matching `newer` exists, make it the plain paper
        and rename the `older` headings beside it so heading mode passes them
        over. Run after the late-report rename, so "Late Report - Agenda"
        is never mistaken for an older agenda here."""
        headings = content.select("div.meeting-document > h3")
        texts = [h.get_text(" ", strip=True) for h in headings]
        if not any(newer.match(text) for text in texts):
            return
        for heading, text in zip(headings, texts):
            if newer.match(text):
                heading.string = paper
            elif older.match(text):
                heading.string = f"Superseded {paper}"
