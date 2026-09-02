"""City of Melbourne.

The council replaced its SharePoint site with Drupal, so the old
``meetings-finder.aspx`` this scraper used is gone. Meetings now live in two
places:

``/meetings-search``
    A paginated Views table of every meeting held, newest first, with the
    minutes and resolutions attached to each row but no agenda. The
    ``field_archived`` filter defaults to the current council (post-November
    2024); ``All`` is needed to reach back to `EARLIEST_YEAR`. Its date filter
    bounds the pager too, so a `years_filter` run is a handful of pages rather
    than two dozen.

``/upcoming-council-and-committee-meetings``
    Scheduled meetings with date, time and location. A row links to its
    meeting page once the papers are published — normally 2pm the Thursday
    before — and only then does the meeting have an agenda to find.

The agenda, and the meeting's time and location, are on the per-meeting page,
which means one fetch per meeting. Fetching all ~220 of them would record a
cassette of well over a hundred megabytes, so those pages are fetched for
meetings inside `DETAIL_WINDOW_DAYS` of today, for everything upcoming, and
for any meeting the listing gave no minutes for. Older meetings carry the
minutes the listing already gave us and no agenda.

The whole site sits behind an AWS WAF challenge: plain requests get HTTP 202
and an empty body whatever headers they send, so every fetch here goes through
Selenium. The challenge page reloads itself once it has issued a token, hence
the wait-for-content on each fetch rather than reading `page_source` straight
after `get()`. The same rules 403 headless Chrome on its User-Agent alone,
which is why this scraper sets `strip_headless_user_agent`.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.melbourne.vic.gov.au"
_SEARCH_URL = f"{_BASE_URL}/meetings-search"
_UPCOMING_URL = f"{_BASE_URL}/upcoming-council-and-committee-meetings"

# The listing runs to 23 pages of 10 for 2020 onwards. The cap only stops a
# runaway if the site ever starts clamping out-of-range pages to the last one
# instead of returning an empty table.
_MAX_SEARCH_PAGES = 60


@dataclass
class _Meeting:
    """One meeting, assembled from however many pages mention it."""

    path: str | None
    name: str
    date: str
    parsed_date: datetime.date | None = None
    time: str | None = None
    location: str | None = None
    agenda_url: str | None = None
    minutes_url: str | None = None

    @property
    def key(self) -> tuple:
        # The meeting page path identifies a meeting across all three sources.
        # Rows with no page yet fall back to name and date.
        return ("path", self.path) if self.path else ("named", self.name, self.date)

    def absorb(self, other: "_Meeting") -> None:
        for field in ("time", "location", "agenda_url", "minutes_url", "path"):
            if not getattr(self, field):
                setattr(self, field, getattr(other, field))


def _strip_trailing_date(title: str) -> str:
    """Turn a meeting title into a meeting type.

    Titles read "Council Meeting 28 July 2026"; the date is carried in its own
    field, and what is left names the kind of meeting — including the
    "Special" that the meeting-type column drops.
    """
    return re.sub(
        r"\s*\d{1,2}\s+\w+\s+\d{4}\s*$",
        "",
        re.sub(r"\s+", " ", title).strip(),
    ).strip()


def _date_from_path(path: str) -> str:
    """A meeting page's own slug ends in its date.

    Nearly every listing title carries the date, but not all of them — the
    "Amendment C278 Sunlight to Parks Committee" row has none — and a meeting
    without a date is a meeting this scraper has to drop. The slug
    (``…-14-september-2021``) says it for free, with no extra page to fetch.
    """
    match = re.search(r"(\d{1,2})-([a-z]+)-(\d{4})$", path, re.IGNORECASE)
    if not match:
        return ""
    day, month, year = match.groups()
    return f"{day} {month.capitalize()} {year}"


def _drupal_field(soup: BeautifulSoup, name: str):
    """The `field__item` of a Drupal field div, e.g. `field-start-date`."""
    field = soup.select_one(f"div.field--name-{name}")
    return field.select_one(".field__item") if field else None


@register_scraper
class MelbourneScraper(BaseScraper):
    # How far back to fetch per-meeting pages for the agenda, time and
    # location. A quarter always spans several meetings — the council sits
    # roughly fortnightly outside the January recess — so there is never a
    # point in the calendar where this window comes back empty.
    #
    # Kept deliberately tight because these fetches are this scraper's main
    # cost and production runs every council in one process under a 180s kill
    # (see AGENTS.md). Widening it buys older agendas at the price of the
    # nightly ingest for every council, which is not a trade worth making.
    DETAIL_WINDOW_DAYS = 90

    # This council's CloudFront rules 403 headless Chrome on the
    # "HeadlessChrome" User-Agent token alone, and 403 an identifying client
    # too — a browser-shaped string is the only thing they serve. Opt in here
    # rather than globally: it is what makes this scraper work at all, and it
    # costs banyule most of its history (see `__setup_selenium_driver`).
    strip_headless_user_agent = True

    def __init__(self):
        super().__init__("melbourne", "VIC", _BASE_URL)
        self.default_location = (
            "Melbourne Town Hall Administration Building, "
            "120 Swanston Street, Melbourne"
        )

    # ------------------------------------------------------------------
    # Fetching
    # ------------------------------------------------------------------

    def _fetch(self, url: str, expect_css: str) -> BeautifulSoup:
        """Fetch a page, waiting past the WAF challenge for real content.

        Retried once, because a scrape here is dozens of sequential page loads
        and one slow challenge round-trip would otherwise cost the whole
        council. Replay is unaffected: the cassette is keyed by URL, so a
        second attempt at the same page reads the same recording.
        """
        last_error = None
        for attempt in range(2):
            try:
                html = self.fetcher.fetch_with_selenium(
                    url,
                    wait_time=30,
                    wait_condition=EC.presence_of_element_located(
                        (By.CSS_SELECTOR, expect_css)
                    ),
                )
                return BeautifulSoup(html, "html.parser")
            except Exception as error:
                # CassetteMiss and UnsupportedDriverCall are BaseExceptions, so
                # a missing recording still surfaces instead of being retried.
                last_error = error
                self.logger.warning(
                    f"{type(error).__name__} on {url} "
                    f"(attempt {attempt + 1}/2)"
                )
                # Chrome does not always survive ~50 pages of this size. A
                # retry against a dead session fails identically, so give the
                # second attempt a new browser.
                self.fetcher.restart_driver()
        raise last_error

    def _year_bounds(self) -> tuple[int, int]:
        """The span of years to ask the listing for.

        `years_filter` is set by the runner when `--years` is passed, and
        production passes the current year every night. Honouring it is not a
        nicety here: the listing's date filter bounds its own pagination, so a
        single-year run walks 3 pages instead of 24, and this scraper is
        otherwise the most expensive one in the project.
        """
        years = getattr(self, "years_filter", None)
        if years:
            return min(years), max(years)
        return EARLIEST_YEAR, clock.current_year() + 2

    def _search_page_url(self, page: int) -> str:
        first, last = self._year_bounds()
        return (
            f"{_SEARCH_URL}?field_archived=All"
            f"&exposed_from_date={first}-01-01"
            f"&exposed_to_date={last}-12-31"
            f"&page={page}"
        )

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_date(self, text: str) -> tuple[str | None, datetime.date | None]:
        """The date as the page writes it, plus a date object to sort by."""
        match = self.date_regex.search(text)
        if not match:
            return None, None
        date_str = match.group()
        try:
            return date_str, parse_date(date_str, fuzzy=True).date()
        except Exception:
            return date_str, None

    def _parse_time(self, text: str) -> str | None:
        match = self.time_regex.search(text)
        return match.group() if match else None

    def _absolute(self, href: str) -> str:
        return urljoin(_BASE_URL, href)

    def _parse_search_rows(self, soup: BeautifulSoup) -> list[_Meeting]:
        meetings = []
        for row in soup.select("table tbody tr"):
            link = row.select_one("td.views-field-title a[href]")
            if not link:
                continue
            title = re.sub(r"\s+", " ", link.get_text(strip=True))
            date_str, parsed = self._parse_date(title)
            if not date_str:
                date_str, parsed = self._parse_date(_date_from_path(link["href"]))
            if not date_str:
                self.logger.warning(f"No date in listing title: {title!r}")
                continue

            minutes = row.select_one("td.views-field-field-minutes a[href]")
            meeting_type = row.select_one("td.views-field-field-meeting-type")

            meetings.append(
                _Meeting(
                    path=link["href"],
                    name=_strip_trailing_date(title)
                    or (
                        meeting_type.get_text(strip=True)
                        if meeting_type
                        else self.default_name
                    ),
                    date=date_str,
                    parsed_date=parsed,
                    minutes_url=self._absolute(minutes["href"]) if minutes else None,
                )
            )
        return meetings

    def _parse_upcoming(self, soup: BeautifulSoup) -> list[_Meeting]:
        meetings = []
        for row in soup.select("table tr"):
            # The meeting type is a row header rather than a cell, so both
            # element types have to be read to line the columns up.
            cells = row.find_all(["th", "td"])
            if len(cells) < 3:
                continue

            when = cells[1].get_text("\n", strip=True)
            date_str, parsed = self._parse_date(when)
            if not date_str:
                continue

            # Everything after the date/time line is the address.
            lines = [line.strip() for line in when.split("\n") if line.strip()]
            location = ", ".join(lines[1:]) or None

            link = cells[2].find("a", href=True)
            meetings.append(
                _Meeting(
                    path=link["href"] if link else None,
                    name=cells[0].get_text(" ", strip=True) or self.default_name,
                    date=date_str,
                    parsed_date=parsed,
                    time=self._parse_time(when),
                    location=location,
                )
            )
        return meetings

    def _parse_detail(self, path: str) -> _Meeting | None:
        soup = self._fetch(self._absolute(path), "main")

        heading = soup.select_one("main h1")
        title = (
            re.sub(r"\s+", " ", heading.get_text(strip=True)) if heading else ""
        )

        start = _drupal_field(soup, "field-start-date")
        start_text = start.get_text(" ", strip=True) if start else ""
        date_str, parsed = self._parse_date(start_text or title)
        if not date_str:
            self.logger.warning(f"No date on meeting page {path}")
            return None

        location = _drupal_field(soup, "field-location-string")
        agenda = soup.select_one("div.field--name-field-agenda-file a[href]")
        minutes = soup.select_one("div.field--name-field-minutes a[href]")

        return _Meeting(
            path=path,
            name=_strip_trailing_date(title) or self.default_name,
            date=date_str,
            parsed_date=parsed,
            time=self._parse_time(start_text),
            location=location.get_text(" ", strip=True) if location else None,
            agenda_url=self._absolute(agenda["href"]) if agenda else None,
            minutes_url=self._absolute(minutes["href"]) if minutes else None,
        )

    # ------------------------------------------------------------------
    # Collection
    # ------------------------------------------------------------------

    def _collect_listing(self) -> list[_Meeting]:
        """Every meeting held since EARLIEST_YEAR, newest page first."""
        meetings: list[_Meeting] = []
        for page in range(_MAX_SEARCH_PAGES):
            rows = self._parse_search_rows(
                self._fetch(self._search_page_url(page), "main")
            )
            if not rows:
                break
            meetings.extend(rows)
        else:
            self.logger.warning(
                f"Stopped at the {_MAX_SEARCH_PAGES}-page cap; the listing may "
                f"hold more meetings than were collected."
            )
        return meetings

    def _needs_detail(self, meeting: _Meeting, cutoff: datetime.date) -> bool:
        """Which meetings are worth a page fetch of their own.

        Recent and upcoming ones, because that is where an agenda is still
        worth reading — and any meeting the listing gave no minutes for,
        because otherwise it has no document at all and gets dropped, and its
        own page is the last place left to look.
        """
        if not meeting.path:
            return False
        if not meeting.minutes_url:
            return True
        return meeting.parsed_date is not None and meeting.parsed_date >= cutoff

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        collected: dict[tuple, _Meeting] = {}

        def add(meeting: _Meeting) -> None:
            existing = collected.get(meeting.key)
            if existing is None:
                collected[meeting.key] = meeting
            else:
                existing.absorb(meeting)

        for meeting in self._parse_upcoming(self._fetch(_UPCOMING_URL, "table")):
            add(meeting)
        upcoming_count = len(collected)

        for meeting in self._collect_listing():
            add(meeting)
        self.logger.info(
            f"Found {upcoming_count} scheduled and "
            f"{len(collected) - upcoming_count} past meeting(s)"
        )

        cutoff = clock.today() - datetime.timedelta(days=self.DETAIL_WINDOW_DAYS)
        wanted = [m for m in collected.values() if self._needs_detail(m, cutoff)]
        self.logger.info(
            f"Fetching {len(wanted)} meeting page(s) for agendas (meetings on or "
            f"after {cutoff}, plus any with no minutes listed); the remaining "
            f"{len(collected) - len(wanted)} meeting(s) keep the minutes from "
            f"the listing only, with no agenda"
        )
        unreadable = 0
        for meeting in wanted:
            try:
                detail = self._parse_detail(meeting.path)
            except Exception as error:
                # A meeting page adds the agenda, time and location to a record
                # the listing already gave us. Losing one is a degradation
                # worth logging, not a reason to drop 200 meetings — unlike a
                # listing page, which `_collect_listing` still fails loudly on
                # because a gap there silently truncates the history.
                unreadable += 1
                self.logger.warning(
                    f"Could not read meeting page {meeting.path}: "
                    f"{type(error).__name__}"
                )
                continue
            if detail is None:
                continue
            # The meeting page is the better source for everything it holds.
            detail.absorb(meeting)
            collected[meeting.key] = detail

        # Tolerating a lost meeting page one at a time can add up to a scrape
        # that "worked" and found almost no agendas — which is what happens
        # when Chrome dies part-way and every later fetch fails. That is a
        # failed run, and it must not be mistaken for this council publishing
        # nothing, least of all by a re-record.
        if wanted and unreadable > len(wanted) // 4:
            raise RuntimeError(
                f"{unreadable} of {len(wanted)} meeting pages could not be "
                f"read; treating this as a failed run rather than reporting "
                f"{len(collected)} meetings with almost no agendas."
            )

        results = []
        undocumented = 0
        for meeting in sorted(
            collected.values(),
            key=lambda m: (m.parsed_date or datetime.date.min, m.name),
            reverse=True,
        ):
            if not (meeting.agenda_url or meeting.minutes_url):
                # Nearly always a scheduled meeting whose papers are not
                # published yet. There is no document to point at, and a
                # record without one fails the runner's required-property
                # check.
                undocumented += 1
                continue
            results.append(
                ScraperReturn(
                    name=meeting.name,
                    date=meeting.date,
                    time=meeting.time,
                    webpage_url=(
                        self._absolute(meeting.path) if meeting.path else _SEARCH_URL
                    ),
                    agenda_url=meeting.agenda_url,
                    minutes_url=meeting.minutes_url,
                    download_url=meeting.agenda_url or meeting.minutes_url,
                    location=meeting.location,
                )
            )

        if not results:
            self.logger.warning("No meetings found for Melbourne")
        else:
            self.logger.info(
                f"Found {len(results)} Melbourne meetings "
                f"({undocumented} meeting(s) dropped with no papers published)"
            )
        return results
