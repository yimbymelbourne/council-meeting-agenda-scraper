import datetime
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from aus_council_scrapers import clock
from aus_council_scrapers.alyka import find_month
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR
from aus_council_scrapers.pdf_dates import meeting_date_from_papers

_BASE_URL = "https://carrathool.nsw.gov.au"
_LISTING_URL = f"{_BASE_URL}/about-council/council-meetings/"
_ARCHIVE_URL = f"{_BASE_URL}/about-council/publications/agendas-and-minutes/"

# Carrathool Shire Council puts the current year's meetings on one page, a
# table of Meeting Date | Location | Agenda | Minutes | Audio, with the date
# as DD/MM/YYYY and the venue (Goolgowi, Hillston, Carrathool) beside it.
# Future meetings are rows whose cells say "Business Paper" with no link yet.
#
# Earlier years (February 2023 to December 2025) are on a separate archive
# page, /about-council/publications/agendas-and-minutes/, a table per year
# ("2025 Meetings") whose rows are labelled by month only ("December 2025",
# "October 2024 Extra Ordinary"). The day is on neither that page nor most
# filenames, so each archived meeting is dated from the first page of its
# own papers (`pdf_dates`): the minutes first ("MINUTES OF THE ORDINARY
# MEETING OF THE CARRATHOOL SHIRE COUNCIL held on Tuesday 16 December
# 2025", 0.1-1.5 MB, usually read whole), then the business paper
# ("ORDINARY MEETING AGENDA 16 December 2025", 1.4-17 MB). A meeting neither
# dates is left out and logged. Checked 26 Oct 2026: 32 of the 33 archived
# meetings are dated by their minutes, March 2024 (whose minutes link is its
# business paper) by its business paper. For 29 of the 32, the business
# paper is readable within 8 MB and gives the same day as the minutes.
#
# The archive is read only for a run that asks for a past year, so a
# production run for the current year costs one request, as before. A year
# the meetings page holds is never taken from the archive, so the two pages
# cannot list one meeting twice when the council moves a year across.
#
# A documented robots.txt exception, widened on 26 Oct 2026.
# carrathool.nsw.gov.au/robots.txt has, under `User-agent: *`:
#
#     Disallow: /wp-content/uploads/
#     Disallow: /assets/
#
# (checked 26 Oct 2026; no Crawl-delay), and every business paper and set of
# minutes is under /wp-content/uploads/. Both pages the scraper reads are
# allowed. council-alerts downloads every document URL a scraper emits, so
# production fetches the disallowed path; the maintainer decided on 26 Oct
# 2026 to accept that, as he did for swan, because these papers are the
# council's official public record. Since 26 Oct 2026 the exception also
# covers this scraper fetching the archived papers itself, to read the day
# off their first page: one or two PDFs per archived meeting (the first
# 256 KB, or the whole file up to 8 MB), and only on a run for a past
# year, never for the current year. Nothing here may request /assets/ or
# any other disallowed path. See AGENTS.md before adding another.
_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")

# "Council meetings are currently held on the third Tuesday of every month
# commencing at 10.00am." An extraordinary meeting's time is not given.
_ORDINARY_TIME = "10:00 am"
_EXTRAORDINARY = re.compile(r"extra\s*-?\s*ordinary", re.IGNORECASE)

# The page is rebuilt for each new year, so early January may show no
# meeting with papers yet. An empty current year is an error only once this
# much of it has passed, the rule CraftMeetingsModuleScraper uses.
_NEW_YEAR_GRACE_DAYS = 90

# The archive page's first year (from February 2023).
_ARCHIVE_STARTS = 2023


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
        page_years = set()
        for row in rows[1:]:
            match = _DATE.search(row.get_text("", strip=True))
            if match:
                page_years.add(int(match.group(3)))
            record = self._row(row, headers, wanted)
            if record is not None:
                results.append(record)

        # Past years are on the archive page. A production run asks only for
        # the current year and never reads it.
        archived = {y for y in wanted if y < clock.current_year()} - page_years
        if archived:
            results.extend(self._archive(archived))

        if not results:
            message = (
                f"{self.council_name}: no meetings with papers for {sorted(wanted)} "
                f"at {_LISTING_URL}"
            )
            # A year before the archive starts, or after this one, is
            # legitimately empty. An archived year must have meetings, and
            # the current one must have papers once its first months have
            # passed.
            today = clock.today()
            if any(_ARCHIVE_STARTS <= year < today.year for year in wanted) or (
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
            if _EXTRAORDINARY.search(label)
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

    def _archive(self, years: set[int]) -> list[ScraperReturn]:
        """Meetings of `years` from the archive page, dated from their papers."""
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(_ARCHIVE_URL), "html.parser")
        rows = [
            row
            for table in soup.find_all("table")
            for row in table.find_all("tr")
            if len(row.find_all("td")) >= 3
        ]
        if not rows:
            raise RuntimeError(f"{self.council_name}: no meeting rows at {_ARCHIVE_URL}")
        results = []
        undated = []
        for row in rows:
            cells = row.find_all("td")
            label = cells[0].get_text(" ", strip=True)
            month = find_month(label)
            if month is None or month[0] not in years:
                continue
            agenda_link, minutes_link = self._link(cells[1]), self._link(cells[2])
            if agenda_link is None and minutes_link is None:
                # "No Council meeting held due to Local Government Elections."
                continue
            agenda_url = urljoin(_ARCHIVE_URL, agenda_link["href"].strip()) if agenda_link else None
            minutes_url = urljoin(_ARCHIVE_URL, minutes_link["href"].strip()) if minutes_link else None
            if agenda_url and agenda_url == minutes_url:
                # March 2024's minutes link is its business paper.
                minutes_url = None
            date = meeting_date_from_papers(
                self.fetcher, [minutes_url, agenda_url], *month, logger=self.logger
            )
            if date is None:
                undated.append(label)
                continue
            name = (
                "Extraordinary Council Meeting"
                if _EXTRAORDINARY.search(label)
                else "Ordinary Council Meeting"
            )
            results.append(
                ScraperReturn(
                    name=name,
                    date=date.isoformat(),
                    time=None,
                    webpage_url=_ARCHIVE_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                    location=None,
                )
            )
        if undated:
            self.logger.warning(
                f"{self.council_name}: left out, no day in their papers: {undated}"
            )
        return results

    @staticmethod
    def _link(cell: Optional[Tag]) -> Optional[Tag]:
        if cell is None:
            return None
        for link in cell.find_all("a", href=True):
            if urlparse(link["href"]).path.lower().endswith(".pdf"):
                return link
        return None
