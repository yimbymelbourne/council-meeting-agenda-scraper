import datetime
import re
from typing import Optional
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.wagin.wa.gov.au"
# Any page carries the site menu, whose "Meeting Documents" branch links one
# content page per year. The slugs are not regular (`agendas-minutes-2025.aspx`
# but `meetings-2022.aspx`), so they are read off the menu rather than built.
# This page is the menu's "Council Meetings" entry, small and stable.
_INDEX_URL = f"{_BASE_URL}/council/your-council/council-committee-meeting-dates.aspx"
_YEAR_LINK = re.compile(r"^\s*Meetings\s+(\d{4})\s*$", re.IGNORECASE)

_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    )
}
_ROW_DATE = re.compile(r"(\d{1,2})\s+" + _MONTH + r"\s+(\d{4})", re.IGNORECASE)
# A day and month in a file name, with the year if it has one:
# `Agenda_-25_February_2025_-_Public.pdf`, `Agenda_4_August_SCM_for_publishing.pdf`.
_FILE_DAY_MONTH = re.compile(
    r"(?<![\d.])(\d{1,2})[\s_\-]+" + _MONTH + r"(?:[\s_\-]+(\d{4}))?(?![a-z])",
    re.IGNORECASE,
)
_FILE_ISO = re.compile(r"(?<!\d)(20\d\d)[_\-](\d\d)[_\-](\d\d)(?!\d)")
# The row date and the file a link points at sometimes disagree by a day or
# two (a committee row dated 9 September 2023 links minutes filed as 8
# September). Further apart than this, the link may be another meeting's
# paper; see `_drop_misfiled`.
_FILE_DATE_TOLERANCE_DAYS = 3

# Label words that are the document type or upload noise, not the meeting.
_LABEL_NOISE = re.compile(
    r"\(PDF\)|\(?un\s*confirmed\)?|\bconfirmed\b|\bagenda\b|\bminutes?\b|\d+\s*MB\b|\s-\s*$",
    re.IGNORECASE,
)
_BODY_WORDS = re.compile(r"committee|meeting|group|\bagm\b", re.IGNORECASE)

# The labels are free text, so one body is spelt several ways across the
# years. Keyed by the spelling with "&" as "and", "bush fire" as one word
# and the case folded; the value is the one name every year gets, so the
# meetings of a body group together downstream. The Audit Committee became
# the Audit, Risk and Improvement Committee in 2026 (the WA reforms renamed
# every council's), and is kept under the name most of its meetings carry.
_BODY_ALIASES = {
    "audit, risk and improvement committee": "Audit Committee",
    "bushfire advisory group agm": "Bushfire Advisory Annual General Meeting",
    "works and services committee": "Works and Services Committee",
    "finance and general purpose committee": "Finance and General Purposes Committee",
    "sportsground precinct redevelopment committee": (
        "Sportsground Precinct Redevelopment Steering Committee"
    ),
}


def _row_date(text: str) -> Optional[datetime.date]:
    match = _ROW_DATE.search(text)
    if not match:
        return None
    day, month, year = match.groups()
    try:
        return datetime.date(int(year), _MONTHS[month[:3].lower()], int(day))
    except ValueError:
        return None


def _file_date(url: str, year: int) -> Optional[datetime.date]:
    filename = unquote(url.rsplit("/", 1)[-1])
    match = _FILE_ISO.search(filename)
    if match:
        try:
            return datetime.date(*(int(g) for g in match.groups()))
        except ValueError:
            pass
    match = _FILE_DAY_MONTH.search(filename)
    if match:
        day, month, file_year = match.groups()
        try:
            return datetime.date(
                int(file_year or year), _MONTHS[month[:3].lower()], int(day)
            )
        except ValueError:
            return None
    return None


def _committee_name(label: str) -> Optional[str]:
    """The body a committee-table label names.

    "Audit Agenda (PDF)" is the Audit Committee; "Bush Fire Advisory
    Committee - Minutes Unconfirmed" and "Annual Electors Meeting Agenda"
    already say what they are.
    """
    name = label
    for _ in range(3):
        name = _LABEL_NOISE.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip(" -–,")
    if not name:
        return None
    if not _BODY_WORDS.search(name):
        name = f"{name} Committee"
    key = re.sub(r"bush\s+fire", "bushfire", name.replace("&", "and"), flags=re.IGNORECASE)
    key = re.sub(r"\s+", " ", key).lower()
    if key in _BODY_ALIASES:
        return _BODY_ALIASES[key]
    # "Bush Fire Advisory Committee" in 2026, "Bushfire" in other years.
    return re.sub(r"\bBush\s+Fire\b", "Bushfire", name, flags=re.IGNORECASE)


@register_scraper
class WaginScraper(BaseScraper):
    def __init__(self):
        super().__init__("wagin", "WA", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _year_pages(self) -> dict[int, str]:
        html = self.fetcher.fetch_with_requests(_INDEX_URL)
        soup = BeautifulSoup(html, "html.parser")
        pages: dict[int, str] = {}
        for anchor in soup.find_all("a", href=True):
            match = _YEAR_LINK.match(anchor.get_text(" ", strip=True))
            if match and "/meeting-documents/" in anchor["href"]:
                pages.setdefault(int(match.group(1)), urljoin(_BASE_URL, anchor["href"]))
        if not pages:
            # The menu is the only way to the year pages: without it the
            # council would report as having no meetings.
            raise RuntimeError(f"{self.council_name}: no 'Meetings <year>' links in the site menu")
        return pages

    @staticmethod
    def _paper(cell) -> tuple[Optional[str], str]:
        """The cell's main paper and its label.

        A cell lists the agenda or minutes first, then the meeting's item
        reports, attachments, notices of motion and late items, so only the
        first link is the paper itself.
        """
        anchor = cell.find("a", href=True)
        if not anchor:
            return None, ""
        url = urljoin(_BASE_URL, anchor["href"].strip())
        label = anchor.get_text(" ", strip=True)
        if not url.lower().endswith(".pdf"):
            return None, label
        return url, label

    def _drop_misfiled(self, results: list[ScraperReturn]) -> None:
        """Clear a link that is another meeting's paper.

        The 25 July 2023 ordinary meeting's agenda link is the 11 July
        special meeting's agenda, and the 13 February 2024 electors'
        meeting links the 17 December 2024 electors' minutes. A file name
        that merely disagrees with its row is not enough to drop it: the
        14 October 2021 Finance agenda is filed as 19 October, and its first
        page says 14 October. So a link goes only when its file name dates
        it to another row on the page that links the same file, or that is
        a meeting of the same body.
        """
        for record in results:
            date = datetime.date.fromisoformat(record.date)
            for field in ("agenda_url", "minutes_url"):
                url = getattr(record, field)
                file_date = _file_date(url, date.year) if url else None
                if not file_date or abs((file_date - date).days) <= _FILE_DATE_TOLERANCE_DAYS:
                    continue
                owner = any(
                    other is not record
                    and other.date == file_date.isoformat()
                    and (other.name == record.name or url in (other.agenda_url, other.minutes_url))
                    for other in results
                )
                if owner:
                    self.logger.warning(
                        f"{self.council_name}: {url} is the {file_date} paper, "
                        f"not the {date} {record.name}'s; skipped"
                    )
                    setattr(record, field, None)
            record.download_url = record.agenda_url or record.minutes_url

    def _parse_year(self, html: str, page_url: str) -> list[ScraperReturn]:
        soup = BeautifulSoup(html, "html.parser")
        # The first table is the Council's own meetings; the second is its
        # committees, Annual Electors' meetings in some years.
        tables = soup.select("table")
        results = []
        for index, table in enumerate(tables):
            council_table = index == 0
            date: Optional[datetime.date] = None
            for row in table.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) < 3:
                    continue
                # A row with no date is a second meeting the same day (the
                # Annual Electors' meeting after an ordinary meeting).
                date = _row_date(cells[0].get_text(" ", strip=True)) or date
                if not date:
                    continue
                agenda_url, agenda_label = self._paper(cells[1])
                minutes_url, minutes_label = self._paper(cells[2])
                if not (agenda_url or minutes_url):
                    continue
                label = agenda_label or minutes_label
                if re.search(r"annual\s+electors", label, re.IGNORECASE):
                    name = "Annual Electors Meeting"
                elif council_table:
                    # Labelled by month ("February Agenda"), so "Special"
                    # is the only thing that tells the meetings apart.
                    special = re.search(r"special", f"{agenda_label} {minutes_label}", re.IGNORECASE)
                    name = "Special Council Meeting" if special else "Ordinary Council Meeting"
                else:
                    name = _committee_name(label)
                    if not name:
                        continue
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
        self._drop_misfiled(results)
        return [r for r in results if r.agenda_url or r.minutes_url]

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        pages = self._year_pages()

        results = []
        for year in sorted(wanted & set(pages)):
            # Left to raise: a year page that cannot be read would otherwise
            # report that year as having no meetings.
            html = self.fetcher.fetch_with_requests(pages[year])
            results.extend(
                r
                for r in self._parse_year(html, pages[year])
                if int(r.date[:4]) in wanted
            )

        if not results:
            self.logger.warning(
                f"{self.council_name} found no meetings for {sorted(wanted)}; "
                f"year pages listed: {sorted(pages)}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
