import datetime
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.mansfield.vic.gov.au"
_LISTING_URL = f"{_BASE_URL}/council/council-meetings"

# Mansfield (Drupal 11) lists its meetings newest first, nine to a page
# (`?page=0` onwards), each card linking a page per meeting titled "15
# September 2026 Ordinary Council Meeting" or "... Additional Council
# Meeting". Both are meetings of the Council, so both are read. The site
# holds nothing older than 16 July 2024: the listing ends there, and the
# sitemap has no other meeting pages.
#
# The documents are only on the meeting pages, in sections headed Agenda,
# Minutes and Related attachments. The first two each link one PDF
# ("Council Meeting Agenda 15 September 2026 (PDF, 598KB)"); the third holds
# the numbered item attachments, which include other bodies' minutes
# ("15.1.1 Audit And Risk Committee Meeting Minutes ...") and are never
# taken as the meeting's.
#
# The listing stops being read once a page reaches back past the earliest
# wanted year, so a production year costs the listing pages that reach it
# (two) and a page per meeting in it (about 14).
#
# robots.txt (checked 20 Oct 2026) disallows /search but not the listing,
# its `?page=` pager or the meeting pages.

_MAX_PAGES = 20

_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october"
    "|november|december"
)
_TITLE = re.compile(
    rf"^\s*(\d{{1,2}})\s+({_MONTHS})\s+(\d{{4}})\s+(.+?)\s*$", re.IGNORECASE
)
_SECTION = re.compile(r"^\s*(agenda|minutes)\s*$", re.IGNORECASE)


def _parse_title(text: str) -> Optional[tuple[datetime.date, str]]:
    match = _TITLE.match(text)
    if not match:
        return None
    month = _MONTHS.split("|").index(match[2].lower()) + 1
    try:
        return datetime.date(int(match[3]), month, int(match[1])), match[4]
    except ValueError:
        return None


@register_scraper
class MansfieldScraper(BaseScraper):
    # One production year, measured 20 Oct 2026 from a home IP through
    # main.py: 16 requests (two listing pages, 14 meetings), 30 s. Orders
    # dispatch only; see BaseScraper.expected_seconds.
    expected_seconds = 30

    def __init__(self):
        super().__init__("mansfield", "VIC", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _soup(self, url: str) -> BeautifulSoup:
        return BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")

    def _listed(self, wanted: set[int]) -> list[tuple[datetime.date, str, str]]:
        """(date, meeting type, page) for every listed meeting in a wanted year."""
        listed = []
        for page in range(_MAX_PAGES):
            url = _LISTING_URL if page == 0 else f"{_LISTING_URL}?page={page}"
            cards = self._soup(url).select("h3.node--card__title")
            if not cards:
                if page == 0:
                    # The first page always lists the latest meetings, so an
                    # empty one means the layout changed.
                    raise ValueError(f"{self.council_name}: no meetings on {url}")
                return listed
            dates = []
            for card in cards:
                parsed = _parse_title(card.get_text(" ", strip=True))
                link = card.find_parent("a", href=True) or card.find("a", href=True)
                if parsed is None or link is None:
                    continue
                date, meeting_type = parsed
                dates.append(date)
                if date.year in wanted:
                    listed.append((date, meeting_type, urljoin(url, link["href"])))
            # Newest first, so once a page reaches back past the earliest
            # wanted year, later pages hold nothing wanted.
            if dates and min(dates).year < min(wanted):
                return listed
        self.logger.warning(
            f"{self.council_name}: stopped at {_MAX_PAGES} listing pages; "
            f"there may be more meetings"
        )
        return listed

    @staticmethod
    def _papers(soup: BeautifulSoup, page_url: str) -> dict[str, Optional[str]]:
        papers: dict[str, Optional[str]] = {"agenda": None, "minutes": None}
        # Each section is an `li.council-meeting__doc-item` holding its own
        # `h2` and, for Agenda and Minutes, a single link.
        for item in soup.select("li.council-meeting__doc-item"):
            link = item.find("a", href=True)
            heading = item.select_one("h2.council-meeting__section-title")
            match = (
                _SECTION.match(heading.get_text(" ", strip=True)) if heading else None
            )
            if not link or not match:
                continue
            kind = match[1].lower()
            href = urljoin(page_url, link["href"])
            if papers[kind] is None and href.lower().endswith(".pdf"):
                papers[kind] = href
        return papers

    @staticmethod
    def _time(soup: BeautifulSoup, date: datetime.date) -> Optional[str]:
        """The start time, when the page's own date agrees with the title's.

        The 20 October 2026 page gives "Thu, Oct 15 2026, 5:11", five days
        before the meeting its title names, so a time is only taken from a
        `<time>` whose date is the meeting's.
        """
        stamp = soup.select_one(".council-meeting__date time[datetime]")
        if not stamp:
            return None
        try:
            start = datetime.datetime.fromisoformat(stamp["datetime"])
        except ValueError:
            return None
        if start.date() != date:
            return None
        return start.strftime("%H:%M")

    @staticmethod
    def _location(soup: BeautifulSoup) -> Optional[str]:
        block = soup.select_one(".council-meeting__location-info")
        if not block:
            return None
        lines = [line.strip() for line in block.get_text("\n").split("\n")]
        lines = [line for line in lines if line and line != "Australia"]
        return ", ".join(lines) or None

    def scraper(self) -> list[ScraperReturn]:
        wanted = self._wanted_years()
        results = []
        held = 0
        for date, meeting_type, url in self._listed(wanted):
            soup = self._soup(url)
            papers = self._papers(soup, url)
            if date < clock.today():
                held += 1
            if not papers["agenda"] and not papers["minutes"]:
                continue
            results.append(
                ScraperReturn(
                    name=meeting_type,
                    date=date.isoformat(),
                    time=self._time(soup, date),
                    webpage_url=url,
                    agenda_url=papers["agenda"],
                    minutes_url=papers["minutes"],
                    location=self._location(soup),
                    download_url=papers["agenda"] or papers["minutes"],
                )
            )
        if held and not results:
            # Every meeting already held has its agenda posted, so pages read
            # for held meetings with no Agenda or Minutes among them mean the
            # sections' markup changed, not a year without papers.
            raise ValueError(
                f"{self.council_name}: {held} meeting pages read, "
                f"none with an agenda or minutes"
            )
        return results
