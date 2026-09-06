import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.yarracity.vic.gov.au"
_INDEX_URL = (
    "https://www.yarracity.vic.gov.au"
    "/about-us/council-and-committee-meetings/council-meetings"
)

# Every meeting Yarra has held since 2016 is linked from the one index page,
# as "<date> Council Meeting" pointing at a page per meeting. The documents
# live only on those pages, so the year bound is what keeps the fetch count
# sane: one request per meeting in range.
_MEETING_PATH = "/about-us/committees-meetings-and-minutes/"

_AGENDA_LABEL = re.compile(r"^\s*agenda\b", re.IGNORECASE)
_MINUTES_LABEL = re.compile(r"^\s*minutes\b", re.IGNORECASE)
_DOCUMENTS_HEADING = re.compile(r"^\s*Documents\s*$", re.IGNORECASE)
_WHERE_HEADING = re.compile(r"^\s*Where\s*$", re.IGNORECASE)


@register_scraper
class YarraScraper(BaseScraper):
    def __init__(self):
        council = "yarra"
        state = "VIC"
        base_url = _BASE_URL
        super().__init__(council, state, base_url)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _meeting_links(self, index_html: str) -> list[tuple[int, str, str]]:
        """Return (year, link text, url) for each meeting page, newest first."""
        soup = BeautifulSoup(index_html, "html.parser")
        wanted = self._wanted_years()

        found: dict[str, tuple[int, str]] = {}
        for link in soup.find_all("a", href=True):
            url = urljoin(_INDEX_URL, link["href"])
            if _MEETING_PATH not in url or url in found:
                continue

            text = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            date_match = self.date_regex.search(text)
            if not date_match:
                continue

            year = parse_date(date_match.group(), dayfirst=True).year
            if year in wanted:
                found[url] = (year, text)

        meetings = [(year, text, url) for url, (year, text) in found.items()]
        meetings.sort(key=lambda m: m[0], reverse=True)
        return meetings

    def _documents(self, soup: BeautifulSoup, page_url: str) -> tuple[str, str]:
        """The meeting's agenda and minutes, from the Documents section.

        The section also carries a recording link and the venue's map links,
        so match on the label rather than taking every link under it.
        """
        heading = soup.find(["h2", "h3"], string=_DOCUMENTS_HEADING)
        if not heading:
            return None, None

        agenda_url = None
        minutes_url = None
        for link in (heading.parent or soup).find_all("a", href=True):
            label = link.get_text(" ", strip=True)
            href = urljoin(page_url, link["href"])
            if agenda_url is None and _AGENDA_LABEL.match(label):
                agenda_url = href
            elif minutes_url is None and _MINUTES_LABEL.match(label):
                minutes_url = href
        return agenda_url, minutes_url

    @staticmethod
    def _location(soup: BeautifulSoup) -> str:
        """The venue, from the block under the "Where" heading.

        That block wraps the address in "View map" and "Get directions" links,
        which are not part of it.
        """
        heading = soup.find(["h2", "h3"], string=_WHERE_HEADING)
        block = heading.find_next_sibling() if heading else None
        if not block:
            return None

        block = BeautifulSoup(str(block), "html.parser")
        for link in block.find_all("a"):
            link.decompose()
        location = re.sub(r"\s+", " ", block.get_text(" ", strip=True))
        return location or None

    def _meeting(self, url: str, link_text: str) -> ScraperReturn:
        html = self.fetcher.fetch_with_requests(url)
        soup = BeautifulSoup(html, "html.parser")

        agenda_url, minutes_url = self._documents(soup, url)
        if not agenda_url and not minutes_url:
            # A meeting scheduled but not yet papered.
            return None

        # The page states the meeting time in a machine-readable <time>; the
        # index only ever gives the date, and a handful of older pages have no
        # <time> at all.
        time_element = soup.find("time")
        stamp = time_element.get("datetime") if time_element else None
        if stamp:
            when = parse_date(stamp)
            time = when.strftime("%I:%M %p").lstrip("0")
        else:
            when = parse_date(self.date_regex.search(link_text).group(), dayfirst=True)
            time = None
        date = when.date().isoformat()

        heading = soup.find("h1")
        name = heading.get_text(" ", strip=True) if heading else link_text
        name = re.sub(r"\s+", " ", self.date_regex.sub("", name)).strip(" -–—")

        return ScraperReturn(
            name=name or "Council Meeting",
            date=date,
            time=time,
            webpage_url=url,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
            location=self._location(soup),
        )

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        index_html = self.fetcher.fetch_with_requests(_INDEX_URL)
        meetings = self._meeting_links(index_html)
        self.logger.debug(f"{len(meetings)} meeting page(s) in range")

        results = []
        for _, link_text, url in meetings:
            try:
                meeting = self._meeting(url, link_text)
            except Exception as e:
                self.logger.warning(f"Could not read {url}: {e}")
                continue
            if meeting:
                results.append(meeting)

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
