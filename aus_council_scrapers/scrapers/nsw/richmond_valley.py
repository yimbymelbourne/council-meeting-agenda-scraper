"""Richmond Valley Council (NSW).

The council keeps a WordPress page per year, linked from the council-meetings
index as "<year> Agendas and Minutes". Each holds a table with one row per
meeting: a date cell ("Tuesday 18 August | Ordinary Meeting"), then Agenda,
Attachments, Minutes, Video, Pre-Meeting Questions and Additional Documents
columns. The papers are InfoCouncil exports (`CO_20260818_AGN_3321_AT.pdf`)
or hand-named uploads, all self-hosted under `/wp-content/uploads/`.

Production asks for one year, which is two requests: the index and that
year's page.

Do not use the hosted platforms a probe turns up for "richmond": Resolve's
`richmond` tenant is Richmond Shire (QLD) and eScribe's `pub-richmond` is
Richmond, California.
"""

from __future__ import annotations

import datetime
import re
import urllib.parse
from typing import Optional

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_INDEX_URL = "https://richmondvalley.nsw.gov.au/council/council-meetings/"

# Read the year off the link label, not the slug: 2016-2018 live at
# `/<year>-meeting-minutes/` and the rest at `/<year>-agendas-and-minutes/`.
_YEAR_LINK = re.compile(r"^\s*(\d{4})\s+Agendas and Minutes\s*$", re.IGNORECASE)

_MONTHS = {
    name: number
    for number, name in enumerate(
        (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ),
        start=1,
    )
}
_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

# "Tuesday 18 August | Ordinary Meeting", "Tuesday 20 August 2024 | Ordinary
# Meeting", "Tuesday 15 September – Ordinary Meeting", "Tuesday 20 February
# 2024 Ordinary meeting", or just "Tuesday 20 October" for a meeting whose
# type has not been typed in yet. The year is optional: most pages leave it
# off and the page itself says which year it is.
_DATE_CELL = re.compile(
    r"^\s*(?:(?P<weekday>[A-Za-z]+day)\s+)?(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]+)"
    r"(?:\s+(?P<year>\d{4}))?\s*(?:[|–—-]\s*)?(?P<rest>.*)$"
)

# Dates the council put in a filename: "...-15-April-2025.pdf" or the
# InfoCouncil "CO_20250415_AGN_...". Only consulted when the row's weekday
# disagrees with its own day, which happens: the 2025 page lists "Tuesday 14
# April" for the meeting held on Tuesday 15 April, and its agenda and minutes
# are both filed under 15 April.
_FILE_WORD_DATE = re.compile(r"(\d{1,2})[-_ ]([A-Za-z]+)[-_ ](\d{4})")
_FILE_ISO_DATE = re.compile(r"_(20\d{2})(\d{2})(\d{2})_")


def _date_in_filename(url: str) -> Optional[datetime.date]:
    name = urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1])
    match = _FILE_ISO_DATE.search(name)
    if match:
        try:
            return datetime.date(*(int(part) for part in match.groups()))
        except ValueError:
            pass
    match = _FILE_WORD_DATE.search(name)
    if match and match.group(2).lower() in _MONTHS:
        try:
            return datetime.date(
                int(match.group(3)),
                _MONTHS[match.group(2).lower()],
                int(match.group(1)),
            )
        except ValueError:
            pass
    return None


def _repair_encoding(html: str) -> str:
    """Undo requests' Latin-1 guess on a page that is really UTF-8.

    The server sends `content-type: text/html` with no charset, so requests
    decodes the UTF-8 body as ISO-8859-1 and "Tuesday 15 September – Ordinary
    Meeting" arrives with the dash as three junk characters. Re-encoding as
    Latin-1 recovers the original bytes. If the page was decoded properly
    (a charset added later), it holds characters Latin-1 cannot encode, or
    bytes that are not valid UTF-8, and is returned unchanged.
    """
    try:
        return html.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return html


@register_scraper
class RichmondValleyScraper(BaseScraper):
    def __init__(self):
        super().__init__("richmond_valley", "NSW", "https://richmondvalley.nsw.gov.au")

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _year_pages(self) -> dict[int, str]:
        soup = BeautifulSoup(
            _repair_encoding(self.fetcher.fetch_with_requests(_INDEX_URL)),
            "html.parser",
        )
        pages: dict[int, str] = {}
        for link in soup.find_all("a", href=True):
            match = _YEAR_LINK.match(link.get_text(" ", strip=True))
            if match:
                pages.setdefault(
                    int(match.group(1)), urllib.parse.urljoin(_INDEX_URL, link["href"])
                )
        if not pages:
            raise RuntimeError(
                f"{_INDEX_URL} links no '<year> Agendas and Minutes' pages; "
                f"the menu markup has probably changed"
            )
        return pages

    def _meeting_date(self, cell_text: str, page_year: int, urls: list[str]):
        """(date, meeting type) for a row, or None if the cell is not a date."""
        match = _DATE_CELL.match(cell_text)
        if not match or match.group("month").lower() not in _MONTHS:
            return None
        year = int(match.group("year") or page_year)
        try:
            date = datetime.date(
                year, _MONTHS[match.group("month").lower()], int(match.group("day"))
            )
        except ValueError:
            return None

        weekday = (match.group("weekday") or "").lower()
        if weekday in _WEEKDAYS and _WEEKDAYS[date.weekday()] != weekday:
            # The weekday and the day disagree, so one of them is a typo. A
            # date the papers themselves carry, a few days away and on the
            # stated weekday, settles which.
            for url in urls:
                filed = _date_in_filename(url)
                if (
                    filed
                    and abs((filed - date).days) <= 7
                    and _WEEKDAYS[filed.weekday()] == weekday
                ):
                    self.logger.info(
                        f"{cell_text!r}: {date} is not a {weekday}; using {filed} "
                        f"from {url.rsplit('/', 1)[-1]}"
                    )
                    date = filed
                    break
            else:
                self.logger.warning(
                    f"{cell_text!r}: {date} is not a {weekday} and no paper says "
                    f"otherwise; keeping the date as written"
                )

        rest = match.group("rest").strip(" |–—-")
        if not rest:
            name = "Council Meeting"
        else:
            # Typed by hand: "Ordinary meeting" and "Ordinary Meeting" both occur.
            name = " ".join(word[:1].upper() + word[1:] for word in rest.split())
        return date, name

    def _meetings_on_page(
        self, html: str, page_url: str, page_year: int
    ) -> list[ScraperReturn]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[ScraperReturn] = []
        # The current year's page repeats the next meeting in a table of its
        # own above the full list, so the same row arrives twice.
        seen: set[tuple] = set()

        for table in soup.select("table.meeting-table"):
            rows = table.find_all("tr")
            if not rows:
                continue
            headers = [
                cell.get_text(" ", strip=True).lower()
                for cell in rows[0].find_all(["th", "td"])
            ]

            for row in rows[1:]:
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue
                papers: dict[str, str] = {}
                for header, cell in zip(headers, cells):
                    # Columns, not link text, say what a link is: the
                    # Attachments, Video and Additional Documents columns
                    # never hold the agenda or the minutes.
                    if header not in ("agenda", "minutes"):
                        continue
                    link = cell.find("a", href=True)
                    if link:
                        papers[header] = urllib.parse.urljoin(
                            page_url, link["href"].strip()
                        )

                if not papers:
                    continue
                parsed = self._meeting_date(
                    re.sub(r"\s+", " ", cells[0].get_text(" ", strip=True)),
                    page_year,
                    list(papers.values()),
                )
                if parsed is None:
                    self.logger.warning(
                        f"{page_url}: no date in row {cells[0].get_text(' ', strip=True)!r}"
                    )
                    continue
                date, name = parsed

                key = (date, papers.get("agenda"), papers.get("minutes"))
                if key in seen:
                    continue
                seen.add(key)

                agenda_url = papers.get("agenda")
                minutes_url = papers.get("minutes")
                results.append(
                    ScraperReturn(
                        name=name,
                        date=date.isoformat(),
                        time=None,
                        webpage_url=page_url,
                        agenda_url=agenda_url,
                        minutes_url=minutes_url,
                        download_url=agenda_url or minutes_url,
                    )
                )
        return results

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        pages = self._year_pages()

        results: list[ScraperReturn] = []
        for year in sorted(wanted & set(pages)):
            # A failed year page raises: in a one-year production run it is
            # the only page, and returning [] would read as a quiet council.
            html = _repair_encoding(self.fetcher.fetch_with_requests(pages[year]))
            found = [
                meeting
                for meeting in self._meetings_on_page(html, pages[year], year)
                if int(meeting.date[:4]) in wanted
            ]
            if not found:
                self.logger.warning(f"{pages[year]} listed no meetings with papers")
            results.extend(found)

        missing = sorted(
            year for year in wanted - set(pages) if year <= clock.current_year()
        )
        if missing:
            # Normal for a new year before its first meeting (the page is
            # added in January or February); anything else means the index
            # has stopped linking a year it used to.
            self.logger.warning(f"No year page linked for {missing}")
            if not results and clock.today() > datetime.date(max(missing), 3, 31):
                raise RuntimeError(
                    f"{self.council_name}: no year page for {missing} and nothing "
                    f"else to return; the index markup has probably changed"
                )

        if not results and clock.today() - datetime.date(
            min(wanted), 1, 1
        ) > datetime.timedelta(days=90):
            # The year page is linked but its table yielded nothing, which
            # three months into a year means its markup has changed. Returning
            # [] would let a one-year production run report a working council
            # with no meetings.
            raise RuntimeError(
                f"{self.council_name}: no meetings with papers in {sorted(wanted)}; "
                f"the year page markup has probably changed"
            )

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
