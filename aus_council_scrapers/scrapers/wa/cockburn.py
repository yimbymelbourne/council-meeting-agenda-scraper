import datetime
import math
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR
from aus_council_scrapers.meeting_documents import (
    AGENDA,
    MINUTES,
    Document,
    group_documents,
)

_BASE_URL = "https://www.cockburn.wa.gov.au"
_LISTING_URL = (
    f"{_BASE_URL}/City-and-Council/About-Council-Meetings-and-Elections"
    "/Agendas-and-Minutes/"
)

# The register is an Alyka "DocumentListSingle" web part on Kentico: a table
# of documents, not meetings, 16 rows a page, newest first. Paging and the
# year filter are plain GET parameters, despite the JavaScript pager.
_ROWS_PER_PAGE = 16

# The `years` filter is the year a document was *published*, not the year of
# the meeting: minutes for a 9 December meeting are published in the new
# year, and the agenda for a late-January meeting can go up in December. So
# a meeting year Y needs the publish years either side of it—the tail of
# Y-1 for early-January agendas, and Y+1 for late minutes (which, newest
# first, sit at the end of that year's list, so it is read in full).
#
# Measured over 2019-2026, minutes went up within three weeks of the meeting
# except for one 2018 meeting signed off in March 2019, which is lost unless
# that year is fetched too—a trade worth making for a bounded fetch.
_LEAD_IN_FROM = (12, 1)  # month, day: only December of the previous year

# Rows that are papers for a meeting but neither its agenda nor its minutes:
# attachments circulated separately, addenda, amended reports, and the
# odd governance document filed in the same register.
_NOT_AGENDA_OR_MINUTES = re.compile(
    r"addendum|attach|separate\s+cover|\bitem\b|updated information|cancelled"
    r"|terms of reference|\bform\b|membership|schedule of submissions",
    re.IGNORECASE,
)
_KIND = re.compile(r"\b(agenda|minutes)\b", re.IGNORECASE)
_AMENDED = re.compile(r"\bamended\b", re.IGNORECASE)

# Suffixes that name the council or the venue rather than the meeting, and
# would otherwise end up in the meeting name.
_TITLE_NOISE = re.compile(
    r"\s*-\s*City of Cockburn[^-]*(?:-\s*Internal)?"
    r"|\s*\((?:ARC|GovCo)\)"
    r"|\bcommencement\b"
    r"|,?\s*-?\s*adjourned to .*$",
    re.IGNORECASE,
)


@register_scraper
class CockburnScraper(BaseScraper):
    def __init__(self):
        super().__init__("cockburn", "WA", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _page(self, year: int, page: int) -> tuple[list[tuple], int]:
        """The rows on one page as (title, published, url), and the total."""
        url = f"{_LISTING_URL}?page={page}&years={year}"
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")

        count = soup.find("input", id="recordCountValue")
        total = int(count["value"]) if count and count.get("value") else 0

        rows = []
        table = soup.find(id=re.compile(r"AlykaDocumentsListSingle_OuterPanel$"))
        for tr in table.select("tbody tr") if table else []:
            title_cell = tr.find("td", attrs={"data-title": "Title"})
            date_cell = tr.find("td", attrs={"data-title": "Year"})
            link = title_cell.find("a", href=True) if title_cell else None
            if not link or not date_cell:
                continue
            for hidden in link.select(".sr-only"):
                hidden.decompose()
            title = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            published = parse_date(date_cell.get_text(strip=True), dayfirst=True)
            rows.append((title, published.date(), urljoin(_BASE_URL, link["href"])))
        return rows, total

    def _rows(self, year: int, published_from: datetime.date = None) -> list[tuple]:
        """Every row published in `year`, or only those from `published_from`."""
        rows: list[tuple] = []
        page = 1
        while True:
            try:
                page_rows, total = self._page(year, page)
            except Exception as e:
                self.logger.warning(f"Could not read {year} page {page}: {e}")
                self._errors.append(e)
                break
            rows.extend(page_rows)
            if published_from and page_rows and page_rows[-1][1] < published_from:
                break
            if page >= math.ceil(total / _ROWS_PER_PAGE):
                break
            page += 1
        return rows

    def _document(self, title: str, url: str) -> Document:
        if _NOT_AGENDA_OR_MINUTES.search(title):
            return None
        kind = _KIND.search(title)
        date = self.date_regex.search(title)
        if not kind or not date:
            return None
        return Document(
            kind=AGENDA if kind.group(1).lower() == "agenda" else MINUTES,
            title=_TITLE_NOISE.sub("", title),
            date=parse_date(date.group(), dayfirst=True).date(),
            url=url,
            # An amended agenda replaces the original, but where both are
            # listed the original is what the meeting was called with.
            rank=1 if _AMENDED.search(title) else 0,
        )

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        first, last = min(wanted), min(max(wanted) + 1, clock.current_year())
        self._errors: list[Exception] = []

        rows = self._rows(first - 1, datetime.date(first - 1, *_LEAD_IN_FROM))
        for year in range(first, last + 1):
            rows.extend(self._rows(year))

        seen = set()
        documents = []
        for title, _, url in rows:
            if url in seen:
                continue
            seen.add(url)
            document = self._document(title, url)
            if document and document.date.year in wanted:
                documents.append(document)

        results = []
        for meeting in group_documents(documents, self.date_regex):
            results.append(
                ScraperReturn(
                    name=meeting.name,
                    date=meeting.date.isoformat(),
                    time=meeting.stated_time,
                    webpage_url=_LISTING_URL,
                    agenda_url=meeting.agenda_url,
                    minutes_url=meeting.minutes_url,
                    download_url=meeting.agenda_url or meeting.minutes_url,
                )
            )

        # Production asks for one year, so one failed fetch can leave
        # nothing. An empty list does not raise, and main.py would count the
        # council as working with 0 meetings. Raise instead; a failure that
        # still leaves other years' meetings stays a warning.
        if not results and self._errors:
            raise self._errors[-1]
        if not results:
            self.logger.warning(
                f"{self.council_name}: no meetings among {len(rows)} register rows"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
