import datetime
import re
from typing import Optional
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://centralhighlands.tas.gov.au"
_LISTING_URL = f"{_BASE_URL}/meetings-agendas-minutes"

# Central Highlands Council (Tasmania—not Central Highlands Regional Council
# in Queensland, hence the slug). A Craft CMS site whose whole history, from
# the December 2022 AGM, is one page: a table per year, a row per meeting,
# columns Date | Meeting | Agenda | Attachments | Minutes | Audio. The links
# carry no text, only a title, so a link's column says what it is.
#
# Every body on the page is kept—ordinary and special council meetings, the
# AGM, and the Finance and Plant committees—because one request covers them
# all.
#
# The table is kept by hand and the date comes from the first cell, never
# the folder: folders are wrong in places (the April 2025 agenda sits in
# 2026/Apr/). Filenames, though, are checked against the row. A file whose
# name gives a different date or month is a paste from another meeting—the
# December 2024 AGM row's "minutes" are the previous AGM's draft minutes,
# attached to the agenda for confirmation—and is left out.
#
# One row has the wrong year. The 2025 AGM has no row of its own: its papers
# (AGM-Agenda-9-December-2025.pdf, the 2024–2025 annual report) sit on a
# second "Dec 9, 2024" AGM row, and the agenda's cover reads "Tuesday 9th
# December 2025". So when every paper in a row that names a full date names
# the same one, and it is the row's day and month a year either side, the
# meeting is dated by the papers.
#
# The row's own date is sometimes the one that is wrong. Two rows were
# checked against their agenda's cover page and found misdated: "Jun 19,
# 2026" (agenda named 19-June-2026, cover "16th June 2026") and "Sep 16,
# 2025" (cover "23rd September 2025"). In both the attachment book is named
# for the real day ("Attachments-16-June-2026.pdf"), and in every row whose
# date was right the attachments name the same day or none. So an
# attachment book naming a full date within a fortnight of the row's dates
# the meeting, and the row's papers are checked against either day.
#
# As of October 2026 every paper filed before February 2025 (in the
# full-month folders 2025/January, 2024/December and so on) answers HTTP 500
# "An internal server error occurred", as a file that does not exist does.
# They are still linked from the page and are kept as listed.
_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}
_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))
_FULL_DATE = re.compile(rf"\b(\d{{1,2}}) ({_MONTH})\b (\d{{4}}|\d{{2}})(?!\d)")
_MONTH_YEAR = re.compile(rf"\b({_MONTH})\b (\d{{4}})")

_SUPPLEMENTARY = re.compile(r"supplementary|late", re.IGNORECASE)


def _stem_words(url: str) -> str:
    """The filename as lower-case words: "4.1-Council-Minutes-18-March-2025"
    becomes "4 1 council minutes 18 march 2025"."""
    name = unquote(urlparse(url).path.rsplit("/", 1)[-1]).lower()
    name = re.sub(r"\.pdf$", "", name)
    return re.sub(r"[^a-z0-9]+", " ", name).strip()


def _named_date(url: str) -> Optional[datetime.date]:
    """The full date a filename names, if it names one."""
    full = _FULL_DATE.search(_stem_words(url))
    if not full:
        return None
    day, month, year = int(full[1]), _MONTHS[full[2]], int(full[3])
    try:
        return datetime.date(year + 2000 if year < 100 else year, month, day)
    except ValueError:
        return None


def _contradicts(url: str, meeting_date: datetime.date) -> bool:
    """True when the filename names a different date, or month and year,
    from the meeting it is listed against."""
    words = _stem_words(url)
    full = _FULL_DATE.search(words)
    if full:
        day, month, year = int(full[1]), _MONTHS[full[2]], int(full[3])
        if year < 100:
            year += 2000
        return (year, month, day) != (
            meeting_date.year,
            meeting_date.month,
            meeting_date.day,
        )
    month_year = _MONTH_YEAR.search(words)
    if month_year:
        return (int(month_year[2]), _MONTHS[month_year[1]]) != (
            meeting_date.year,
            meeting_date.month,
        )
    return False


def _is_pdf(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


@register_scraper
class CentralHighlandsTasScraper(BaseScraper):
    def __init__(self):
        super().__init__("central_highlands_tas", "TAS", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(_LISTING_URL), "html.parser")

        tables = soup.select("table.table-meeting")
        if not tables:
            raise RuntimeError(
                f"{self.council_name}: no meeting tables at {_LISTING_URL}"
            )

        results: list[ScraperReturn] = []
        for table in tables:
            rows = table.find_all("tr")
            if not rows:
                continue
            headers = [
                c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"])
            ]
            for row in rows[1:]:
                record = self._row(row, headers, wanted)
                if record is not None:
                    results.append(record)

        if not results:
            self.logger.warning(
                f"{self.council_name}: no meetings with papers for {sorted(wanted)} "
                f"at {_LISTING_URL}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results

    def _row(self, row: Tag, headers: list[str], wanted: set[int]) -> Optional[ScraperReturn]:
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            return None
        date_text = cells[0].get_text(" ", strip=True)
        try:
            meeting_date = parse_date(date_text).date()
        except (ValueError, OverflowError):
            self.logger.warning(f"{self.council_name}: unparseable date {date_text!r}")
            return None
        name = re.sub(r"\s+", " ", cells[1].get_text(" ", strip=True))

        row_date = meeting_date
        attachment_dates = {
            _named_date(urljoin(_LISTING_URL, link["href"].strip()))
            for index, cell in enumerate(cells[2:], start=2)
            if index < len(headers) and headers[index] == "attachments"
            for link in cell.find_all("a", href=True)
        } - {None}
        if len(attachment_dates) == 1:
            named = attachment_dates.pop()
            if named != row_date and abs((named - row_date).days) <= 14:
                self.logger.warning(
                    f"{self.council_name}: the {row_date} {name} row's attachments "
                    f"are for {named}; dated by the attachments"
                )
                meeting_date = named
        paper_dates = {
            _named_date(urljoin(_LISTING_URL, link["href"].strip()))
            for index, cell in enumerate(cells[2:], start=2)
            if index < len(headers) and headers[index] in ("agenda", "attachments", "minutes")
            for link in cell.find_all("a", href=True)
        } - {None}
        if len(paper_dates) == 1:
            named = next(iter(paper_dates))
            if (named.month, named.day) == (row_date.month, row_date.day) and abs(
                named.year - row_date.year
            ) == 1:
                self.logger.warning(
                    f"{self.council_name}: the {row_date} {name} row's papers are all "
                    f"for {named}; dated by the papers"
                )
                meeting_date = row_date = named
        if meeting_date.year not in wanted:
            return None

        agenda_url = minutes_url = None
        for index, cell in enumerate(cells[2:], start=2):
            column = headers[index] if index < len(headers) else ""
            if column not in ("agenda", "minutes"):
                continue
            for link in cell.find_all("a", href=True):
                url = urljoin(_LISTING_URL, link["href"].strip())
                words = _stem_words(url)
                if not _is_pdf(url):
                    # The May 2025 agenda cell holds the meeting's mp3.
                    continue
                if column == "agenda" and _SUPPLEMENTARY.search(words):
                    continue
                if column == "minutes" and "minutes" not in words and "agenda" in words:
                    # January 2025's minutes cell links the agenda again.
                    continue
                if _contradicts(url, meeting_date) and _contradicts(url, row_date):
                    self.logger.warning(
                        f"{self.council_name}: {column} on the {meeting_date} "
                        f"{name} row is {url}, which names another date; left out"
                    )
                    continue
                if column == "agenda" and agenda_url is None:
                    agenda_url = url
                elif column == "minutes" and minutes_url is None:
                    minutes_url = url

        if not agenda_url and not minutes_url:
            return None
        return ScraperReturn(
            name=name,
            date=meeting_date.isoformat(),
            time=None,
            webpage_url=_LISTING_URL,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
        )
