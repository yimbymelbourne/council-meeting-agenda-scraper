"""Lake Macquarie City Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds every meeting from 2016 with a
year filter: Ordinary and Extraordinary meetings of Council, and a
"Standing Committee Meeting" row for the evening the standing committees
sit. All of them are meetings of the whole Council, so nothing is filtered
out. Upcoming meetings appear on the same list once their agenda is up.

Papers are in folders (``papers_by = "folder"``): an "Agenda" folder whose
files are titled only by meeting—"Ordinary Meeting", "Information
Meeting", "Amended Agenda", "Supplementary Agenda"—beside "Attachments" and
"Questions on items" folders. The meeting's agenda is the first plainly
titled file. Two kinds of file in the agenda folder are not it:

* the "Information Meeting" (or "Information Report", "Informational
  Meeting") paper, a separate information-only agenda tabled beside most
  ordinary meetings, and
* the odd item's own paper filed loose, coded by report number: "23SD001 -
  Revised Child Safe Policy - External - Version 1" (27 February 2023),
  "Mayoral Minute - 21MM004 - Extraordinary Council Meeting" (9 August
  2021).

Those are dropped before the base class picks (`papers`).

A file named for another meeting is not this one's either. The 14 July 2025
Extraordinary Meeting's only file is ``agenda-extraordinary-council-
meeting-13-october-2025_1.pdf``, whose first page is the 13 October 2025
meeting's agenda (checked 20 October 2026). The council names every paper
for its meeting's date, so a file whose name carries a date in another
month, or the date of another listed meeting, is dropped first
(`_drop_other_meetings_files`); a payload left with nothing is skipped like
any meeting with no papers. A different day in the same month is not
enough, as a typo is likelier than a misfiled paper.

**One standing-committee row is several meetings.** Its agenda folder holds
one agenda per committee—"Development and Planning Standing Committee",
"Organisational Services Standing Committee", "Service Delivery Standing
Committee", "Built and Natural Assets Standing Committee" and, in 2020,
"Planning for the Future Standing Committee"—so the row becomes one record
per committee, named for it (`build_returns`). Titles vary—"Agenda -
Development Planning Standing Committee - 11 July 2022", "Amended Agenda -
Built and Natural Assets Standing Committee"—so the name is the committee's
alone, and "Development Planning" is read as the "Development and
Planning" it is everywhere else. A committee's supplementary agenda or an
attachment ("Supplementary Agenda - Development and Planning Standing
Committee", 8 March 2021; "DP Standing Committee - 22DP008 - Attachment 2")
is not its agenda. Files in that folder not titled for a committee are not
any committee's agenda: 9 March 2020's row also carries "Ordinary Council -
25 May 2020", which belongs to the 25 May meeting and is already on that
row.

**No minutes are published.** Every payload says: "Meeting minutes are
confirmed at Ordinary Council Meetings. Unconfirmed minutes are available
in Ordinary Council Meeting agendas." So every record is agenda-only, by
the council's choice: no payload from 2020 to 2026 has a minutes folder
(checked 20 October 2026).

robots.txt (2,038 lines, almost all old news pages) disallows nothing this
requests: the listing, its ``dlv_`` query, the renderer and ``/files/``.
The site is behind Cloudflare (``cf-ray``); the project's identifying
User-Agent gets 200 from a home IP, and the scout found a generic
"Mozilla/5.0" refused with 403, so the default User-Agent stays.

One production year is 20 requests: the listing filtered to that year at
``page_size`` 50 (19 rows in 2026), then a payload per row.
"""

import dataclasses
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.opencities import (
    ListingRow,
    OpenCitiesMeetingsScraper,
    folder_documents,
)

# "Information Meeting", "Information meeting", "Information Report - 27
# July": the information-only paper, not the meeting's agenda.
_INFORMATION = re.compile(r"\binformation(?:al)?\b", re.IGNORECASE)
# A report number in a title, e.g. "23SD001", "26SP021", "21MM004".
_REPORT_CODE = re.compile(r"\b\d{2}[A-Z]{2,4}\d{3}\b")
# A committee's other papers: "Supplementary Agenda - Development and
# Planning Standing Committee", "DP Standing Committee - 22DP008 - Attachment
# 2 - final three pages".
_NOT_A_COMMITTEE_AGENDA = re.compile(
    r"\b(?:supplementary|attachments?)\b|\b\d{2}[A-Z]{2,4}\d{3}\b", re.IGNORECASE
)
# A committee's agenda: "Development and Planning Standing Committee",
# "Amended Agenda - Built and Natural Assets Standing Committee" (9 November
# 2020), "Agenda - Service Delivery Standing Committee - 14 June 2022".
# The meeting's date in a filename: "...-meeting-13-october-2025_1.pdf".
_FILE_DATE = re.compile(
    r"(?<![0-9])(\d{1,2})-(january|february|march|april|may|june|july|august"
    r"|september|october|november|december)-(\d{4})(?![0-9])",
    re.IGNORECASE,
)
_COMMITTEE = re.compile(
    r"^(?P<amended>amended\s+)?(?:agenda\s*[-–—:]\s*)?"
    r"(?P<name>.*?\bstanding\s+committee)\b",
    re.IGNORECASE,
)


@register_scraper
class LakeMacquarieScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 37 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 37

    list_name = "OC CL Public Meetings"
    papers_by = "folder"
    # The busiest year since 2020 is 25 rows (2020): one listing page a year.
    page_size = 50
    # The year-filtered page offers every year in its dropdown (checked
    # 20 October 2026), so production skips the bare first page.
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "lake_macquarie",
            "NSW",
            "https://www.lakemac.com.au/Our-Council/Council-meetings/Business-papers",
        )

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        for document in content.find_all("div", class_="meeting-document"):
            title = document.find("div", class_="meeting-document-title")
            text = title.get_text(" ", strip=True) if title else ""
            if _INFORMATION.search(text) or _REPORT_CODE.search(text):
                document.decompose()
        return super().papers(content)

    def _drop_other_meetings_files(self, content: BeautifulSoup, row: ListingRow):
        """Remove each file named for another meeting (see the module
        docstring)."""
        try:
            meeting = parse_date(row.date, dayfirst=True).date()
        except (ValueError, OverflowError):
            return
        listed = getattr(self, "_listed_dates", set())
        for document in content.find_all("div", class_="meeting-document"):
            folder = document.find_parent("div", class_="meeting-folder")
            heading = folder.find(class_="folder-title") if folder else None
            if heading is None or heading.get_text(strip=True).lower() != "agenda":
                # Item attachments are named for whatever they report on
                # ("...-financial-statements-30-june-2026.pdf").
                continue
            anchor = document.find("a", href=True)
            if anchor is None:
                continue
            name = urlparse(anchor["href"]).path.rsplit("/", 1)[-1]
            named = set()
            for day, month, year in _FILE_DATE.findall(name):
                try:
                    named.add(parse_date(f"{day} {month} {year}").date())
                except (ValueError, OverflowError):
                    continue
            if (
                named
                and meeting not in named
                and all(
                    (d.year, d.month) != (meeting.year, meeting.month) or d in listed
                    for d in named
                )
            ):
                self.logger.info(
                    f"{row.date} {row.meeting_type}: {name} is named for another meeting"
                )
                document.decompose()

    def build_returns(
        self, content: BeautifulSoup, row: ListingRow
    ) -> list[ScraperReturn]:
        self._drop_other_meetings_files(content, row)
        if not re.search(r"\bstanding\s+committee\b", row.meeting_type, re.IGNORECASE):
            return super().build_returns(content, row)

        # Each committee's agenda, plain before amended, in payload order.
        committees: dict[str, list[tuple[bool, str]]] = {}
        for document in folder_documents(content):
            if document.folder.lower() != "agenda":
                continue
            match = _COMMITTEE.match(document.title)
            if not match or _NOT_A_COMMITTEE_AGENDA.search(document.title):
                continue
            name = re.sub(r"\s+", " ", match.group("name")).strip()
            name = re.sub(
                r"^development\s+planning\b",
                "Development and Planning",
                name,
                flags=re.IGNORECASE,
            )
            committees.setdefault(name, []).append(
                (bool(match.group("amended")), document.href)
            )
        # The row's time and location, which every committee on it shares.
        record = self.build_return(content, row)
        if record is None or not committees:
            return [record] if record else []

        records = []
        for name, files in committees.items():
            href = sorted(files, key=lambda f: f[0])[0][1]
            agenda = urljoin(self.base_url, href)
            records.append(
                dataclasses.replace(
                    record,
                    name=name,
                    agenda_url=agenda,
                    minutes_url=None,
                    download_url=agenda,
                )
            )
        return records
