import re
from typing import Optional
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.ballarat.vic.gov.au"

# Ballarat keeps one hand-edited page per year, for Council meetings and,
# since 2023, separately for the Planning Delegated Committee. Each page links
# the PDFs directly. The year pages sit at irregular paths
# ("/2024-agendas-and-minutes", "/city/council-meetings/2023-...",
# ".../planning-delegated-committee" for 2025), so they are read off the
# index pages by their "<year> ... Agendas and Minutes" link text rather
# than built. The current year is linked from the body's own page; earlier
# years only from its archive page, which is fetched only when a past year
# is wanted.
_INDEXES = (
    f"{_BASE_URL}/about-us/council-meetings",
    f"{_BASE_URL}/about-us/council-meetings/planning-delegated-committee-meetings",
)
_YEAR_PAGE_LINK = re.compile(r"^(20\d\d)\b.*agendas\s+and\s+minutes$", re.IGNORECASE)
_ARCHIVE_LINK = re.compile(r"archive", re.IGNORECASE)

# Link text names the document: "25 March 2026 Council Meeting Agenda | Part 1",
# "View July 29 Planning Special Committee Minutes", "View 13 July Planning
# Delegated Committee Agenda Part 1". Before 2025 the year is left off, so it
# comes from the page. The day is given before or after the month.
_MONTHS = (
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
)
_DAY_MONTH = re.compile(rf"\b(\d{{1,2}})\s+({_MONTHS})\b", re.IGNORECASE)
_MONTH_DAY = re.compile(rf"\b({_MONTHS})\s+(\d{{1,2}})\b", re.IGNORECASE)
_YEAR = re.compile(r"\b(20\d\d)\b")
_PART = re.compile(r"part\s*(\d+)", re.IGNORECASE)

_MINUTES = re.compile(r"\bminutes\b", re.IGNORECASE)
_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)
# An embargoed agenda is the late release of the confidential items, and a
# few links carry one report or attachment ("attachments for item 8.12
# missing from agenda", "Item 8.1 Attachment - Annual Report").
_NOT_THE_PAPER = re.compile(
    r"embargoed|\bitem\s+\d|urgent|notice of motion|budget", re.IGNORECASE
)

# Meeting kinds, read from the link text and the filename together, since
# the 2020 links say only "View March 23 agenda" while the file is "23 March
# 2020 Special Meeting Agenda", and the 14 July 2021 links say "Planning
# Committee" while the minutes file says "Planning Delegated Committee". A
# meeting is named after the most specific kind any of its documents gives;
# the list runs from most to least specific. (The Planning Special Committee
# became the Planning Delegated Committee under the Local Government Act
# 2020, so the 9 September 2020 papers use both names.)
_KINDS = (
    (re.compile(r"planning\s+delegated", re.I), "Planning Delegated Committee Meeting"),
    (re.compile(r"planning\s+special", re.I), "Planning Special Committee Meeting"),
    (re.compile(r"planning\s+committe", re.I), "Planning Committee Meeting"),
    (re.compile(r"unscheduled", re.I), "Unscheduled Council Meeting"),
    (re.compile(r"special", re.I), "Special Council Meeting"),
    (re.compile(r"statutory", re.I), "Statutory Council Meeting"),
    (re.compile(r"additional", re.I), "Additional Council Meeting"),
)
_DEFAULT_KIND = "Council Meeting"


def _kind(text: str) -> Optional[str]:
    for pattern, kind in _KINDS:
        if pattern.search(text):
            return kind
    return None


@register_scraper
class BallaratScraper(BaseScraper):
    def __init__(self):
        super().__init__("ballarat", "VIC", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _soup(self, url: str) -> BeautifulSoup:
        html = self.fetcher.fetch_with_requests(url)
        soup = BeautifulSoup(html, "html.parser")
        return soup.find("main") or soup

    def _year_links(self, soup: BeautifulSoup, page_url: str) -> dict[int, str]:
        found = {}
        for link in soup.find_all("a", href=True):
            text = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            match = _YEAR_PAGE_LINK.match(text)
            if match:
                found.setdefault(int(match.group(1)), urljoin(page_url, link["href"]))
        return found

    def _year_pages(self, index_url: str, wanted: set[int]) -> dict[int, str]:
        soup = self._soup(index_url)
        pages = self._year_links(soup, index_url)
        # Years still to come have no page yet; only a missing past year is a
        # reason to read the archive.
        missing_past = {y for y in wanted - pages.keys() if y < clock.current_year()}
        if missing_past:
            archive = next(
                (
                    a
                    for a in soup.find_all("a", href=True)
                    if _ARCHIVE_LINK.search(a.get_text(" ", strip=True))
                ),
                None,
            )
            if archive is None:
                raise ValueError(f"No archive link on {index_url}")
            archive_url = urljoin(index_url, archive["href"])
            for year, url in self._year_links(self._soup(archive_url), archive_url).items():
                pages.setdefault(year, url)
        return {y: u for y, u in pages.items() if y in wanted}

    @staticmethod
    def _date(label: str, page_year: int):
        year_match = _YEAR.search(label)
        year = int(year_match.group(1)) if year_match else page_year
        match = _DAY_MONTH.search(label)
        if match:
            day, month = match.groups()
        else:
            match = _MONTH_DAY.search(label)
            if not match:
                return None
            month, day = match.groups()
        return parse_date(f"{day} {month} {year}", dayfirst=True).date()

    def _meetings(self, page_url: str, page_year: int) -> list[ScraperReturn]:
        soup = self._soup(page_url)
        meetings: dict[tuple, dict] = {}
        for link in soup.find_all("a", href=True):
            href = urljoin(page_url, link["href"])
            if "/sites/default/files/" not in href or not href.lower().endswith(".pdf"):
                continue
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            filename = unquote(href.rsplit("/", 1)[-1])
            if _NOT_THE_PAPER.search(label):
                continue
            if _MINUTES.search(label):
                field = "minutes"
            elif _AGENDA.search(label):
                field = "agenda"
            else:
                continue
            # A link split in two by the editor ("V" + "iew September 2
            # agenda") leaves a fragment with no date; the other half has it.
            date = self._date(label, page_year)
            if date is None:
                continue

            kinds = [k for k in (_kind(label), _kind(filename)) if k]
            key = (date, any(k.startswith("Planning") for k in kinds))
            meeting = meetings.setdefault(key, {"kinds": []})
            meeting["kinds"].extend(kinds)

            # Big agendas are split into numbered parts; Part 1 carries the
            # agenda itself, so it is the one kept. An unnumbered agenda is
            # the whole thing and wins over any part.
            part_match = _PART.search(label) or _PART.search(filename)
            part = int(part_match.group(1)) if part_match else 0
            current = meeting.get(field)
            if current is None or part < current[0]:
                meeting[field] = (part, href)

        results = []
        for (date, _), meeting in meetings.items():
            agenda_url = meeting["agenda"][1] if "agenda" in meeting else None
            minutes_url = meeting["minutes"][1] if "minutes" in meeting else None
            order = [kind for _, kind in _KINDS]
            name = min(meeting["kinds"], key=order.index, default=_DEFAULT_KIND)
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

        results: list[ScraperReturn] = []
        for index_url in _INDEXES:
            pages = self._year_pages(index_url, wanted)
            if clock.current_year() in wanted and clock.current_year() not in pages:
                raise ValueError(
                    f"No {clock.current_year()} page linked from {index_url}"
                )
            for year, url in sorted(pages.items()):
                for meeting in self._meetings(url, year):
                    if int(meeting.date[:4]) in wanted:
                        results.append(meeting)

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
