import datetime
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.coonambleshire.nsw.gov.au"
# The current year's papers are on the meetings page; 2023 to last year are on
# one "Previous Years" page. Nothing earlier is online.
_CURRENT_URL = _BASE_URL + "/council/council-meetings"
_PREVIOUS_URL = _BASE_URL + "/council/previous-years"

# Each paper is a one-row table whose only cell is a link labelled
# "<n>. <paper> - <type> Meeting <month> <year>": "1. Business Paper -
# Ordinary Meeting February 2026", "2. DRAFT Minutes - Ordinary Meeting July
# 2026", "7. Draft Meeting Minutes - Extra-ordinary Meeting October 2025".
# Annexures and supplementary reports share the shape and are skipped.
_LABEL = re.compile(
    r"^\s*\d+\.\s*(?P<paper>.+?)\s+-\s+(?P<type>extra[\s-]*ordinary|ordinary)\s+meeting\s+"
    r"(?:(?P<day>\d{1,2})\s+)?(?P<month>[a-z]+)\s+(?P<year>\d{4})",
    re.IGNORECASE,
)
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

# The labels give only the month. The day is taken from a document's file
# name when the name carries a whole date, and only one that falls in the
# labelled month counts. Forms seen: "2026.03.11 ...", "2025-03-12_...",
# "CO_20260211_MIN_...", "...-20251017.pdf", "... 15 April 2026.PDF".
_DOTTED = re.compile(r"(?<!\d)(20\d{2})[.-](\d{2})[.-](\d{2})(?!\d)")
_YYYYMMDD = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")
_WORDED = re.compile(
    r"(?<!\d)(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(20\d{2})",
    re.IGNORECASE,
)
# A six-digit "yymmdd_" prefix is the older upload naming. On business papers
# it is the meeting date—checked against the papers' cover pages—but on
# minutes it is not: the June 2025 minutes are "250611_..." for a meeting
# held on 18 June, the April 2025 minutes "250509_..." for 9 April. So it is
# read from business papers only.
_YYMMDD_PREFIX = re.compile(r"^(\d{2})(\d{2})(\d{2})_")

# Business papers whose label and file name give only the month. Each date
# was read off the paper's own cover ("Date: Wednesday, 10 December 2025")
# on 20 Oct 2026. Without these the six meetings would be left out, since
# the day is printed nowhere else the site publishes. Reading covers live
# needs a fetcher method that returns bytes and records them in cassettes;
# `fetch_with_requests` returns decoded text, which mangles a PDF. Until that
# exists, a new undated paper is still left out with a warning, and its date
# can be added here once checked.
_COVER_DATES = {
    "ordinary business paper january 26.pdf": datetime.date(2026, 1, 22),
    "ordinary business paper may 2025.pdf": datetime.date(2025, 5, 15),
    "ordinary business paper september 2025.pdf": datetime.date(2025, 9, 10),
    "ordinary business paper - october 2025.pdf": datetime.date(2025, 10, 8),
    "november ordinary business paper 2025.pdf": datetime.date(2025, 11, 12),
    "december ordinary business paper 2025.pdf": datetime.date(2025, 12, 10),
}


@dataclass
class _Paper:
    kind: str  # "agenda" or "minutes"
    type: str  # "Ordinary" or "Extraordinary"
    year: int
    month: int
    day: Optional[int]
    url: str
    page: str


def _dates_in_name(url: str, trust_prefix: bool) -> list[datetime.date]:
    name = unquote(url.rsplit("/", 1)[-1])
    candidates = []
    candidates += [(int(y), int(m), int(d)) for y, m, d in _DOTTED.findall(name)]
    candidates += [(int(y), int(m), int(d)) for y, m, d in _YYYYMMDD.findall(name)]
    candidates += [
        (int(y), _MONTHS.index(m[:3].lower()) + 1, int(d))
        for d, m, y in _WORDED.findall(name)
    ]
    if trust_prefix:
        prefix = _YYMMDD_PREFIX.match(name)
        if prefix:
            yy, mm, dd = prefix.groups()
            candidates.append((2000 + int(yy), int(mm), int(dd)))
    found = []
    for y, m, d in candidates:
        try:
            found.append(datetime.date(y, m, d))
        except ValueError:
            pass
    return found


@register_scraper
class CoonambleScraper(BaseScraper):
    def __init__(self):
        super().__init__("coonamble", "NSW", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _papers(self, html: str, page_url: str) -> list[_Paper]:
        soup = BeautifulSoup(html, "html.parser")
        papers = []
        for link in soup.find_all("a", href=True):
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            match = _LABEL.match(label)
            if not match:
                continue
            paper = match.group("paper").lower()
            if "minutes" in paper:
                kind = "minutes"
            elif "business paper" in paper and "supplementary" not in paper:
                kind = "agenda"
            else:
                continue  # annexures, supplementary reports
            month_word = match.group("month")[:3].lower()
            if month_word not in _MONTHS:
                continue
            month = _MONTHS.index(month_word) + 1
            year = int(match.group("year"))
            href = link["href"].strip()
            if unquote(href).lower().startswith("javascript"):
                # Several 2023 papers are wrapped in an outer
                # `<a href="javascript%3A">` whose text is the paper's label.
                continue
            url = urljoin(page_url, href)

            day = int(match.group("day")) if match.group("day") else None
            if day is None:
                in_month = {
                    d.day
                    for d in _dates_in_name(url, trust_prefix=kind == "agenda")
                    if (d.year, d.month) == (year, month)
                }
                if len(in_month) == 1:
                    day = in_month.pop()
            if day is None and kind == "agenda":
                cover = _COVER_DATES.get(unquote(url.rsplit("/", 1)[-1]).lower())
                if cover and (cover.year, cover.month) == (year, month):
                    day = cover.day
            papers.append(
                _Paper(
                    kind=kind,
                    type=(
                        "Ordinary"
                        if match.group("type").lower() == "ordinary"
                        else "Extraordinary"
                    ),
                    year=year,
                    month=month,
                    day=day,
                    url=url,
                    page=page_url,
                )
            )
        return papers

    def _meetings(self, papers: list[_Paper]) -> list[ScraperReturn]:
        # Group by meeting type and month, then pair within the group by day.
        # October 2025 held two extraordinary meetings, so a month can hold
        # more than one meeting of a type.
        groups: dict[tuple, list[_Paper]] = {}
        for paper in papers:
            groups.setdefault((paper.type, paper.year, paper.month), []).append(paper)

        results = []
        for (meeting_type, year, month), group in groups.items():
            meetings = [
                {"day": p.day, "agenda": p.url, "minutes": None, "page": p.page}
                for p in group
                if p.kind == "agenda"
            ]
            for minutes in (p for p in group if p.kind == "minutes"):
                target = next(
                    (m for m in meetings if minutes.day and m["day"] == minutes.day),
                    None,
                )
                undated = [m for m in meetings if m["day"] is None]
                if target is None and minutes.day and len(undated) == 1:
                    # The February 2026 business paper's name has no date;
                    # its minutes are "CO_20260211_MIN_3228.pdf".
                    target = undated[0]
                    target["day"] = minutes.day
                if target is None and not minutes.day and len(meetings) == 1:
                    target = meetings[0]
                if target is None:
                    if minutes.day:
                        meetings.append(
                            {
                                "day": minutes.day,
                                "agenda": None,
                                "minutes": minutes.url,
                                "page": minutes.page,
                            }
                        )
                    continue
                if target["minutes"] is None:
                    target["minutes"] = minutes.url

            for m in meetings:
                if m["minutes"] is None and m["agenda"] is None:
                    continue
                if m["day"] is None:
                    # Never guess the day: the labels give only the month.
                    self.logger.warning(
                        f"{self.council_name}: {meeting_type} meeting of "
                        f"{datetime.date(year, month, 1):%B %Y} left out—no paper "
                        f"names its day ({m['agenda'] or m['minutes']})"
                    )
                    continue
                date = datetime.date(year, month, m["day"])
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
        return results

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        pages = [_CURRENT_URL]
        if min(wanted) < clock.current_year():
            pages.append(_PREVIOUS_URL)

        papers = []
        for page in pages:
            html = self.fetcher.fetch_with_requests(page)
            found = self._papers(html, page)
            if not found:
                # Both pages always carry papers; none means the layout moved.
                raise ValueError(f"{self.council_name}: no meeting papers on {page}")
            papers.extend(found)

        # A paper sits on one page only, but drop repeats in case a year is
        # on both while the council moves it across.
        seen = set()
        unique = []
        for p in papers:
            if p.year in wanted and p.url not in seen:
                seen.add(p.url)
                unique.append(p)

        results = self._meetings(unique)
        results.sort(key=lambda r: r.date, reverse=True)
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
