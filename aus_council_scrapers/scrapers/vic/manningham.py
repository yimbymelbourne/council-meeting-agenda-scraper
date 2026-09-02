from aus_council_scrapers.base import (
    BROWSER_USER_AGENT,
    BaseScraper,
    ScraperReturn,
    register_scraper,
)
from aus_council_scrapers.constants import EARLIEST_YEAR
from bs4 import BeautifulSoup
import re
from datetime import datetime
from urllib.parse import urljoin


@register_scraper
class ManninghamScraper(BaseScraper):
    # Manningham's CloudFront rules run the opposite way to most councils':
    # they serve a browser-shaped client and 403 an identifying one (measured
    # 2026-08-20 — 200 with 364KB against a 919-byte 403). It is the only
    # council in the project that needs this, and the override is deliberately
    # per-scraper so the project-wide identifying default stays put.
    user_agent = BROWSER_USER_AGENT

    def __init__(self):
        council_name = "manningham"
        state = "VIC"
        base_url = "https://www.manningham.vic.gov.au"
        super().__init__(council_name, state, base_url)
        self.webpage_url = "https://www.manningham.vic.gov.au/about-council/how-council-works/council-meetings"

    def _get_meeting_links(self) -> list[str]:
        """Return all council meeting page URLs from the listings page."""
        html = self.fetcher.fetch_with_requests(self.webpage_url)
        soup = BeautifulSoup(html, "html.parser")
        urls = []
        seen = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            txt = a.get_text(strip=True)
            if "council-meeting" in href.lower() and "events" in href.lower():
                full_url = urljoin(self.base_url, href)
                if full_url not in seen:
                    seen.add(full_url)
                    urls.append(full_url)
        return urls

    def _parse_meeting_page(self, url: str) -> ScraperReturn | None:
        """Fetch a meeting page and extract agenda/minutes info."""
        html = self.fetcher.fetch_with_requests(url)
        soup = BeautifulSoup(html, "html.parser")

        # Date and time: prefer ICS export (upcoming meetings), fall back to page title
        ics = soup.find("a", class_="js-ics-export")
        if ics:
            datetime_str = ics.get("data-ics-start", "")
            try:
                dt = datetime.strptime(datetime_str, "%Y-%m-%d %I:%M %p")
                date = dt.strftime("%Y-%m-%d")
                time = dt.strftime("%H:%M")
            except ValueError:
                return None
        else:
            # Past meetings: parse date from the page title
            h1 = soup.find("h1", class_="page-title")
            if not h1:
                return None
            title_text = h1.get_text(strip=True)
            date_match = re.search(self.date_regex, title_text)
            if not date_match:
                return None
            try:
                dt = datetime.strptime(date_match.group(), "%d %B %Y")
            except ValueError:
                try:
                    dt = datetime.strptime(date_match.group().lstrip("0"), "%d %B %Y")
                except ValueError:
                    return None
            date = dt.strftime("%Y-%m-%d")
            time = None

        if dt.year < EARLIEST_YEAR:
            return None

        # Title
        h1_el = soup.find("h1", class_="page-title")
        name_raw = h1_el.get_text(strip=True) if h1_el else ""
        date_match_name = re.search(self.date_regex, name_raw)
        name = name_raw.replace(date_match_name.group(), "").strip() if date_match_name else name_raw

        # Location
        addr = soup.find("p", class_="address")
        location = addr.get_text(" ", strip=True) if addr else None

        # Agenda and minutes from media download blocks
        agenda_url = None
        minutes_url = None
        for media in soup.find_all("div", class_="media--view-mode-download"):
            title_div = media.find("div", class_="file--details")
            file_link = media.find("a", class_="file-link")
            if not title_div or not file_link:
                continue
            title = title_div.get_text(strip=True).lower()
            href = file_link.get("href", "")
            if not href:
                continue
            if "council agenda" in title and agenda_url is None:
                agenda_url = href
            elif "council minutes" in title and minutes_url is None:
                minutes_url = href

        if not agenda_url and not minutes_url:
            return None

        return ScraperReturn(
            name=name,
            date=date,
            time=time,
            webpage_url=url,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url,
            location=location,
        )

    def scraper(self) -> list[ScraperReturn]:
        meeting_urls = self._get_meeting_links()

        years_filter = getattr(self, "years_filter", None)
        allowed_years = set(years_filter) if years_filter else None

        results = []
        urls_to_fetch = []
        for url in meeting_urls:
            year_in_url = re.search(r"-(\d{4})(?:-\w+)?$", url)
            if not year_in_url:
                continue
            year = int(year_in_url.group(1))
            if year < EARLIEST_YEAR:
                continue
            if allowed_years and year not in allowed_years:
                continue
            urls_to_fetch.append(url)

        self.logger.info(f"Found {len(urls_to_fetch)} meeting links to fetch")
        for url in urls_to_fetch:
            try:
                record = self._parse_meeting_page(url)
                if record:
                    results.append(record)
            except Exception as e:
                self.logger.debug(f"Error parsing {url}: {e}")

        results.sort(key=lambda x: x.date, reverse=True)
        return results


if __name__ == "__main__":
    scraper = ManninghamScraper()
    scraper.scraper()
