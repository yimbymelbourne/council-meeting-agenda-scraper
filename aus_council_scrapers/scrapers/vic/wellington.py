"""Wellington Shire Council—a Webflow CMS list, paged on the server.

The Meeting Minutes and Agendas page renders 100 meetings a page, newest
first, with Webflow's own pager (``?e9e2f2ae_page=2``, ``=3``). Each meeting
is a ``div.meeting-item.w-dyn-item``: the date in ``.meeting-title``
("Tuesday, October 6, 2026"), the type in ``meeting-type`` ("Ordinary",
"Special"), the start time beside it, and ``a.meeting-links-link`` buttons
labelled Agenda, Minutes and Watch. In October 2026 three pages reached back
to February 2014.

A button with nothing behind it is still in the markup, hidden with
``w-condition-invisible`` and pointing at ``#``; those are skipped, so an
upcoming meeting comes out with its agenda and no minutes.

The date comes from the title, never the filename: the 1 September 2026
minutes are filed as ``20280901-Minutes-OrdinaryCouncilMeeting.pdf``.

**Cost.** Page 1 runs back to mid-2022, so production's one year is one
request. The pager is followed only while the last page read still reaches
into a wanted year.

Cloudflare fronts the site (``server: cloudflare``); no challenge was seen
from a home IP. robots.txt allows everything. Not yet measured from a GitHub
runner.
"""

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.wellington.vic.gov.au"
_LISTING_URL = f"{_BASE_URL}/council/meeting-minutes-and-agendas"

# A safety stop: the listing had three pages in October 2026.
_MAX_PAGES = 20


def _visible_pdf(anchor, page_url: str) -> str | None:
    if "w-condition-invisible" in (anchor.get("class") or []):
        return None
    href = (anchor.get("href") or "").strip()
    if not urlparse(href).path.lower().endswith(".pdf"):
        return None
    return urljoin(page_url, href)


@register_scraper
class WellingtonScraper(BaseScraper):
    def __init__(self):
        super().__init__("wellington", "VIC", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return {int(year) for year in years_filter}
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _parse(self, soup: BeautifulSoup, page_url: str) -> list[ScraperReturn]:
        results = []
        for item in soup.select("div.meeting-item.w-dyn-item"):
            title = item.select_one(".meeting-title")
            if title is None:
                continue
            date = parse_date(title.get_text(" ", strip=True)).date()

            agenda_url = minutes_url = None
            for anchor in item.select("a.meeting-links-link"):
                url = _visible_pdf(anchor, page_url)
                label = anchor.get_text(" ", strip=True).lower()
                if not url:
                    continue
                if label == "agenda" and agenda_url is None:
                    agenda_url = url
                elif label == "minutes" and minutes_url is None:
                    minutes_url = url
            if not agenda_url and not minutes_url:
                continue

            kind = item.select_one('[fs-cmsfilter-field="meeting-type"]')
            kind = kind.get_text(" ", strip=True) if kind else ""
            name = f"{kind} Council Meeting" if kind else "Council Meeting"

            time_value = None
            for row_item in item.select(".meeting-details-row-item"):
                label_div = row_item.select_one(".meeting-details-row-title")
                if label_div and "time" in label_div.get_text().lower():
                    match = self.time_regex.search(row_item.get_text(" ", strip=True))
                    time_value = match.group() if match else None

            results.append(
                ScraperReturn(
                    name=name,
                    date=date.isoformat(),
                    time=time_value,
                    webpage_url=_LISTING_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )
        return results

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        earliest = min(wanted)

        results: list[ScraperReturn] = []
        url = _LISTING_URL
        for _ in range(_MAX_PAGES):
            # Every page raises on failure: a missing page is a gap in the
            # middle of the history, not its end.
            soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
            items = soup.select("div.meeting-item.w-dyn-item")
            if not items and url == _LISTING_URL:
                raise RuntimeError(
                    f"{self.council_name}: no meetings on {_LISTING_URL}"
                )
            page = self._parse(soup, url)
            results.extend(r for r in page if int(r.date[:4]) in wanted)

            # Newest first, so once a page ends before the earliest wanted
            # year every later page is older still.
            dates = [
                parse_date(t.get_text(" ", strip=True)).date()
                for t in soup.select("div.meeting-item.w-dyn-item .meeting-title")
            ]
            following = soup.select_one("a.w-pagination-next")
            if not following or not dates or min(dates).year < earliest:
                break
            url = urljoin(_LISTING_URL, following["href"])

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
