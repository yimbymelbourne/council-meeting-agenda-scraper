import datetime
import difflib
import re
from typing import Optional
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://bourke.nsw.gov.au"
_LISTING_URL = f"{_BASE_URL}/council/council-meetings/"

# Bourke Shire Council's whole history, 2011 on, is on one WordPress page:
# under "Business Papers, Minutes and Recordings", an accordion per year, each
# holding a TablePress table of Meeting Date | Business Papers | Minutes |
# Video Recordings. Business papers start in 2013; earlier years are
# minutes only. A separate table at the top lists this year's meeting dates
# and times, which is where the time comes from.
#
# The tables are kept by hand:
#
# - The date cell can carry the meeting type after the date ("28 September
#   2026 Extraordinary", "26 September 2011 (Mayoral Election)") and has
#   typos ("16 Deember 2024"), so the month is matched loosely.
# - Rows without a type are named plain "Council Meeting" rather than
#   assumed ordinary: 8 October 2024, a Tuesday after the election, is one
#   of them. Extraordinary meetings the row does not label are recognised by
#   their filenames ("bp20211210_EXTRA.pdf").
# - Since 2024 the papers come out of InfoCouncil, named
#   CO_<meeting date>_AGN|MIN_<id>. That stamp outranks the row: the row
#   "27 June 2026" links CO_20260727_AGN_2226 and CO_20260727_MIN_2226, and
#   the meeting was 27 July (22 June is the row above it). The older
#   bp/min names mix YYMMDD and DDMMYY and are not read.
# - A cell can hold a second paper beside the business paper (late reports,
#   a supplementary agenda, an attachment book) or the confidential minutes
#   beside the minutes ("cmin210726.pdf", "con-min210628.pdf"); the first
#   plain one is the paper.
# Untyped rows that are not council meetings at all, named from their minutes
# cover. The 14 March 2023 row (bp230314.pdf, min230314.pdf) is headed
# "MINUTES North Bourke Water Extension Request Committee 14 March 2023".
_NAMES_BY_DATE = {
    datetime.date(2023, 3, 14): "North Bourke Water Extension Request Committee",
}

_ROW_DATE = re.compile(r"^\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\s*(.*)$")
_MONTHS = [datetime.date(2000, m, 1).strftime("%B").lower() for m in range(1, 13)]
_CO_STAMP = re.compile(r"(?:^|/)CO_(\d{8})_(?:AGN|MIN)_", re.IGNORECASE)
_NOT_THE_AGENDA = re.compile(r"late|_sup|_att|budget-review", re.IGNORECASE)
_NOT_THE_MINUTES = re.compile(r"^(?:c|con-)min", re.IGNORECASE)
_EXTRA = re.compile(r"extra", re.IGNORECASE)


def _filename(url: str) -> str:
    return unquote(urlparse(url).path.rsplit("/", 1)[-1])


def _parse_row_date(text: str) -> Optional[tuple[datetime.date, str]]:
    match = _ROW_DATE.match(text)
    if not match:
        return None
    day, month_word, year, rest = match.groups()
    month_word = month_word.lower()
    if month_word in _MONTHS:
        month = _MONTHS.index(month_word) + 1
    else:
        close = difflib.get_close_matches(month_word, _MONTHS, n=1, cutoff=0.75)
        if not close:
            return None
        month = _MONTHS.index(close[0]) + 1
    try:
        return datetime.date(int(year), month, int(day)), rest.strip(" ()")
    except ValueError:
        return None


def _co_date(url: str) -> Optional[datetime.date]:
    match = _CO_STAMP.search(urlparse(url).path)
    if not match:
        return None
    try:
        return datetime.datetime.strptime(match[1], "%Y%m%d").date()
    except ValueError:
        return None


@register_scraper
class BourkeScraper(BaseScraper):
    def __init__(self):
        super().__init__("bourke", "NSW", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(_LISTING_URL), "html.parser")

        tables = soup.select("table.tablepress")
        if not tables:
            raise RuntimeError(f"{self.council_name}: no tables at {_LISTING_URL}")

        times: dict[datetime.date, str] = {}
        paper_tables: list[tuple[Tag, list[str]]] = []
        for table in tables:
            headers = [th.get_text(" ", strip=True).lower() for th in table.select("thead th")]
            if "meeting time" in headers:
                self._read_times(table, headers, times)
            elif "minutes" in headers:
                paper_tables.append((table, headers))

        if not paper_tables:
            raise RuntimeError(
                f"{self.council_name}: no business paper tables at {_LISTING_URL}"
            )

        results: list[ScraperReturn] = []
        for table, headers in paper_tables:
            for row in table.select("tbody tr"):
                record = self._row(row, headers, wanted)
                if record is not None:
                    record.time = times.get(datetime.date.fromisoformat(record.date))
                    results.append(record)

        if not results:
            self.logger.warning(
                f"{self.council_name}: no meetings with papers for {sorted(wanted)} "
                f"at {_LISTING_URL}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results

    def _read_times(self, table: Tag, headers: list[str], times: dict) -> None:
        date_col = headers.index("meeting date") if "meeting date" in headers else None
        time_col = headers.index("meeting time")
        if date_col is None:
            return
        for row in table.select("tbody tr"):
            cells = row.find_all("td")
            if len(cells) <= max(date_col, time_col):
                continue
            parsed = _parse_row_date(cells[date_col].get_text(" ", strip=True))
            time_text = cells[time_col].get_text(" ", strip=True)
            if parsed and time_text:
                times[parsed[0]] = time_text.replace(".", ":")

    def _column_links(self, cell: Tag) -> list[str]:
        return [
            urljoin(_LISTING_URL, a["href"].strip())
            for a in cell.find_all("a", href=True)
            if urlparse(a["href"]).path.lower().endswith(".pdf")
        ]

    def _row(self, row: Tag, headers: list[str], wanted: set[int]) -> Optional[ScraperReturn]:
        cells = row.find_all("td")
        if not cells:
            return None
        date_text = cells[0].get_text(" ", strip=True)
        parsed = _parse_row_date(date_text)
        if parsed is None:
            self.logger.warning(f"{self.council_name}: unparseable date {date_text!r}")
            return None
        row_date, qualifier = parsed

        agenda_url = minutes_url = None
        for index, cell in enumerate(cells[1:], start=1):
            column = headers[index] if index < len(headers) else ""
            for url in self._column_links(cell):
                name = _filename(url)
                if column == "business papers" and agenda_url is None:
                    if not _NOT_THE_AGENDA.search(name):
                        agenda_url = url
                elif column == "minutes" and minutes_url is None:
                    if not _NOT_THE_MINUTES.match(name):
                        minutes_url = url

        meeting_date = row_date
        stamps = {d for d in (_co_date(u) for u in (agenda_url, minutes_url) if u) if d}
        if len(stamps) == 1:
            stamped = stamps.pop()
            if stamped != row_date:
                self.logger.warning(
                    f"{self.council_name}: row {date_text!r} links papers stamped "
                    f"{stamped}; dated by the stamp"
                )
                meeting_date = stamped
        elif len(stamps) > 1:
            # Agenda and minutes stamped for different meetings: keep only
            # what agrees with the row.
            if agenda_url and _co_date(agenda_url) not in (None, row_date):
                agenda_url = None
            if minutes_url and _co_date(minutes_url) not in (None, row_date):
                minutes_url = None

        if meeting_date.year not in wanted:
            return None
        if not agenda_url and not minutes_url:
            return None

        if not qualifier and meeting_date in _NAMES_BY_DATE:
            name = _NAMES_BY_DATE[meeting_date]
        elif qualifier:
            kind = qualifier[0].upper() + qualifier[1:]
            name = kind if "meeting" in kind.lower() else f"{kind} Council Meeting"
        elif any(_EXTRA.search(_filename(u)) for u in (agenda_url, minutes_url) if u):
            name = "Extraordinary Council Meeting"
        else:
            name = "Council Meeting"

        return ScraperReturn(
            name=name,
            date=meeting_date.isoformat(),
            time=None,
            webpage_url=_LISTING_URL,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
        )
