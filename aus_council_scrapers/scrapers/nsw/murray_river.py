"""Murray River Council—OpenCities from 2021, InfoCouncil before it.

**2021 onwards** is the OpenCities meetings module, on
`OpenCitiesMeetingsScraper`. One list (``OC CL Public Meetings``) holds the
Council's Ordinary and Special meetings and nothing else. The ``dlv_`` year
filter offers 2018 and 2021–2026; each of 2021–2026 returned only its own
rows (October 2026). Papers are filed under headings—"Agenda",
"Attachments Under Separate Cover" / "Attachments", "Unconfirmed Minutes" /
"Minutes"—each paper a "Download PDF" link, so ``papers_by = "heading"``.
One meeting files its papers in a folder inside the heading instead: the 25
August 2026 "Minutes" section holds an "Attachments" folder of two titled
documents, "Councillors Agenda Questions and Answers" first and "Minutes"
second. Heading mode takes a section's first PDF, which would report the
questions as the minutes, so `papers` drops the folder documents whose own
title does not name the heading's paper.

**2020** is on the council's old InfoCouncil site,
``murrayriver.infocouncil.biz``, which the OpenCities filter does not reach
(its 2018 and 2020 filters return no rows). Its ``?year=2020`` page lists
13 Council meetings with agenda and minutes, read with `InfoCouncilScraper`
through this scraper's fetcher, so the requests are recorded and replayed
as Murray River's.

InfoCouncil's **2021** page overlaps OpenCities, and holds one meeting
OpenCities does not: the 16 July 2021 Extraordinary meeting, with agenda
and minutes. So 2021 is read from both, and an InfoCouncil meeting is added
only on a date OpenCities has no meeting for. InfoCouncil is never the
source for a date OpenCities has, because its 2021 grid pairs papers
wrongly: the 19 January 2021 row links the 23 November 2021 minutes.

Both InfoCouncil years are read only when wanted, which production's
one-year run never asks for. Two things differ from InfoCouncil's usual
grid:

* The date cell is ``15/12/2020``, which the stock date pattern does not
  match, so `_InfoCouncilArchive` matches it itself and stores the date as
  ISO. Read month-first, "05/12/2020" would be 12 May.
* InfoCouncil names the committees "Council" and "Extra Council"; they are
  renamed to the OpenCities types for the same meetings, "Ordinary
  Meeting" and "Special Meeting", so a meeting keeps one name across the
  two sources.

The InfoCouncil host is behind Cloudflare (home connections pass; GitHub's
runners are unmeasured), which again matters only for a run asking for
2020 or 2021. Its robots.txt is a 404, which places no restriction.

robots.txt on the council's own site disallows a handful of per-meeting
pages under this listing (``.../27-July-Ordinary-Council-Meeting/Agenda``
and the like); the scraper requests none of them.

``page_size`` and ``year_filtered_first_page`` were checked (October 2026):
a ``(pagesize=50)`` page held all 11 of 2026's rows to date, and the
filtered page carries the full year dropdown. A production year is one
listing request plus one payload per meeting.
"""

import datetime
import re

from bs4 import BeautifulSoup

from aus_council_scrapers.base import (
    InfoCouncilScraper,
    ScraperReturn,
    register_scraper,
)
from aus_council_scrapers.opencities import ListingRow, OpenCitiesMeetingsScraper

_SITE = "https://www.murrayriver.nsw.gov.au"

# The paper a heading names: "Agenda", "Minutes", "Confirmed Minutes". A
# document in a folder under that heading is kept only if its own title
# names the same paper.
_PAPER_WORD = re.compile(r"^(?:\w+\s+)?(agenda|minutes)\b", re.IGNORECASE)

# InfoCouncil's committee names, as OpenCities names the same meetings.
_INFOCOUNCIL_NAMES = {"Council": "Ordinary Meeting", "Extra Council": "Special Meeting"}

# The year only InfoCouncil has; OpenCities starts with 2021.
_INFOCOUNCIL_ONLY = frozenset({2020})
# The year both have, where InfoCouncil only fills OpenCities' gaps.
_INFOCOUNCIL_GAPS = frozenset({2021})


class _InfoCouncilArchive(InfoCouncilScraper):
    """Murray River's InfoCouncil site, read for the years OpenCities lacks."""

    tidy_meeting_rows = True

    def __init__(self):
        super().__init__(
            "murray_river",
            "NSW",
            _SITE,
            "https://murrayriver.infocouncil.biz",
        )
        # "15/12/2020": day first. The year check InfoCouncilScraper makes
        # on it reads the year correctly whichever way round it parses.
        self.date_regex = re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b")

    def scraper(self) -> list[ScraperReturn]:
        records = super().scraper()
        for record in records:
            record.name = _INFOCOUNCIL_NAMES.get(record.name, record.name)
            if record.date:
                record.date = (
                    datetime.datetime.strptime(record.date, "%d/%m/%Y")
                    .date()
                    .isoformat()
                )
        return records


@register_scraper
class MurrayRiverScraper(OpenCitiesMeetingsScraper):
    # One production year (2026), measured 20 Oct 2026 from a home IP: 12
    # requests (one listing page and 11 payloads), 23 s. Orders dispatch only
    # (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 23

    list_name = "OC CL Public Meetings"
    papers_by = "heading"
    page_size = 100
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "murray_river",
            "NSW",
            f"{_SITE}/Council/Council-meetings/Agendas-and-minutes",
        )

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        for section in content.find_all("div", class_="meeting-document"):
            h3 = section.find("h3", recursive=False)
            word = _PAPER_WORD.match(h3.get_text(" ", strip=True)) if h3 else None
            if not word:
                continue
            for title in section.select(
                "div.meeting-folder div.meeting-document-title"
            ):
                if word.group(1).lower() not in title.get_text(" ", strip=True).lower():
                    document = title.find_parent("div", class_="meeting-document")
                    if document is not None and document is not section:
                        document.decompose()
        return super().papers(content)

    def build_return(
        self, content: BeautifulSoup, row: ListingRow
    ) -> ScraperReturn | None:
        record = super().build_return(content, row)
        # The payload's time is "12:00 AM" on three meetings (24 January and 23
        # May 2023, 27 August 2024): a time left unset, not a midnight meeting.
        # Reporting it would claim a time nobody published, so the record
        # carries none, as gosnells does.
        #
        # "10:00 PM" is on two Extraordinary meetings (4 November 2021, 19
        # December 2022), and both agendas' notices say "Time: 10am". The
        # payload flipped AM and PM, so that time is dropped too rather than
        # reported as a meeting held at night. No other meeting in the
        # listing is set at 10 PM.
        if record is not None and record.time in ("12:00 AM", "10:00 PM"):
            record.time = None
        return record

    def scraper(self) -> list[ScraperReturn]:
        wanted = self._wanted_years()
        # OpenCities offers no year before 2021, so a run asking only for
        # 2020 skips it rather than read its dropdown for nothing.
        results = super().scraper() if wanted - _INFOCOUNCIL_ONLY else []
        archive_years = sorted(wanted & (_INFOCOUNCIL_ONLY | _INFOCOUNCIL_GAPS))
        if not archive_years:
            return results

        archive = _InfoCouncilArchive()
        archive.fetcher = self.fetcher
        archive.logger = self.logger
        archive.years_filter = archive_years
        # InfoCouncilScraper raises when every requested year failed, so a
        # blocked InfoCouncil host fails the council rather than returning
        # a quietly short list.
        listed = {record.cleaned_date for record in results}
        for record in archive.scraper():
            if record.cleaned_date.year in _INFOCOUNCIL_ONLY or (
                record.cleaned_date not in listed
            ):
                results.append(record)
        return results
