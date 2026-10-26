import datetime
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://walcha.nsw.gov.au"
_INDEX_URL = _BASE_URL + "/council/agendas-minutes/agendas-business-papers/"

# Business papers and minutes are on separate WordPress pages, both linked
# from the index: business papers by calendar year ("2026 Business Papers",
# one page for "2023-2024"), minutes by financial year ("2025 – 2026 Council
# Meeting Minutes", from 2022-23 only). Their URLs are irregular (/2022-
# business-papers at the site root, /council/agendas-minutes/2023-2024-
# council-meeting-minutes), so they are read off the index. One production
# year is the index, one business-paper page and the two financial-year
# minutes pages it straddles: four requests.
#
# Neither page dates its meetings reliably. Business papers sit under month
# headings ("February 2026") with link text such as "Ordinary Meeting (8MB)";
# minutes links say "Ordinary Meeting Minutes". The date is in the file name
# ("February-2026-Ordinary-Meeting-Business-Paper-25022026-FINAL.pdf",
# "JUL23-Ordinary-Meeting-Minutes-26072023.pdf"), and the file name is
# trusted over the label: "January 2023 ExtraOrdinary Council Meeting" links
# the 19 April 2023 business paper. A paper whose name has no usable date
# (June 2025's business paper, March 2026's minutes "...-2503206-Signed")
# is matched to the one meeting of its type that month.
_MONTHS = [
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
]
_MONTH_WORD = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
_DDMMYYYY = re.compile(r"(?<!\d)(\d{2})(\d{2})(20\d{2})(?!\d)")
_WORDED = re.compile(
    r"(?<!\d)(\d{1,2})[\s_-]+" + _MONTH_WORD + r"[\s_-]+(20\d{2})", re.IGNORECASE
)
# "February-2026-...", "JUL23-...", "May21-...", "FEB24-EO-..."
_MONTH_YEAR = re.compile(
    r"(?<![a-z])" + _MONTH_WORD + r"[\s_-]*(20\d{2}|\d{2})(?!\d)", re.IGNORECASE
)
# Seven 2020 business papers give the month and nothing more, in the file
# name, the link text and the heading. Each date was read off the paper's
# own cover ("To be held on Wednesday, 19 February 2020") on 20 Oct 2026.
# Without these the seven meetings would be left out. A new undated paper is
# still left out with a warning: reading covers live needs a fetcher method
# that returns bytes, which `fetch_with_requests` (decoded text) is not.
_COVER_DATES = {
    "February-2020-Ordinary-Meeting-Business-Paper.pdf": datetime.date(2020, 2, 19),
    "April-2020-Ordinary-Meeting-Business-Paper.pdf": datetime.date(2020, 4, 29),
    "July-2020-Extra-Ordinary-Business-Paper.pdf": datetime.date(2020, 7, 15),
    "July-2020-Ordinary-Meeting-Business-Paper.pdf": datetime.date(2020, 7, 29),
    "August-2020-Ordinary-Meeting-Business-Paper.pdf": datetime.date(2020, 8, 26),
    "September-2020-Ordinary-Business-Paper.pdf": datetime.date(2020, 9, 30),
    "December-2020-Ordinary-Meeting-Business-Paper.pdf": datetime.date(2020, 12, 16),
}
_BP_PAGE = re.compile(
    r"^(20\d{2})(?:\s*[-–]\s*(20\d{2}))?\s+business papers", re.IGNORECASE
)
_MINUTES_PAGE = re.compile(
    r"^(20\d{2})\s*[-–]\s*(20\d{2})\s+council meeting minutes", re.IGNORECASE
)
# Item attachments, appendices, late reports and the "Part 2" of a split
# business paper are not the agenda.
_NOT_AGENDA = re.compile(r"item|att-|attachment|app-|late|part-2", re.IGNORECASE)


@dataclass
class _Paper:
    kind: str
    type: str
    date: Optional[datetime.date]
    year: Optional[int]
    month: Optional[int]
    url: str
    page: str


def _date(day, month, year) -> Optional[datetime.date]:
    try:
        return datetime.date(int(year), int(month), int(day))
    except ValueError:
        return None


def _full_dates(text: str, compact: bool) -> list[datetime.date]:
    found = []
    if compact:
        found += [_date(d, m, y) for d, m, y in _DDMMYYYY.findall(text)]
    found += [
        _date(d, _MONTHS.index(m[:3].lower()) + 1, y)
        for d, m, y in _WORDED.findall(text)
    ]
    return [d for d in found if d]


def _month_year(text: str) -> Optional[tuple[int, int]]:
    match = _MONTH_YEAR.search(text)
    if not match:
        return None
    year = int(match.group(2))
    return (year + 2000 if year < 100 else year), _MONTHS.index(
        match.group(1)[:3].lower()
    ) + 1


@register_scraper
class WalchaScraper(BaseScraper):
    def __init__(self):
        super().__init__("walcha", "NSW", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _content(html: str):
        soup = BeautifulSoup(html, "html.parser")
        return (
            soup.find("div", attrs={"data-elementor-type": "wp-page"})
            or soup.body
            or soup
        )

    def _pages(self, wanted: set[int]) -> tuple[list[str], list[str]]:
        soup = BeautifulSoup(
            self.fetcher.fetch_with_requests(_INDEX_URL), "html.parser"
        )
        papers, minutes = [], []
        for link in soup.find_all("a", href=True):
            text = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            url = urljoin(_INDEX_URL, link["href"].strip())
            bp = _BP_PAGE.match(text)
            if bp:
                first = int(bp.group(1))
                last = int(bp.group(2) or first)
                if wanted & set(range(first, last + 1)) and url not in papers:
                    papers.append(url)
                continue
            fy = _MINUTES_PAGE.match(text)
            if (
                fy
                and wanted & {int(fy.group(1)), int(fy.group(2))}
                and url not in minutes
            ):
                minutes.append(url)
        if not papers and not minutes:
            raise ValueError(
                f"{self.council_name}: no year pages linked from {_INDEX_URL}"
            )
        return papers, minutes

    def _business_papers(self, page: str) -> list[_Paper]:
        content = self._content(self.fetcher.fetch_with_requests(page))
        found = []
        heading = ""
        for element in content.find_all(["h2", "h3", "h4", "strong", "a"]):
            text = re.sub(r"\s+", " ", element.get_text(" ", strip=True))
            if element.name != "a":
                if element.find_parent("a") is None and _month_year(text):
                    heading = text
                continue
            url = urljoin(page, element.get("href", "").strip())
            name = unquote(url.rsplit("/", 1)[-1])
            if "/wp-content/uploads/" not in url or not name.lower().endswith(".pdf"):
                continue
            if not re.search(r"business-paper|agenda", name, re.IGNORECASE):
                continue
            if _NOT_AGENDA.search(name):
                continue
            dates = _full_dates(name, compact=True) or _full_dates(text, compact=False)
            if not dates and not _month_year(name) and not _month_year(text):
                dates = _full_dates(heading, compact=False)
            month_year = _month_year(name) or _month_year(text) or _month_year(heading)
            cover = _COVER_DATES.get(name)
            if not dates and cover and month_year == (cover.year, cover.month):
                dates = [cover]
            found.append(
                _Paper(
                    kind="agenda",
                    type=(
                        "Extraordinary"
                        if re.search(r"extra", f"{name} {text}", re.IGNORECASE)
                        else "Ordinary"
                    ),
                    date=dates[0] if dates else None,
                    year=month_year[0] if month_year else None,
                    month=month_year[1] if month_year else None,
                    url=url,
                    page=page,
                )
            )
        return found

    def _minutes(self, page: str) -> list[_Paper]:
        content = self._content(self.fetcher.fetch_with_requests(page))
        found = []
        for link in content.find_all("a", href=True):
            text = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            url = urljoin(page, link["href"].strip())
            name = unquote(url.rsplit("/", 1)[-1])
            if "/wp-content/uploads/" not in url or "minutes" not in name.lower():
                continue
            dates = _full_dates(name, compact=True) or _full_dates(text, compact=False)
            month_year = _month_year(name) or _month_year(text)
            found.append(
                _Paper(
                    kind="minutes",
                    type=(
                        "Extraordinary"
                        if re.search(r"extra|-EO-", name, re.IGNORECASE)
                        else "Ordinary"
                    ),
                    date=dates[0] if dates else None,
                    year=month_year[0] if month_year else None,
                    month=month_year[1] if month_year else None,
                    url=url,
                    page=page,
                )
            )
        return found

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        paper_pages, minutes_pages = self._pages(wanted)

        papers: list[_Paper] = []
        for page in paper_pages:
            papers += self._business_papers(page)
        for page in minutes_pages:
            papers += self._minutes(page)

        # A file linked twice (the January/April 2023 mix-up, a financial
        # year's July and August repeated on the next year's page) counts once.
        unique: dict[str, _Paper] = {}
        for p in papers:
            unique.setdefault(p.url, p)

        meetings: dict[tuple, dict] = {}
        undated_agendas: list[_Paper] = []
        for p in unique.values():
            if p.kind != "agenda":
                continue
            if p.date is None:
                undated_agendas.append(p)
            else:
                meetings.setdefault(
                    (p.date, p.type), {"agenda": p.url, "minutes": None, "page": p.page}
                )

        def same_month(p: _Paper, pool) -> list:
            return [
                k
                for k in pool
                if (k[0].year, k[0].month, k[1]) == (p.year, p.month, p.type)
            ]

        for p in (p for p in unique.values() if p.kind == "minutes"):
            if p.date is not None:
                key = (p.date, p.type)
                if key not in meetings:
                    undated = [
                        a
                        for a in undated_agendas
                        if (a.year, a.month, a.type)
                        == (p.date.year, p.date.month, p.type)
                    ]
                    if len(undated) == 1:
                        # "June-2025-Ordinary-Meeting-Business-Paper.pdf" is
                        # dated by "June-2025-Ordinary-Meeting-Minutes-25062025.pdf".
                        undated_agendas.remove(undated[0])
                        meetings[key] = {
                            "agenda": undated[0].url,
                            "minutes": None,
                            "page": undated[0].page,
                        }
                    else:
                        meetings[key] = {
                            "agenda": None,
                            "minutes": None,
                            "page": p.page,
                        }
                meetings[key]["minutes"] = meetings[key]["minutes"] or p.url
                continue
            candidates = same_month(p, meetings)
            if len(candidates) == 1 and meetings[candidates[0]]["minutes"] is None:
                meetings[candidates[0]]["minutes"] = p.url
            elif p.year is None or p.year in wanted:
                # A financial-year minutes page also holds the half of the
                # year not asked for, whose business papers were not read;
                # those minutes have nothing to pair with, which is expected.
                self.logger.warning(
                    f"{self.council_name}: cannot date minutes {p.url}; left out"
                )

        for p in (p for p in undated_agendas if p.year is None or p.year in wanted):
            self.logger.warning(
                f"{self.council_name}: no day for business paper {p.url}; left out"
            )

        results = []
        for date, meeting_type in sorted(meetings, reverse=True):
            if date.year not in wanted:
                continue
            m = meetings[(date, meeting_type)]
            results.append(
                ScraperReturn(
                    name=f"{meeting_type} Council Meeting",
                    date=date.isoformat(),
                    time=None,
                    webpage_url=m["page"],
                    agenda_url=m["agenda"],
                    minutes_url=m["minutes"],
                    download_url=m["agenda"] or m["minutes"],
                )
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
