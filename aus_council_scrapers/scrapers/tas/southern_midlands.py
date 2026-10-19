import datetime
import re
from typing import Optional
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.southernmidlands.tas.gov.au"
_HUB_URL = f"{_BASE_URL}/council-meetings/"

# Southern Midlands keeps its papers on hand-edited static pages: one for the
# current year ("Agendas & Minutes 2026 Year", /agendas-and-minutes-2026/) and
# archives covering a span of years ("Agendas & Minutes 2025-2021",
# "... 2020-2012"). Each page is a flat run of links to /assets/*.pdf:
# "Agenda 28th January 2026", "Attachments 28th January 2026 Part 1",
# "Minutes 28th January 2026".
#
# The pages are found by their link text rather than by building URLs. The
# current-year page's address changes every year, and an address that does
# not exist (/agendas-and-minutes-2025/) answers 200 with a "not found" page,
# so a guessed URL would read as a year with no meetings. The hub links the
# current-year page; that page's sub-navigation links the archives.
_PAGE_LINK = re.compile(
    r"agendas?\s*(?:&|and)\s*minutes\s+(\d{4})(?:\s*-\s*(\d{4}))?", re.IGNORECASE
)

_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        [
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
    )
}
# Labels write ordinal days ("23rd September 2020") and are hand-typed
# ("Septemeber"), so a month is matched on its first three letters. Older
# filenames use underscores ("AGENDA_-_22_January_2020").
_DAY_MONTH_YEAR = re.compile(
    r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[\s_\-]+"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s_\-,]+(\d{4})",
    re.IGNORECASE,
)
# "southernmidlands_agenda_2016_03_23_Tunnack_Hall.pdf", "Agenda_20180424".
_ISO_DATE = re.compile(r"(?<!\d)(20\d\d)[_\-]?(\d\d)[_\-]?(\d\d)(?!\d)")

# Attachments books ("Attachments 28th January 2026 Part 1") and the 2021
# "Minute Attachments" are papers beside the agenda or minutes, not either.
_ATTACHMENT = re.compile(r"attach|enclos", re.IGNORECASE)
_MINUTES = re.compile(r"minut", re.IGNORECASE)
_AGENDA = re.compile(r"agenda", re.IGNORECASE)
_SPECIAL = re.compile(r"special", re.IGNORECASE)
_AGM = re.compile(r"annual\s+gen|(?<![a-z])agm(?![a-z])", re.IGNORECASE)
_FACILITIES = re.compile(r"facilities", re.IGNORECASE)


def _date_in(text: str) -> Optional[datetime.date]:
    for day, month, year in _DAY_MONTH_YEAR.findall(text):
        try:
            return datetime.date(int(year), _MONTHS[month[:3].lower()], int(day))
        except ValueError:
            continue
    for year, month, day in _ISO_DATE.findall(text):
        try:
            return datetime.date(int(year), int(month), int(day))
        except ValueError:
            continue
    return None


def _meeting_name(text: str) -> str:
    if _AGM.search(text):
        return "Annual General Meeting"
    if _FACILITIES.search(text):
        return "Facilities and Recreation Committee"
    if _SPECIAL.search(text):
        return "Special Council Meeting"
    return "Ordinary Council Meeting"


@register_scraper
class SouthernMidlandsScraper(BaseScraper):
    def __init__(self):
        super().__init__("southern_midlands", "TAS", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _year_pages(soup: BeautifulSoup) -> dict[str, tuple[int, int]]:
        """{page url: (first year, last year)} for every listing page linked."""
        pages = {}
        for link in soup.find_all("a", href=True):
            match = _PAGE_LINK.search(link.get_text(" ", strip=True))
            if not match:
                continue
            years = sorted(int(y) for y in match.groups() if y)
            pages[urljoin(_BASE_URL, link["href"])] = (years[0], years[-1])
        return pages

    def _fetch(self, url: str) -> BeautifulSoup:
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
        if soup.find(id="col1") is None:
            # The site's "not found" page is a 200 without the content column.
            raise RuntimeError(f"{self.council_name}: no listing on {url}")
        return soup

    def _documents(self, soup: BeautifulSoup, page_url: str):
        """(kind, date, name, url) for each agenda and minutes link on a page."""
        previous_href = None
        for link in soup.find(id="col1").find_all("a", href=True):
            href = link["href"].strip()
            if not href.lower().endswith(".pdf"):
                continue
            # A label is sometimes split by a <br> into a second, empty anchor
            # to the same file; the empty one adds nothing.
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            if not label or href == previous_href:
                continue
            previous_href = href
            url = urljoin(page_url, href)
            filename = unquote(href.rsplit("/", 1)[-1])
            if _ATTACHMENT.search(label) or _ATTACHMENT.search(filename):
                continue
            # The filename says what the document is more reliably than the
            # label: in 2024 the agenda links are labelled with a bare date
            # ("24th January 2024"), and "Agenda 13th December 2023 Minutes -
            # Annual General Meeting" is the AGM's minutes. And the 2024 AGM's
            # "Minutes" link points at its agenda file, which is then the
            # agenda and not the minutes.
            if _MINUTES.search(filename):
                kind = "minutes"
            elif _AGENDA.search(filename):
                kind = "agenda"
            elif _MINUTES.search(label):
                kind = "minutes"
            elif _AGENDA.search(label):
                kind = "agenda"
            else:
                continue
            # The label carries the meeting's date; the filename is the
            # fallback, for "Agenda 23rd Septemeber 2020".
            date = _date_in(label) or _date_in(filename)
            if date is None:
                self.logger.warning(
                    f"{self.council_name}: cannot date {label!r} ({url}); skipped"
                )
                continue
            yield kind, date, _meeting_name(f"{label} {filename}"), url

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # Fetch failures are left to raise: each page holds whole years, and
        # a page lost would report those years as having no meetings.
        hub = BeautifulSoup(self.fetcher.fetch_with_requests(_HUB_URL), "html.parser")
        current = self._year_pages(hub)
        if not current:
            raise RuntimeError(
                f"{self.council_name}: no agendas-and-minutes page linked from {_HUB_URL}"
            )

        # The current-year page is always read: its sub-navigation is where
        # the archive pages are linked.
        pages: dict[str, BeautifulSoup] = {}
        archives: dict[str, tuple[int, int]] = {}
        for url in current:
            pages[url] = self._fetch(url)
            archives.update(self._year_pages(pages[url]))
        for url, (first, last) in archives.items():
            if url in pages or not wanted & set(range(first, last + 1)):
                continue
            pages[url] = self._fetch(url)

        meetings: dict[tuple[datetime.date, str], dict] = {}
        for page_url, soup in pages.items():
            for kind, date, name, url in self._documents(soup, page_url):
                if date.year not in wanted:
                    continue
                meeting = meetings.setdefault((date, name), {"webpage_url": page_url})
                # First link wins: the agenda is listed before any amended
                # copy, and an AGM's mislabelled second link repeats its agenda.
                meeting.setdefault(kind, url)

        results = []
        for (date, name), papers in sorted(meetings.items()):
            agenda_url = papers.get("agenda")
            minutes_url = papers.get("minutes")
            results.append(
                ScraperReturn(
                    name=name,
                    date=date.isoformat(),
                    time=None,
                    webpage_url=papers["webpage_url"],
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        if not results:
            # The one empty answer that is not a fault: production asks for
            # the current year alone, and before March a small council may not
            # have posted its first paper of the year. Any other empty result
            # means the pages moved or stopped parsing, and returning [] would
            # read downstream as a successful night with no meetings.
            today = clock.today()
            if min(wanted) > today.year or (
                min(wanted) == today.year and today.month < 3
            ):
                self.logger.warning(
                    f"{self.council_name}: no meetings published yet for "
                    f"{sorted(wanted)}"
                )
            else:
                raise RuntimeError(
                    f"{self.council_name}: no meetings with documents for "
                    f"{sorted(wanted)}; the pages may have changed"
                )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
