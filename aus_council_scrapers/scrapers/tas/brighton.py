import datetime
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.brighton.tas.gov.au"
_LISTING_URL = f"{_BASE_URL}/council/meeting-minutes/"

# Brighton Council (Tasmania—not Brighton in Victoria, hence the slug). Its
# whole history since 2018 is on one page, in CSS tabs: one tab per meeting
# body, one table per year inside it, a row per meeting with the date in the
# first cell and "View" links in columns headed Agenda, Attachments, Minutes
# and Audio Recording. Column sets change from table to table (before 2024 the
# OCM tables hold only Minutes, or Minutes and Audio), so cells are mapped by
# their header, never by position.
#
# One request covers everything, so every body with documents is kept. The
# other tabs are the meeting schedule, committee membership, and "Council
# Meeting Outcomes"—summaries of decisions rather than minutes.
_BODIES = {
    "ordinary council": "Ordinary Council Meeting",
    "planning authority": "Planning Authority Meeting",
    "community development": "Community Development Committee",
    "parks & recreation": "Parks & Recreation Committee",
    "finance": "Finance Committee",
    "annual general": "Annual General Meeting",
}

# A filename date in the d-m-yy or d-m-yyyy form every Brighton upload uses
# ("OCM-Agenda-20-01-2026-website.pdf", "Planning-Minutes-8-10-19.pdf").
_FILENAME_DATE = re.compile(r"(?<!\d)(\d{1,2})-(\d{1,2})-(\d{4}|\d{2})(?!\d)")


def _filename_date(url: str) -> Optional[datetime.date]:
    match = _FILENAME_DATE.search(urlparse(url).path.rsplit("/", 1)[-1])
    if not match:
        return None
    day, month, year = (int(g) for g in match.groups())
    if year < 100:
        year += 2000
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


@register_scraper
class BrightonTasScraper(BaseScraper):
    def __init__(self):
        super().__init__("brighton_tas", "TAS", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _document(self, link: Tag, meeting_date: datetime.date, kind: str):
        url = urljoin(_LISTING_URL, link["href"].strip())
        if not urlparse(url).path.lower().endswith(".pdf"):
            # A few attachments and recordings are SharePoint shares; no agenda
            # or minutes is, but refuse a non-document rather than store one.
            return None
        # Pasting the wrong link is the one error this hand-kept table makes:
        # the 4 February 2025 Parks & Recreation row links the 5 November 2024
        # agenda. Every upload is named with its meeting's date, so a filename
        # naming a different day is someone else's document.
        named = _filename_date(url)
        if named is not None and named != meeting_date:
            self.logger.warning(
                f"{self.council_name}: {kind} linked on the {meeting_date} row is "
                f"{url}, dated {named}; left out"
            )
            return None
        return url

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(_LISTING_URL), "html.parser")

        results: list[ScraperReturn] = []
        for tab_link in soup.select('a[href^="#tab-"]'):
            label = tab_link.get_text(" ", strip=True).lower()
            body = next((name for key, name in _BODIES.items() if key in label), None)
            tab = soup.find(id=tab_link["href"][1:])
            if body is None or tab is None:
                continue

            for table in tab.find_all("table"):
                rows = table.find_all("tr")
                if not rows:
                    continue
                headers = [
                    c.get_text(" ", strip=True).lower()
                    for c in rows[0].find_all(["th", "td"])
                ]
                for row in rows[1:]:
                    record = self._row(row, headers, body, wanted)
                    if record is not None:
                        results.append(record)

        if not results:
            self.logger.warning(
                f"{self.council_name}: no meetings with documents found at {_LISTING_URL}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results

    def _row(self, row: Tag, headers: list[str], body: str, wanted: set[int]):
        cells = row.find_all(["td", "th"])
        if not cells:
            return None
        date_text = cells[0].get_text(" ", strip=True)
        if not date_text:
            # Placeholder rows left blank for meetings not yet scheduled.
            return None
        try:
            meeting_date = parse_date(date_text, fuzzy=True, dayfirst=True).date()
        except (ValueError, OverflowError):
            self.logger.warning(f"{self.council_name}: unparseable date {date_text!r}")
            return None
        if meeting_date.year not in wanted:
            return None

        agenda_url = minutes_url = None
        for index, cell in enumerate(cells[1:], start=1):
            column = headers[index] if index < len(headers) else ""
            for link in cell.find_all("a", href=True):
                text = link.get_text(" ", strip=True).lower()
                # The 2022 AGM row puts its minutes in the agenda cell as a
                # second link, "View Minutes", so the link's own label wins
                # over its column.
                if "minutes" in text or (column == "minutes" and text.startswith("view")):
                    kind = "minutes"
                elif column == "agenda":
                    kind = "agenda"
                else:
                    continue
                url = self._document(link, meeting_date, kind)
                if url is None:
                    continue
                if kind == "agenda" and agenda_url is None:
                    agenda_url = url
                elif kind == "minutes" and minutes_url is None:
                    minutes_url = url

        if not agenda_url and not minutes_url:
            # Upcoming meetings sit in the table with empty cells until their
            # agenda is posted.
            return None
        return ScraperReturn(
            name=body,
            date=meeting_date.isoformat(),
            time=None,
            webpage_url=_LISTING_URL,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
        )
