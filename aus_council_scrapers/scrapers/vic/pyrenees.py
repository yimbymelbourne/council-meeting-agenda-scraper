"""Pyrenees Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds Ordinary, Special and Statutory
meetings with a year filter offering 2013, 2014 and 2019 onward; upcoming
meetings appear once their agenda is up (19 October 2026 was listed with
its agenda on 20 October). Those are the only meeting types, so nothing is
filtered out.

Papers are in folders (``papers_by = "folder"``): an "Agenda" folder and a
"Minutes" folder, each file titled "October 2026 Ordinary Meeting Agenda",
"... Agenda Attachments", "March Minutes - Confirmed". The base class takes
the folder's kind and passes over the attachment books.

**The listing's date is wrong for some 2020 meetings.** Its rows say 17
February, 15 June and 20 July 2020; the minutes' own first pages say
"Tuesday 18 February 2020", "Tuesday 9 June 2020" and "Tuesday 21 July
2020", and the agenda files are named ``2020.02.18-``, ``2020.06.09-`` and
``2020.07.21-`` (checked 20 October 2026). Every agenda file is named for its
meeting's date that way, so where the agenda's name carries a date within a
month of the row's, that date is the meeting's (`build_return`). Only the
agenda's: minutes are named for the day they were written up as often as
for the meeting—21 March 2023's are ``2023.03.31-minutes-...-21-march-
2023.pdf``.

The rule has one exception, where the agenda's file is another meeting's
paper. The 13 April 2021 Special Meeting's agenda link is
``2021.04.20-agenda_ordinary_council_meeting.withattmtsv2.pdf``—the
ordinary meeting of a week later—beside its own
``2021.04.13-special-meeting-minutes-public.pdf``. Where the minutes' file
is named for the listed date, the listing is right and the agenda is not
this meeting's, so it is dropped.

Two Statutory Meeting rows (8 November 2022 and 31 October 2023) have no
meeting type, so each is named from its agenda's title (`meeting_name`).

robots.txt disallows a few hundred of the council's own meeting pages
(``/About-Pyrenees-Shire-Council/Council-Meetings/Council-Agenda-and-
Minutes/<meeting>/...``), none of which this requests; the listing, its
``dlv_`` query, the renderer and ``/files/`` are allowed.

One production year is 13 requests: the listing filtered to that year at
``page_size`` 50 (12 rows in 2026), then a payload per meeting.
"""

import datetime
import re

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.opencities import (
    ListingRow,
    OpenCitiesMeetingsScraper,
    folder_documents,
)

# "/2020.06.09-agenda-public-with-attmts.pdf"
_FILE_DATE = re.compile(r"/(\d{4})\.(\d{2})\.(\d{2})-[^/]*$")
_KIND_OF_MEETING = re.compile(
    r"\b(ordinary|special|statutory|extraordinary)\s+meeting\b", re.IGNORECASE
)


@register_scraper
class PyreneesScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 24 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 24

    list_name = "OC CL Public Meetings"
    papers_by = "folder"
    # The busiest year is 15 rows (2025): one listing page a year.
    page_size = 50
    # The year-filtered page offers every year in its dropdown (checked
    # 20 October 2026), so production skips the bare first page.
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "pyrenees",
            "VIC",
            "https://www.pyrenees.vic.gov.au"
            "/About-Pyrenees-Shire-Council/Council-Meetings/Council-Agenda-and-Minutes",
        )

    def meeting_name(
        self, row: ListingRow, content: BeautifulSoup, papers: dict[str, str]
    ) -> str:
        if row.meeting_type:
            return row.meeting_type
        for document in folder_documents(content):
            match = _KIND_OF_MEETING.search(document.title)
            if match:
                return f"{match.group(1).title()} Meeting"
        return self.default_name

    def build_return(
        self, content: BeautifulSoup, row: ListingRow
    ) -> ScraperReturn | None:
        record = super().build_return(content, row)
        if record is None or not record.agenda_url:
            return record
        named = _file_date(record.agenda_url)
        try:
            listed = parse_date(row.date, dayfirst=True).date()
        except (ValueError, OverflowError):
            return record
        if named is None or named == listed or abs((named - listed).days) > 31:
            return record
        if record.minutes_url and _file_date(record.minutes_url) == listed:
            self.logger.info(
                f"{row.date}: the agenda is named for {named:%d %B %Y} and the "
                f"minutes for the listed date, so the agenda is another meeting's"
            )
            record.agenda_url = None
            record.download_url = record.minutes_url
            return record
        self.logger.info(
            f"{row.date}: the agenda is named for {named:%d %B %Y}, "
            f"which is taken as the meeting's date"
        )
        record.date = f"{named:%d %B %Y}"
        return record


def _file_date(url: str) -> datetime.date | None:
    match = _FILE_DATE.search(url)
    if not match:
        return None
    try:
        return datetime.date(*(int(part) for part in match.groups()))
    except ValueError:
        return None
