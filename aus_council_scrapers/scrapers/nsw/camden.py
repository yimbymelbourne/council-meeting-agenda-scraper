import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_INDEX_URL = "https://www.camden.nsw.gov.au/council/council-meetings"

# The index links a page per year, labelled "<year> Business Papers and Minutes".
# Read the year off the label rather than the href: the slugs were never
# renamed as years rolled over, so 2024 lives at
# `2022-business-papers-and-minutes-3` and 2021 at
# `2020-business-papers-and-minutes-2`.
_YEAR_LINK = re.compile(r"^\s*(\d{4})\s+Business Papers", re.IGNORECASE)

# On a year page each meeting is an `h2` holding just the date, followed by the
# links to that meeting's documents until the next `h2`.
_MEETING_DATE = re.compile(
    r"\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September"
    r"|October|November|December)\s+\d{4}",
    re.IGNORECASE,
)

# "Business Paper" is Camden's word for the agenda. Attachments and mayoral
# minutes sit alongside it under the same heading and are not the meeting's
# agenda or minutes.
_AGENDA_LABEL = re.compile(r"business paper|agenda", re.IGNORECASE)
_MINUTES_LABEL = re.compile(
    r"^\s*(?:draft\s+|unconfirmed\s+|confirmed\s+)?minutes", re.IGNORECASE
)


@register_scraper
class CamdenScraper(BaseScraper):
    def __init__(self):
        council = "camden"
        state = "NSW"
        base_url = "https://www.camden.nsw.gov.au"
        super().__init__(council, state, base_url)
        self.default_location = "70 Central Ave, Oran Park NSW 2570"
        self.default_time = "18:30"

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _year_pages(self, index_html: str) -> dict[int, str]:
        """Map year -> year-page URL, for the years we want."""
        soup = BeautifulSoup(index_html, "html.parser")
        wanted = self._wanted_years()

        pages: dict[int, str] = {}
        for link in soup.find_all("a", href=True):
            match = _YEAR_LINK.match(link.get_text(" ", strip=True))
            if not match:
                continue
            year = int(match.group(1))
            if year not in wanted or year in pages:
                continue
            # Some of these hrefs are absolute and some are site-relative;
            # concatenating blindly is what produced
            # `camden.nsw.gov.au/https://www.camden.nsw.gov.au/...` and a 404.
            pages[year] = urljoin(_INDEX_URL, link["href"])
        return pages

    @staticmethod
    def _meeting_name(heading_text: str) -> str:
        """Turn a heading into a meeting name.

        Most headings are the bare date. The rest qualify it, usually as
        "12 May 2026 (Extraordinary)", which is a meeting type rather than a
        name until "Council Meeting" is put back on it.
        """
        qualifier = _MEETING_DATE.sub("", heading_text).strip(" -–—()")
        if not qualifier:
            return "Council Meeting"
        if "meeting" in qualifier.lower():
            return qualifier
        return f"{qualifier} Council Meeting"

    def _meetings_on_page(self, html: str, page_url: str) -> list[ScraperReturn]:
        soup = BeautifulSoup(html, "html.parser")
        results = []

        # These headings are peppered with non-breaking spaces, which would
        # otherwise end up inside the date string we emit.
        headings = []
        for heading in soup.find_all("h2"):
            text = re.sub(r"\s+", " ", heading.get_text(" ", strip=True))
            date_match = _MEETING_DATE.search(text)
            if date_match:
                headings.append((heading, text, date_match.group()))

        boundaries = {id(heading) for heading, _, _ in headings}

        for heading, heading_text, date in headings:
            agenda_url = None
            minutes_url = None
            for element in heading.find_next_siblings():
                if id(element) in boundaries:
                    break
                for link in element.find_all("a", href=True):
                    label = link.get_text(" ", strip=True)
                    href = urljoin(page_url, link["href"])
                    if minutes_url is None and _MINUTES_LABEL.search(label):
                        minutes_url = href
                    elif agenda_url is None and _AGENDA_LABEL.search(label):
                        agenda_url = href

            if not agenda_url and not minutes_url:
                continue

            name = self._meeting_name(heading_text)

            results.append(
                ScraperReturn(
                    name=name,
                    date=date,
                    time=None,
                    webpage_url=page_url,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        return results

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        index_html = self.fetcher.fetch_with_requests(_INDEX_URL)
        year_pages = self._year_pages(index_html)

        results: list[ScraperReturn] = []
        for year in sorted(year_pages):
            url = year_pages[year]
            try:
                html = self.fetcher.fetch_with_requests(url)
            except Exception as e:
                # A year the council has not published a page for yet.
                self.logger.warning(f"Could not fetch {year} papers at {url}: {e}")
                continue
            found = self._meetings_on_page(html, url)
            self.logger.debug(f"{year}: {len(found)} meeting(s)")
            results.extend(found)

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
