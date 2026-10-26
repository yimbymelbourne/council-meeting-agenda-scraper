"""Bathurst Regional Council—OpenCities meetings module from February 2024,
static year pages before it.

**February 2024 on: the meetings module** at /Minutes-and-Agendas, read with
`OpenCitiesMeetingsScraper` (list ``OC CL Public Meetings``, filtered a year
at a time, 100 rows to a page so a year is one listing request). Bathurst
lists a meeting's agenda and its minutes as two rows, each with its own
payload: "Ordinary Meeting of Council - 16 September 2026" and "Ordinary
Meeting of Council - 16 September 2026 - Minutes". In each payload the
first ``div.meeting-document`` is the whole paper—its ``h3`` is the row's
title and its own Download PDF link the paper—and the rest are one PDF per
report item, so only that first link is read, and the heading says whether
it is the agenda or the minutes. The base class then merges the two rows of
one meeting, which share a name and date.

No one field says what a row is. The meeting-type column is blank on some
("02 September 2026"), and says "Ordinary Council Meeting" on some minutes
rows (18 February 2026) and on extraordinary meetings (23 January 2026). The
row's page slug usually names it
(``Extraordinary-Meeting-of-Council-23-January-2026-Minutes``) but in 2024
is sometimes the date alone (``3-April-2024``, a policy meeting). So rows
are chosen and named from the slug, the type and the payload's heading
together. A few meetings have only a minutes row in the module (1 May 2024,
19 and 27 November 2025), so they have no agenda.

**Policy meetings are read.** Bathurst holds a Policy Meeting of Council
(before 2024, the Policy Committee) most months beside its Ordinary Meeting.
It is a meeting of the full council, with its own agenda and minutes in the
same module, so it is reported as "Policy Meeting of Council" (and
"Policy Committee Meeting" in the archive years, as the council labelled
it). Many policy meetings have only a minutes row in the module.

**2020–2023: one page per year** under /Council/Council-Meetings/, linked
from that page. Each meeting is one link, "1 February 2023 - Ordinary
Council Meeting", to a post-meeting booklet: the minutes, with the agenda's
attachments bound in (the 1 February 2023 booklet opens with "AGENDA -
Ordinary Meeting of Council - 1 February 2023 Attachments" and then runs
"MINUTES OF THE ORDINARY MEETING ..."). It does not carry the business paper
itself, so it is reported as the minutes, and those meetings have no
agenda. Where a meeting has separate links instead—19 April 2023 has
"Agenda", five "Attachments Part N" and "Minutes" under a plain-text
heading—they are read as labelled. A file named as an agenda and not as a
post-meeting booklet (13 August 2021) is the agenda. One label carries the
wrong year ("21 June 2024 - Ordinary Council Meeting" on the 2023 page, file
``210623_...``), so the page's year is used.

**18 February 2026 is missing.** Both its rows carry only per-item report
PDFs and a "Download All" zip, with no whole agenda or minutes, so there is
no paper to report and the base class skips them with a warning.

**Cost.** One production year is one listing request plus a payload per
agenda or minutes row: 28 requests and 56 s for 2026 (measured 20 October
2026), over the 20 aimed for. That is the floor while each meeting's
agenda and minutes are two payloads, and the policy meetings are council
meetings, so they are not cut to save requests.
The archive is read only for a wanted year before 2024: the index page plus
that year's page.

Akamai fronts the site (``x-akamai-transformed``), as it does the other
OpenCities councils in production; plain requests got 200 from a home IP.
Akamai does screen clients, though: curl with a browser User-Agent got 403
on the same PDFs that a ``requests`` session fetched as 200 ``%PDF``.
"""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR
from aus_council_scrapers.opencities import (
    ListingRow,
    OpenCitiesMeetingsScraper,
    _is_pdf,
)

_BASE_URL = "https://www.bathurst.nsw.gov.au"
_LISTING_URL = f"{_BASE_URL}/Minutes-and-Agendas"
_ARCHIVE_INDEX_URL = f"{_BASE_URL}/Council/Council-Meetings"
# The council's own index: "Business Papers and Minutes from February 2024 to
# current visit /Minutes-and-Agendas". Earlier years are the static pages.
_MODULE_FROM_YEAR = 2024

_ARCHIVE_LINK = re.compile(
    r"/Council-Meetings/(\d{4})-Council-Business-Paper-and-Minutes"
)

_POLICY = re.compile(r"policy", re.IGNORECASE)
_EXTRAORDINARY = re.compile(r"extra-?\s*ordinary", re.IGNORECASE)
_MINUTES = re.compile(r"\bminutes?\b", re.IGNORECASE)
_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)
_POST_BOOKLET = re.compile(r"post[-_ ]", re.IGNORECASE)

_DATE_TYPE = re.compile(
    r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|September"
    r"|October|November|December)\s+(\d{4})\s*[-–—]\s*(.+)",
    re.IGNORECASE,
)


def _meeting_name(text: str, policy_name: str = "Policy Meeting of Council") -> str:
    if _POLICY.search(text):
        return policy_name
    if _EXTRAORDINARY.search(text):
        return "Extraordinary Council Meeting"
    return "Ordinary Council Meeting"


@register_scraper
class BathurstScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 28 requests,
    # 56 s. Orders dispatch only; see BaseScraper.expected_seconds.
    expected_seconds = 56

    list_name = "OC CL Public Meetings"
    page_size = 100
    year_filtered_first_page = True

    def __init__(self):
        super().__init__("bathurst", "NSW", _LISTING_URL)

    # ------------------------------------------------------------------
    # The meetings module
    # ------------------------------------------------------------------

    @staticmethod
    def _slug(row: ListingRow) -> str:
        return row.detail_url.rsplit("/", 1)[-1].replace("-", " ")

    def _describe(self, row: ListingRow, content: BeautifulSoup | None = None) -> str:
        """Everything that says what a row is: its slug, its type and, once
        fetched, its payload's heading. None of them is complete on its own—
        the 3 April 2024 policy meeting's slug is just "3-April-2024", and
        the 2 September 2026 one has no type."""
        parts = [self._slug(row), row.meeting_type]
        if content is not None:
            document = content.find("div", class_="meeting-document")
            heading = document.find("h3") if document else None
            if heading:
                parts.append(heading.get_text(" ", strip=True))
        return " | ".join(parts)

    def row_papers(self, content: BeautifulSoup, row: ListingRow) -> dict[str, str]:
        document = content.find("div", class_="meeting-document")
        if document is None:
            return {}
        heading = document.find("h3")
        title = heading.get_text(" ", strip=True) if heading else self._slug(row)
        # The paper is the document's own link, not one in the item folder
        # nested inside it.
        anchor = next(
            (
                a
                for a in document.find_all("a", href=True)
                if _is_pdf(a["href"].strip())
                and not a.find_parent("div", class_="meeting-folder")
            ),
            None,
        )
        if anchor is None:
            return {}
        role = "minutes" if _MINUTES.search(title) else "agenda"
        return {role: urljoin(self.base_url, anchor["href"].strip())}

    def meeting_name(self, row, content, papers) -> str:
        return _meeting_name(self._describe(row, content))

    def build_return(self, content: BeautifulSoup, row: ListingRow):
        record = super().build_return(content, row)
        if record is not None:
            # ISO, matching the archive years, and so dateutil never has to
            # guess a day-first order.
            record.date = parse_date(row.date, dayfirst=True).date().isoformat()
        return record

    # ------------------------------------------------------------------
    # The archive years
    # ------------------------------------------------------------------

    def _archive_pages(self) -> dict[int, str]:
        soup = BeautifulSoup(
            self.fetcher.fetch_with_requests(_ARCHIVE_INDEX_URL), "html.parser"
        )
        pages = {}
        for anchor in soup.find_all("a", href=True):
            match = _ARCHIVE_LINK.search(anchor["href"])
            if match:
                pages[int(match.group(1))] = urljoin(_ARCHIVE_INDEX_URL, anchor["href"])
        if not pages:
            raise RuntimeError(
                f"{self.council_name}: no archive year pages on {_ARCHIVE_INDEX_URL}"
            )
        return pages

    def _parse_archive(
        self, html: str, page_url: str, year: int
    ) -> list[ScraperReturn]:
        soup = BeautifulSoup(html, "html.parser")
        meetings: dict = {}
        for panel in soup.find_all("div", class_="oc-wysiwyg-container-panel-content"):
            for anchor in panel.find_all("a", href=True):
                href = anchor["href"].strip()
                if not _is_pdf(href):
                    continue
                info = anchor.find("span", class_="file-info")
                if info:
                    info.extract()
                label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True))
                match = _DATE_TYPE.search(label)
                filename = href.rsplit("/", 1)[-1]
                if match:
                    if _POST_BOOKLET.search(filename) or not _AGENDA.search(filename):
                        role = "minutes"
                    else:
                        role = "agenda"
                else:
                    # A bare "Agenda" or "Minutes" link under a plain-text
                    # heading naming the meeting (19 April 2023).
                    if _MINUTES.search(label):
                        role = "minutes"
                    elif re.fullmatch(r"agenda", label, re.IGNORECASE):
                        role = "agenda"
                    else:
                        continue
                    match = next(
                        (
                            m
                            for m in (
                                _DATE_TYPE.search(s)
                                for s in anchor.find_all_previous(string=True)
                            )
                            if m
                        ),
                        None,
                    )
                    if match is None:
                        continue
                kind = match.group(4)
                day, month = int(match.group(1)), match.group(2)
                date = parse_date(f"{day} {month} {year}").date()
                name = _meeting_name(kind, policy_name="Policy Committee Meeting")
                meeting = meetings.setdefault(
                    (date, name), {"agenda": None, "minutes": None}
                )
                if meeting[role] is None:
                    meeting[role] = urljoin(page_url, href)

        return [
            ScraperReturn(
                name=name,
                date=date.isoformat(),
                time=None,
                webpage_url=page_url,
                agenda_url=papers["agenda"],
                minutes_url=papers["minutes"],
                download_url=papers["agenda"] or papers["minutes"],
            )
            for (date, name), papers in sorted(meetings.items(), reverse=True)
        ]

    def scraper(self) -> list[ScraperReturn]:
        wanted = self._wanted_years()
        results: list[ScraperReturn] = []
        if any(year >= _MODULE_FROM_YEAR for year in wanted):
            results.extend(super().scraper())

        archive_years = {y for y in wanted if EARLIEST_YEAR <= y < _MODULE_FROM_YEAR}
        if archive_years:
            pages = self._archive_pages()
            for year in sorted(archive_years & set(pages), reverse=True):
                html = self.fetcher.fetch_with_requests(pages[year])
                results.extend(self._parse_archive(html, pages[year], year))
        return results
