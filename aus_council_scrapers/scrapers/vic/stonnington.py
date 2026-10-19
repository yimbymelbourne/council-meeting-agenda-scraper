"""City of Stonnington—OpenCities, on `OpenCitiesMeetingsScraper`.

Replaces an empty placeholder stub.

The list is ``CL Public Meetings``—no ``OC`` prefix, unlike every other
council here—and paging inside a filtered year is a plain GET
(``(pageindex=N)``), verified on 2025's three pages.

Rows carry no meeting type at all, and the filter's type select offers only
"Ordinary Meeting", so every record is named "Council Meeting".

Papers are filed under headings, each with one "Download PDF" link, so
``papers_by = "heading"``. Since 2021 the headings are plain "Agenda" and
"Minutes". In 2020 they were prefixed and grew attachments sections:
"Council Agenda", "Council Minutes", "Council Attachments", "Attachments
Council Agenda", "Planning Attachment - Chapel Street South Yarra"; and on 23
November 2020 the one agenda paper was "Council Agenda and Attachments". So
a leading "Council" is dropped before the base class reads the headings,
which then takes "Agenda and Attachments" as the agenda with its attachments
bound in. A heading that *starts* with "Attachments" or "Planning Attachment"
is still not the agenda.

24 October 2022 is one row for two meetings—an unscheduled one at 6:30pm and
the scheduled one at 7pm—with "Agenda for 7:00pm", "Agenda for 6:30pm",
"Unscheduled Council Meeting minutes" and "Scheduled Council meeting
minutes". The papers pair themselves: the unscheduled minutes say "The
meeting commenced at 6:30pm", and the 7pm agenda is the scheduled meeting's.
So that row becomes two records, "Unscheduled Council Meeting" at 6:30pm and
"Council Meeting" at 7pm, each with its own agenda and minutes. The split
applies only to a payload with exactly that shape—two timed agendas, one
unscheduled and one scheduled set of minutes—with the earlier time taken as
the unscheduled meeting, as it was here.

A few 2020 meetings published a paper only as a Word document: 1 June 2020's
agenda and minutes, 15 June 2020's agenda and 20 July 2020's minutes are
"Download DOCX" links. ``agenda_url`` and ``minutes_url`` are PDFs, so those
papers are not reported, and 1 June 2020—left with only attachment books—is
skipped.

About two meetings a month, all Council meetings, so nothing is allowlisted.
One production year is the unfiltered page, the filtered pages and one payload
per meeting: 18 requests and 35 s for 2026, measured in October 2026.
"""

import copy
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.opencities import (
    ListingRow,
    OpenCitiesMeetingsScraper,
    _is_pdf,
    _label,
    _year_of,
)

_COUNCIL_PREFIX = re.compile(r"^\s*council\s+", re.IGNORECASE)
_YEAR_FOLDER = re.compile(r"/council-meetings/(?:archive/)?(20\d\d)/", re.IGNORECASE)
_TIMED_AGENDA = re.compile(
    r"^agenda\s+for\s+(\d{1,2}(?:[:.]\d\d)?\s*[ap]\.?m\.?)$", re.IGNORECASE
)
_UNSCHEDULED_MINUTES = re.compile(r"^unscheduled\b.*\bminutes$", re.IGNORECASE)
_SCHEDULED_MINUTES = re.compile(r"^scheduled\b.*\bminutes$", re.IGNORECASE)


@register_scraper
class StonningtonScraper(OpenCitiesMeetingsScraper):
    list_name = "CL Public Meetings"
    papers_by = "heading"

    def __init__(self):
        super().__init__(
            "stonnington",
            "VIC",
            "https://www.stonnington.vic.gov.au"
            "/About/About-Council/Council-meetings/Minutes-and-agendas",
        )
        self.default_name = "Council Meeting"

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        content = copy.copy(content)
        for section in content.find_all("div", class_="meeting-document"):
            h3 = section.find("h3")
            if h3 is None:
                continue
            h3.string = _COUNCIL_PREFIX.sub("", h3.get_text(" ", strip=True))
        return super().papers(content)

    def build_return(self, content: BeautifulSoup, row: ListingRow):
        record = super().build_return(content, row)
        if record is None:
            return None
        # Stonnington files every paper under a folder for its year
        # (".../council-meetings/2026/14-september-2026/...",
        # ".../archive/2020/17-august-2020/..."), and once filed another
        # meeting's paper under the wrong meeting: 3 February 2020's Agenda
        # heading links ".../archive/2019/1-april/april1agenda.pdf", the
        # agenda of 1 April 2019. A paper from another year's folder is not
        # this meeting's, so it is dropped rather than reported as its agenda.
        year = _year_of(row.date)
        for field in ("agenda_url", "minutes_url"):
            url = getattr(record, field)
            folder = _YEAR_FOLDER.search(urlparse(url).path) if url else None
            if folder and int(folder.group(1)) != year:
                self.logger.warning(
                    f"{row.date}: {field} is filed under {folder.group(1)}, "
                    f"so it is another meeting's paper and is dropped: {url}"
                )
                setattr(record, field, None)
        if not record.agenda_url and not record.minutes_url:
            return None
        record.download_url = record.agenda_url or record.minutes_url
        return record

    def build_returns(
        self, content: BeautifulSoup, row: ListingRow
    ) -> list[ScraperReturn]:
        records = super().build_returns(content, row)
        split = self._two_meetings(content)
        if split is None or len(records) != 1:
            return records
        # The row's own record has already passed the year-folder check and
        # carries the location; each meeting is a copy with its own papers.
        meetings = []
        for name, time, agenda_url, minutes_url in split:
            record = copy.copy(records[0])
            record.name = name
            record.time = time
            record.agenda_url = agenda_url
            record.minutes_url = minutes_url
            record.download_url = agenda_url
            meetings.append(record)
        return meetings

    def _two_meetings(self, content: BeautifulSoup):
        """``[(name, time, agenda, minutes), ...]`` for a row holding an
        unscheduled and a scheduled meeting, or None. See the module
        docstring."""
        timed, unscheduled, scheduled = [], [], []
        for section in content.find_all("div", class_="meeting-document"):
            h3 = section.find("h3")
            link = next(
                (a for a in section.find_all("a", href=True) if _is_pdf(a["href"])),
                None,
            )
            if h3 is None or link is None:
                continue
            heading = _label(h3.get_text(" ", strip=True))
            url = urljoin(self.base_url, link["href"].strip())
            if match := _TIMED_AGENDA.match(heading):
                # Written as the rest of the listing writes times ("07:00 PM").
                start = parse_date(match.group(1)).time()
                timed.append((start, start.strftime("%I:%M %p"), url))
            elif _UNSCHEDULED_MINUTES.match(heading):
                unscheduled.append(url)
            elif _SCHEDULED_MINUTES.match(heading):
                scheduled.append(url)
        if len(timed) != 2 or len(unscheduled) != 1 or len(scheduled) != 1:
            return None
        (_, early, early_agenda), (_, late, late_agenda) = sorted(timed)
        return [
            ("Unscheduled Council Meeting", early, early_agenda, unscheduled[0]),
            (self.default_name, late, late_agenda, scheduled[0]),
        ]
