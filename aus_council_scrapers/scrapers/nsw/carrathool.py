import datetime
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://carrathool.nsw.gov.au"
_LISTING_URL = f"{_BASE_URL}/about-council/council-meetings/"

# Carrathool Shire Council puts the current year's meetings on one page, a
# table of Meeting Date | Location | Agenda | Minutes | Audio, with the date
# as DD/MM/YYYY and the venue (Goolgowi, Hillston, Carrathool) beside it.
# Future meetings are rows whose cells say "Business Paper" with no link yet.
#
# Earlier years (February 2023 to December 2025) are on a separate archive
# page, /about-council/publications/agendas-and-minutes/, under month
# headings only ("December 2025", "October 2024 Extra Ordinary"). The day is
# on neither that page nor most filenames, and a meeting date is not
# invented from a month, so the archive is not read. That leaves the
# fixture with one year, and the scraper with nothing in the weeks after New
# Year before the first business paper of the year is posted.
#
# A documented robots.txt exception. carrathool.nsw.gov.au/robots.txt has,
# under `User-agent: *`:
#
#     Disallow: /wp-content/uploads/
#     Disallow: /assets/
#
# (checked 26 Oct 2026; no Crawl-delay), and every business paper and set of
# minutes is under /wp-content/uploads/. The scraper itself requests only
# this meetings page, which is allowed, but council-alerts downloads every
# document URL a scraper emits, so production does fetch the disallowed
# path. The maintainer decided on 26 Oct 2026 to accept that, as he did for
# swan, because these papers are the council's official public record. The
# exception covers the emitted papers only: nothing here may request
# /assets/ or any other disallowed path. See AGENTS.md before adding
# another.
_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")

# "Council meetings are currently held on the third Tuesday of every month
# commencing at 10.00am." An extraordinary meeting's time is not given.
_ORDINARY_TIME = "10:00 am"

# The page is rebuilt for each new year, so early January may show no
# meeting with papers yet. An empty current year is an error only once this
# much of it has passed, the rule CraftMeetingsModuleScraper uses.
_NEW_YEAR_GRACE_DAYS = 90


@register_scraper
class CarrathoolScraper(BaseScraper):
    def __init__(self):
        super().__init__("carrathool", "NSW", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(_LISTING_URL), "html.parser")

        table = next(
            (
                t
                for t in soup.find_all("table")
                if "meeting date" in t.get_text(" ", strip=True).lower()
            ),
            None,
        )
        if table is None:
            raise RuntimeError(f"{self.council_name}: no meeting table at {_LISTING_URL}")

        rows = table.find_all("tr")
        headers = [c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"])]
        results = []
        for row in rows[1:]:
            record = self._row(row, headers, wanted)
            if record is not None:
                results.append(record)

        if not results:
            message = (
                f"{self.council_name}: no meetings with papers for {sorted(wanted)} "
                f"at {_LISTING_URL}"
            )
            # Only the current year is on this page, so another year is
            # legitimately empty; the current one must have papers once its
            # first months have passed.
            today = clock.today()
            if (
                today.year in wanted
                and (today - datetime.date(today.year, 1, 1)).days
                >= _NEW_YEAR_GRACE_DAYS
            ):
                raise RuntimeError(message)
            self.logger.warning(message)
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results

    def _row(self, row: Tag, headers: list[str], wanted: set[int]) -> Optional[ScraperReturn]:
        cells = row.find_all("td")
        if len(cells) < len(headers):
            return None
        by_column = dict(zip(headers, cells))
        # The May row's date is split across a stray "1" and a span holding
        # "9/05/2026", so the cell's text is joined without spaces.
        date_text = by_column["meeting date"].get_text("", strip=True)
        match = _DATE.search(date_text)
        if not match:
            return None
        day, month, year = (int(g) for g in match.groups())
        try:
            meeting_date = datetime.date(year, month, day)
        except ValueError:
            self.logger.warning(f"{self.council_name}: bad date {date_text!r}")
            return None
        if meeting_date.year not in wanted:
            return None

        agenda_link = self._link(by_column.get("agenda"))
        minutes_link = self._link(by_column.get("minutes"))
        if agenda_link is None and minutes_link is None:
            return None
        agenda_url = urljoin(_LISTING_URL, agenda_link["href"].strip()) if agenda_link else None
        minutes_url = urljoin(_LISTING_URL, minutes_link["href"].strip()) if minutes_link else None
        if agenda_url and agenda_url == minutes_url:
            minutes_url = None

        label = agenda_link.get_text(" ", strip=True) if agenda_link else ""
        name = (
            "Extraordinary Council Meeting"
            if re.search(r"extra\s*-?\s*ordinary", label, re.IGNORECASE)
            else "Ordinary Council Meeting"
        )
        location = by_column["location"].get_text(" ", strip=True) if "location" in by_column else None

        return ScraperReturn(
            name=name,
            date=meeting_date.isoformat(),
            time=_ORDINARY_TIME if name.startswith("Ordinary") else None,
            webpage_url=_LISTING_URL,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
            location=location or None,
        )

    @staticmethod
    def _link(cell: Optional[Tag]) -> Optional[Tag]:
        if cell is None:
            return None
        for link in cell.find_all("a", href=True):
            if urlparse(link["href"]).path.lower().endswith(".pdf"):
                return link
        return None
