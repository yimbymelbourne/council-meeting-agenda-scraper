"""East Gippsland Shire Council—a Webflow CMS list, every meeting on one page.

The Meeting Minutes and Agendas page renders the whole collection server
side: one ``div.meetings-item.w-dyn-item`` per meeting, with the date in
``.meetings-title`` ("Tuesday, October 20, 2026"), the type in the
``Meeting Type=`` field ("Council Meeting", "Statutory Meeting"), the start
time beside it, and ``a.meeting-link`` buttons labelled Agenda and Minutes.
The Finsweet pager on the page is client-side only, so one request returns
every meeting the council lists—43 in October 2026, from 6 February 2024.
Nothing earlier is linked anywhere on the site.

A button with nothing behind it is still in the markup, hidden with
``w-condition-invisible`` and pointing at ``#``; those are skipped, so an
upcoming meeting comes out with its agenda and no minutes.

The date comes from the title, never the filename: the 31 March 2026
unscheduled meeting's agenda is filed as ``2026.06.31 - Unscheduled Council
Meeting Agenda``.

Cloudflare fronts the site (``server: cloudflare``); no challenge was seen
from a home IP. Not yet measured from a GitHub runner.
"""

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper

_BASE_URL = "https://www.eastgippsland.vic.gov.au"
_LISTING_URL = f"{_BASE_URL}/our-council/meeting-minutes-and-agendas"


def _visible_pdf(anchor) -> str | None:
    if "w-condition-invisible" in (anchor.get("class") or []):
        return None
    href = (anchor.get("href") or "").strip()
    if not urlparse(href).path.lower().endswith(".pdf"):
        return None
    return urljoin(_LISTING_URL, href)


@register_scraper
class EastGippslandScraper(BaseScraper):
    def __init__(self):
        super().__init__("east_gippsland", "VIC", _BASE_URL)

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        years_filter = getattr(self, "years_filter", None)

        soup = BeautifulSoup(
            self.fetcher.fetch_with_requests(_LISTING_URL), "html.parser"
        )
        items = soup.select("div.meetings-item.w-dyn-item")
        if not items:
            # The page loaded but the collection is gone: a redesign, not a
            # council with no meetings.
            raise RuntimeError(f"{self.council_name}: no meetings on {_LISTING_URL}")

        results = []
        for item in items:
            title = item.select_one(".meetings-title")
            if title is None:
                continue
            date = parse_date(title.get_text(" ", strip=True)).date()
            if years_filter and date.year not in years_filter:
                continue

            agenda_url = minutes_url = None
            for anchor in item.select("a.meeting-link"):
                url = _visible_pdf(anchor)
                label = anchor.get_text(" ", strip=True).lower()
                if not url:
                    continue
                if label == "agenda" and agenda_url is None:
                    agenda_url = url
                elif label == "minutes" and minutes_url is None:
                    minutes_url = url
            if not agenda_url and not minutes_url:
                continue

            meeting_type = item.select_one('[fs-list-field="Meeting Type="]')
            name = meeting_type.get_text(" ", strip=True) if meeting_type else ""

            # The start time is the second row item, after the type:
            # "Meeting Time:" then "6:00 pm".
            time_value = None
            for row_item in item.select(".meetings-row-item"):
                label_div = row_item.select_one(".meeting-row-label")
                if label_div and "time" in label_div.get_text().lower():
                    match = self.time_regex.search(row_item.get_text(" ", strip=True))
                    time_value = match.group() if match else None

            results.append(
                ScraperReturn(
                    name=name or "Council Meeting",
                    date=date.isoformat(),
                    time=time_value,
                    webpage_url=_LISTING_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
