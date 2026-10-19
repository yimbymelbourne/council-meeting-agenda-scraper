import datetime
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.ararat.vic.gov.au"
_INDEX_URL = f"{_BASE_URL}/council/council-meetings"

# Ararat (Drupal 10, behind Cloudflare) has three levels:
#
# * /council/council-meetings links one card per year, "2026 Council
#   Meetings". Years start at 2022; nothing older is online.
# * Each year page links one card per meeting: a title ("Council Meeting -
#   29 April 2025", "Statutory Council Meeting - 11 November 2025") and a
#   description giving its kind ("Ordinary Meeting", "Unscheduled Council
#   Meeting"). Paths are inconsistent (/2026-council-meetings,
#   /council-meeting-25-august-2026, /council/council-meetings/council-
#   meeting-29-april-2025), so links are followed, never built.
# * Each meeting page has headed sections, Agenda, Attachments and Minutes
#   (on two statutory meetings, "Statutory Agenda" and "Statutory Minutes").
#   The agenda and minutes links carry the same text ("Council Meeting - 29
#   September 2026"), so a link is classified by the heading above it.
#
# Every meeting the council lists is a meeting of the Council itself, so all
# are read. A production year costs the index, the year page and a page per
# meeting: 11 requests for 2026 so far, up to about 15 in a busy year.
#
# robots.txt (checked 20 Oct 2026) is Drupal's default and disallows none of
# these paths.

_YEAR_CARD = re.compile(r"\b(20\d{2})\s+Council Meetings\b", re.IGNORECASE)
_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october"
    "|november|december"
)
_DATE = re.compile(rf"\b(\d{{1,2}})\s+({_MONTHS})\s+(\d{{4}})\b", re.IGNORECASE)
# The statutory meetings of 8 November 2022 and 14 November 2023 head their
# sections "Statutory Agenda" and "Statutory Minutes", so a qualifier before
# the section's own word is allowed.
_SECTION = re.compile(
    r"^\s*(?:(?:statutory|special|unscheduled|council)\s+)?"
    r"(agenda|minutes|attachments?)\s*$",
    re.IGNORECASE,
)


def _parse_date(text: str) -> Optional[datetime.date]:
    match = _DATE.search(text)
    if not match:
        return None
    month = _MONTHS.split("|").index(match[2].lower()) + 1
    try:
        return datetime.date(int(match[3]), month, int(match[1]))
    except ValueError:
        return None


def _meeting_name(title: str, description: str) -> str:
    """The kind of meeting, from the card's title and description.

    The description says "Ordinary Meeting", "Unscheduled Meeting" or
    "Unscheduled Council Meeting" (Ararat's word for a special meeting), or
    nothing on most 2026 cards, which are all ordinary meetings so far.
    """
    text = f"{title} {description}".lower()
    if "statutory" in text:
        return "Statutory Council Meeting"
    if "unscheduled" in text:
        return "Unscheduled Council Meeting"
    return "Ordinary Council Meeting"


def _papers(soup: BeautifulSoup, page_url: str) -> tuple[Optional[str], Optional[str]]:
    """The (agenda, minutes) PDFs on a meeting page, by the heading above each."""
    content = soup.find("main") or soup.body or soup
    found: dict[str, Optional[str]] = {"agenda": None, "minutes": None}
    for link in content.find_all("a", href=True):
        href = urljoin(page_url, link["href"])
        if not href.lower().endswith(".pdf"):
            continue
        heading = link.find_previous(["h2", "h3", "h4"])
        match = _SECTION.match(heading.get_text(" ", strip=True)) if heading else None
        if not match:
            continue
        section = match[1].lower()
        if section in found and found[section] is None:
            found[section] = href
    return found["agenda"], found["minutes"]


@register_scraper
class AraratScraper(BaseScraper):
    # One production year, measured 20 Oct 2026 from a home IP through
    # main.py: 11 requests (index, year page, nine meetings), 21 s. Orders
    # dispatch only; see BaseScraper.expected_seconds.
    expected_seconds = 21

    def __init__(self):
        super().__init__("ararat", "VIC", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _soup(self, url: str) -> BeautifulSoup:
        return BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")

    @staticmethod
    def _cards(soup: BeautifulSoup, page_url: str) -> list[tuple[str, str, str]]:
        """(title, description, url) for each card on an index or year page."""
        cards = []
        for card in soup.select("div.card"):
            link = card.find("a", href=True)
            title = card.select_one(".card__title")
            if not link or not title:
                continue
            description = card.select_one(".card__desc")
            cards.append(
                (
                    title.get_text(" ", strip=True),
                    description.get_text(" ", strip=True) if description else "",
                    urljoin(page_url, link["href"]),
                )
            )
        return cards

    def scraper(self) -> list[ScraperReturn]:
        wanted = self._wanted_years()
        year_pages = {}
        for title, _, url in self._cards(self._soup(_INDEX_URL), _INDEX_URL):
            if match := _YEAR_CARD.search(title):
                year_pages.setdefault(int(match[1]), url)
        if not year_pages:
            # The index always links the years it holds, so none means the
            # layout changed.
            raise ValueError(f"{self.council_name}: no year pages on {_INDEX_URL}")

        results = []
        for year, year_url in sorted(year_pages.items()):
            if year not in wanted:
                continue
            for title, description, url in self._cards(self._soup(year_url), year_url):
                date = _parse_date(title)
                if date is None or date.year not in wanted:
                    continue
                agenda, minutes = _papers(self._soup(url), url)
                if not agenda and not minutes:
                    # A meeting not yet held may have nothing posted. One
                    # already held with nothing found is more likely a
                    # heading this does not recognise, so it is said.
                    if date < clock.today():
                        self.logger.warning(
                            f"{self.council_name}: no agenda or minutes found on {url}"
                        )
                    continue
                results.append(
                    ScraperReturn(
                        name=_meeting_name(title, description),
                        date=date.isoformat(),
                        time=None,
                        webpage_url=url,
                        agenda_url=agenda,
                        minutes_url=minutes,
                        download_url=agenda or minutes,
                    )
                )
        return results
