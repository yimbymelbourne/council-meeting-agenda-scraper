import datetime
import json
import re

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import (
    BaseScraper,
    ScraperReturn,
    register_scraper,
)
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.gleneira.vic.gov.au"
_LISTING_URL = (
    "https://www.gleneira.vic.gov.au"
    "/about-council/meetings-and-agendas/council-agendas-and-minutes"
    "?year={year}"
)
_LISTING_PAGE_URL = (
    "https://www.gleneira.vic.gov.au"
    "/about-council/meetings-and-agendas/council-agendas-and-minutes"
    "?page={page}&year={year}"
)

# The page embeds pagination info in a ReactDOM.hydrate() script block as JSON.
# Matches: "initialPagination":{"totalItems":19,"page":1,...,"totalPages":2,...}
_PAGINATION_RE = re.compile(r'"initialPagination"\s*:\s*(\{[^}]+\})')


def _abs(href: str) -> str:
    """Return an absolute URL, prepending base if needed."""
    if href.startswith("http"):
        return href
    return _BASE_URL + href


@register_scraper
class GlenEiraScraper(BaseScraper):
    def __init__(self):
        super().__init__("glen_eira", "VIC", _BASE_URL)
        self.default_location = "420 Glen Eira Road, Caulfield"

    def _extract_meeting_links(self, html: str, seen: set) -> list[str]:
        """Return new meeting page hrefs found in html, updating seen in place."""
        soup = BeautifulSoup(html, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if re.search(r"/council-agendas-and-minutes/[^/?#]+", href) and href not in seen:
                seen.add(href)
                links.append(href)
        return links

    def _total_pages(self, html: str) -> int:
        """Extract totalPages from the embedded React pagination JSON, default 1."""
        m = _PAGINATION_RE.search(html)
        if m:
            try:
                data = json.loads(m.group(1))
                return int(data.get("totalPages", 1))
            except (json.JSONDecodeError, ValueError):
                pass
        return 1

    def _parse_year(self, year: int) -> list[ScraperReturn]:
        # Fetch page 1 and find out how many pages there are
        page1_url = _LISTING_URL.format(year=year)
        page1_html = self.fetcher.fetch_with_requests(page1_url)
        total_pages = self._total_pages(page1_html)

        seen: set = set()
        meeting_links = self._extract_meeting_links(page1_html, seen)

        for page in range(2, total_pages + 1):
            page_url = _LISTING_PAGE_URL.format(page=page, year=year)
            page_html = self.fetcher.fetch_with_requests(page_url)
            meeting_links.extend(self._extract_meeting_links(page_html, seen))

        results = []
        for href in meeting_links:
            meeting_url = _abs(href)
            meeting_html = self.fetcher.fetch_with_requests(meeting_url)
            meeting_soup = BeautifulSoup(meeting_html, "html.parser")

            # Date and time from page content
            page_text = meeting_soup.get_text(" ", strip=True)
            date_match = self.date_regex.search(page_text)
            time_match = self.time_regex.search(page_text)
            date = date_match.group() if date_match else None
            time = time_match.group() if time_match else None

            # Derive meeting type from URL slug (reliable across all years).
            # e.g. ".../ordinary-council-meeting-tuesday-..." → "Ordinary Council Meeting"
            slug = href.rstrip("/").split("/")[-1]
            slug_lower = slug.lower()
            if slug_lower.startswith("special-"):
                name = "Special Council Meeting"
            elif slug_lower.startswith("ordinary-"):
                name = "Ordinary Council Meeting"
            else:
                # Capitalise each word as a fallback
                name = slug.replace("-", " ").title()

            # Find all PDF links; classify as agenda or minutes by link text
            agenda_url = None
            minutes_url = None
            for a in meeting_soup.find_all("a", href=True):
                if not a["href"].lower().endswith(".pdf"):
                    continue
                link_text = a.get_text(strip=True).lower()
                full_url = _abs(a["href"])
                if "agenda" in link_text and agenda_url is None:
                    agenda_url = full_url
                elif "minutes" in link_text and minutes_url is None:
                    minutes_url = full_url

            if not agenda_url and not minutes_url:
                continue

            results.append(
                ScraperReturn(
                    name=name,
                    date=date,
                    time=time,
                    webpage_url=meeting_url,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                    location=self.default_location,
                )
            )

        return results

    def scraper(self) -> list[ScraperReturn]:
        current_year = clock.current_year()
        years_filter = getattr(self, "years_filter", None)

        if years_filter:
            years_to_fetch = sorted(years_filter, reverse=True)
        else:
            years_to_fetch = range(current_year, EARLIEST_YEAR - 1, -1)

        all_results: list[ScraperReturn] = []
        for year in years_to_fetch:
            all_results.extend(self._parse_year(year))

        return all_results


if __name__ == "__main__":
    scraper = GlenEiraScraper()
    for r in scraper.scraper():
        print(r)
