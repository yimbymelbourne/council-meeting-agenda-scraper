import datetime
import json
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.cairns.qld.gov.au"
_ARCHIVE_URL = f"{_BASE_URL}/council/meetings/meeting-archive"

# Squiz Matrix, behind Cloudflare. Meetings since January 2021 are calendar
# events found through the meeting-archive page's date search, and each
# event page (/council/meetings/ordinary-meeting/15-april-2026) carries a
# Minutes section and an Agenda section of direct PDFs. The search returns at
# most 12 events with no pager, so a year is read in date windows small
# enough to come back short of that cap.
#
# Each kept meeting costs one request, and there are about 25 Council
# meetings a year, so a production year is about 25 requests. The agenda is
# split into a table of contents ("Table of Contents - Ordinary Meeting - 15
# April 2026", "Notice of Ordinary Meeting") and a PDF per clause; no bound
# agenda exists, so `agenda_url` is the table of contents.
#
# Meetings from 2008 to 2020 are in a separate archive tool: one JSON feed
# behind the same page (`?external-uuid=...`, 4.5 MB), read only when a year
# before 2021 is wanted.
_SEARCH_FORM = "page_calendar_events_search_440162"
_SEARCH_PAGE_SIZE = 12
_FIRST_SEARCH_YEAR = 2021
_ARCHIVE_FEED = f"{_ARCHIVE_URL}/?external-uuid=24fdc466-147e-4a93-975f-0560a26d19d9"

# Council meetings plus the planning body. The planning and environment
# committee was rescinded in August 2023; the governance, community and works
# committees were abolished in October 2021 and are left out, as they would
# add a request per meeting for papers that are not Council decisions.
_KEPT_TYPES = re.compile(r"^(ordinary|special|planning)", re.I)
_ARCHIVE_GROUPS = {
    "Ordinary Meetings": "Ordinary Meeting",
    "Special Meetings": "Special Meeting",
    "Planning and Environment Committee": "Planning and Environment Committee Meeting",
}

# Agendas are published a week or so ahead; the search also lists meetings
# scheduled months out, whose pages hold nothing yet.
_LOOKAHEAD = datetime.timedelta(days=21)


@register_scraper
class CairnsScraper(BaseScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 53 s for 23
    # requests (four searches, 19 event pages). Orders dispatch only.
    expected_seconds = 53

    def __init__(self):
        super().__init__("cairns", "QLD", _BASE_URL)

    def _wanted_years(self) -> list[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return sorted(set(years_filter))
        return list(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _search_url(start: datetime.date, end: datetime.date) -> str:
        def bound(name: str, day: datetime.date) -> str:
            return (
                f"&queries_date_fquery_{name}show=ymd"
                f"&queries_date_fquery_{name}value%5Bd%5D={day.day}"
                f"&queries_date_fquery_{name}value%5Bm%5D={day.month}"
                f"&queries_date_fquery_{name}value%5By%5D={day.year}"
            )

        return (
            f"{_ARCHIVE_URL}?queries_keyword_query=&queries_type_query="
            + bound("from", start)
            + bound("to", end)
            + f"&{_SEARCH_FORM}_submit_button=Search"
        )

    def _search(self, start: datetime.date, end: datetime.date) -> list[dict]:
        url = self._search_url(start, end)
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
        heading = soup.find(
            lambda t: t.name in ("h2", "h3") and t.get_text(strip=True) == "Search Results"
        )
        if heading is None:
            raise ValueError(f"No search results section on {url}")
        results = []
        # Each result is a card: the type (linking the event page), then the
        # date, time and venue, each in a <strong>.
        for card in heading.find_all_next("div", class_="event"):
            link = card.find("a", href=True)
            fields = [s.get_text(" ", strip=True) for s in card.find_all("strong")]
            date_text = next((f for f in fields if self.date_regex.fullmatch(f)), None)
            if not link or not date_text:
                continue
            time_text = next((f for f in fields if self.time_regex.fullmatch(f)), None)
            location = next(
                (f for f in fields if f not in (date_text, time_text)), None
            )
            results.append(
                {
                    "url": urljoin(_BASE_URL, link["href"]),
                    "name": link.get_text(" ", strip=True),
                    "date": parse_date(date_text, dayfirst=True).date(),
                    "time": time_text,
                    "location": location,
                }
            )
        return results

    def _year_events(self, year: int) -> list[dict]:
        events: dict[str, dict] = {}
        # Quarters, because a quarter of Council meetings fits under the cap.
        # A window that comes back full is split in half and asked again: the
        # results are only roughly date-ordered (in 2021 a 30 June special
        # meeting sorts among the March ones), so the date a full page ends
        # on says nothing about what it left out.
        windows = [
            (datetime.date(year, first, 1), datetime.date(year, last, day))
            for first, last, day in ((1, 3, 31), (4, 6, 30), (7, 9, 30), (10, 12, 31))
        ]
        while windows:
            start, end = windows.pop(0)
            page = self._search(start, end)
            for event in page:
                events.setdefault(event["url"], event)
            if len(page) < _SEARCH_PAGE_SIZE:
                continue
            if start >= end:
                raise ValueError(
                    f"More than {_SEARCH_PAGE_SIZE} meetings on {start}; cannot split further"
                )
            middle = start + (end - start) // 2
            windows[:0] = [(start, middle), (middle + datetime.timedelta(days=1), end)]
        return [e for e in events.values() if e["date"].year == year]

    @staticmethod
    def _section_links(soup: BeautifulSoup, title: str) -> list:
        heading = soup.find(lambda t: t.name == "h2" and t.get_text(strip=True) == title)
        if heading is None:
            return []
        return [
            a
            for a in heading.parent.find_all("a", href=True)
            if a["href"].lower().endswith(".pdf")
        ]

    def _event(self, event: dict) -> Optional[ScraperReturn]:
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(event["url"]), "html.parser")

        minutes_url = None
        for link in self._section_links(soup, "Minutes"):
            if re.search(r"minutes", link.get_text(" ", strip=True), re.I):
                minutes_url = urljoin(_BASE_URL, link["href"])
                break

        agenda_url = None
        for link in self._section_links(soup, "Agenda"):
            label = link.get_text(" ", strip=True)
            if re.match(r"clause", label, re.I) or re.search(r"closed", label, re.I):
                continue
            agenda_url = urljoin(_BASE_URL, link["href"])
            break

        if not agenda_url and not minutes_url:
            return None
        return ScraperReturn(
            name=event["name"],
            date=event["date"].isoformat(),
            time=event["time"],
            webpage_url=event["url"],
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
            location=event["location"],
        )

    def _archive(self, years: set[int]) -> list[ScraperReturn]:
        """Meetings before 2021, from the archive tool's JSON feed."""
        groups = json.loads(self.fetcher.fetch_with_requests(_ARCHIVE_FEED))
        results = []
        for group in groups:
            name = _ARCHIVE_GROUPS.get(group.get("group_name", "").replace("&amp;", "&"))
            if not name:
                continue
            for entry in group.get("group_listing", []):
                if entry.get("meeting_year") not in years:
                    continue
                agenda_url = minutes_url = None
                for child in entry.get("asset_children", []):
                    if child.get("asset_type") != "PDF File":
                        continue
                    short = child.get("asset_short_name", "").strip()
                    # "*Open Session Table of Contents" (or "*Table of
                    # Contents", "*Open Session") is the agenda; the closed
                    # session's contents and numbered clauses are not.
                    if agenda_url is None and re.match(r"\*(open session|table of contents)", short, re.I):
                        agenda_url = child["asset_url"]
                    elif minutes_url is None and re.match(r"minutes", short, re.I):
                        minutes_url = child["asset_url"]
                if not agenda_url and not minutes_url:
                    continue
                date = parse_date(entry["asset_name"], dayfirst=True).date()
                results.append(
                    ScraperReturn(
                        name=name,
                        date=date.isoformat(),
                        time=None,
                        webpage_url=_ARCHIVE_URL,
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
        archive_years = {y for y in wanted if y < _FIRST_SEARCH_YEAR}
        if archive_years:
            results.extend(self._archive(archive_years))

        horizon = clock.today() + _LOOKAHEAD
        # Past meetings fetched, and how many of them had a paper.
        past = past_papered = 0
        for year in wanted:
            if year < _FIRST_SEARCH_YEAR or datetime.date(year, 1, 1) > horizon:
                continue
            for event in sorted(self._year_events(year), key=lambda e: e["date"]):
                if not _KEPT_TYPES.match(event["name"]) or event["date"] > horizon:
                    continue
                meeting = self._event(event)
                is_past = event["date"] < clock.today()
                past += is_past
                if meeting:
                    past_papered += is_past
                    results.append(meeting)

        # Past meetings have their papers posted, so past event pages that all
        # come back bare means the Minutes and Agenda headings have changed
        # shape, not that the council stopped publishing.
        if past and not past_papered:
            raise ValueError(
                f"{past} past meetings in {wanted} but no papers on any of them"
            )

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
