import json
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.aurukun.qld.gov.au"
_LANDING_URL = f"{_BASE_URL}/council/documents/council-minutes/"
_MEDIA_API = f"{_BASE_URL}/wp-json/wp/v2/media"

# Aurukun Shire's papers are on a WordPress (Divi) page per year, linked from
# the landing page as "2026 Meetings", "2025 Meetings" and so on. Their slugs
# change from era to era (/meetings-and-agendas-2026/, /council-meetings-2024/,
# /council/documents/council-minutes-2021/), so they are read off the landing
# page rather than built.
#
# From 2021 each paper is a Divi text card reading "Agenda | Ordinary
# Meeting | 17 March", and the card's link is not an <a>: Divi makes the card
# clickable from a script array, `et_link_options_data = [{"class":
# "et_pb_text_5", "url": ...}]`, keyed by the card's class. A plain link scrape
# finds almost nothing. The 2020 page is older, plain links reading "Ordinary
# Meeting 18 February", minutes only.
#
# Most card URLs are WordPress attachment pages (/co_20260421_agn_54_at/), not
# the PDF. The REST media endpoint answers for a batch of slugs at once with
# each one's `source_url`, so a year costs three requests: the landing page,
# the year page and one media lookup. Unpublished papers point at a
# placeholder ("/document-pending/", "Publish-Pending.pdf") and the cancelled
# 27 January 2022 meeting at its cancellation notice; none of those is a
# paper.

_YEAR_LINK = re.compile(r"^(\d{4}) Meetings$")
_LINK_DATA = re.compile(r"et_link_options_data\s*=\s*(\[.*?\]);", re.DOTALL)
_CARD_CLASS = re.compile(r"^et_pb_text_\d+$")
_NOT_A_PAPER = re.compile(r"pending|cancel", re.IGNORECASE)
_DAY_MONTH = re.compile(
    r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b",
    re.IGNORECASE,
)
# 2020: "Special Budget Meeting 29 July", "Post Election Meeting 14 April".
_PLAIN_LINK = re.compile(r"\bMeeting\s+\d{1,2}\s+[A-Za-z]+$", re.IGNORECASE)


@register_scraper
class AurukunScraper(BaseScraper):
    def __init__(self):
        super().__init__("aurukun", "QLD", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        landing = BeautifulSoup(
            self.fetcher.fetch_with_requests(_LANDING_URL), "html.parser"
        )
        year_pages = {}
        for link in landing.find_all("a", href=True):
            match = _YEAR_LINK.match(link.get_text(" ", strip=True))
            if match:
                year_pages.setdefault(
                    int(match.group(1)), urljoin(_LANDING_URL, link["href"])
                )
        if not year_pages:
            raise RuntimeError(f"{self.council_name}: no year pages on {_LANDING_URL}")

        results: list[ScraperReturn] = []
        for year in sorted(self._wanted_years() & set(year_pages), reverse=True):
            page_url = year_pages[year]
            results.extend(self._year(year, page_url))

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results

    def _year(self, year: int, page_url: str) -> list[ScraperReturn]:
        html = self.fetcher.fetch_with_requests(page_url)
        cards = self._cards(html, page_url)

        # (name, date) -> {"agenda": url, "minutes": url}
        meetings: dict[tuple[str, str], dict[str, str]] = {}
        for text, url in cards:
            if _NOT_A_PAPER.search(url):
                continue
            day_month = _DAY_MONTH.search(text)
            if not day_month:
                continue
            try:
                date = parse_date(
                    f"{day_month.group(1)} {day_month.group(2)} {year}"
                ).date()
            except (ValueError, OverflowError):
                self.logger.warning(f"{self.council_name}: no date in {text!r}")
                continue
            kind = self._kind(text, url)
            if kind is None:
                continue
            papers = meetings.setdefault((self._name(text), date.isoformat()), {})
            papers.setdefault(kind, url)

        resolved = self._resolve(
            {url for papers in meetings.values() for url in papers.values()}
        )

        results = []
        for (name, date), papers in meetings.items():
            agenda_url = resolved.get(papers.get("agenda"))
            minutes_url = resolved.get(papers.get("minutes"))
            if not agenda_url and not minutes_url:
                continue
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

    @staticmethod
    def _cards(html: str, page_url: str) -> list[tuple[str, str]]:
        """(card text, link) for every paper on a year page."""
        soup = BeautifulSoup(html, "html.parser")
        main = soup.select_one("#main-content") or soup
        match = _LINK_DATA.search(html)
        scripted = {}
        if match:
            scripted = {
                entry["class"]: entry["url"] for entry in json.loads(match.group(1))
            }

        cards = []
        for div in main.select("div.et_pb_text"):
            card_class = next(
                (c for c in div.get("class", []) if _CARD_CLASS.match(c)), None
            )
            url = scripted.get(card_class)
            if not url:
                link = div.find("a", href=True)
                url = link["href"] if link else None
            if url:
                cards.append((div.get_text(" | ", strip=True), urljoin(page_url, url)))
        if cards:
            return cards

        # The 2020 page predates the cards.
        for link in main.find_all("a", href=True):
            text = link.get_text(" ", strip=True)
            if _PLAIN_LINK.search(text):
                cards.append((text, urljoin(page_url, link["href"])))
        return cards

    @staticmethod
    def _kind(text: str, url: str) -> Optional[str]:
        head = text.split("|", 1)[0].lower()
        if head.startswith("minute"):
            return "minutes"
        if head.startswith("agenda"):
            return "agenda"
        # 2020's plain links name only the meeting; the page holds minutes.
        lowered = url.lower()
        if "agenda" in lowered:
            return "agenda"
        if "min" in lowered:
            return "minutes"
        return None

    @staticmethod
    def _name(text: str) -> str:
        lowered = text.lower()
        if "special" in lowered:
            return "Special Council Meeting"
        if "post election" in lowered:
            return "Post-Election Meeting"
        # "Ordinary Meeting | Budget Meeting" is the July ordinary meeting,
        # which adopts the budget.
        return "Ordinary Council Meeting"

    def _resolve(self, urls: set[str]) -> dict[str, str]:
        """Map each card link to its PDF.

        A link into /wp-content/uploads/ is the PDF already. Any other is a
        WordPress attachment page, whose slug the media endpoint resolves.
        A slug the endpoint does not know is left out with a warning rather
        than emitted as a web page posing as a document.
        """
        resolved = {url: url for url in urls if "/wp-content/uploads/" in url}
        slugs = {
            urlparse(url).path.strip("/").rsplit("/", 1)[-1]: url
            for url in urls
            if url not in resolved
        }
        if not slugs:
            return resolved
        body = self.fetcher.fetch_with_requests(
            _MEDIA_API,
            params={
                "slug": ",".join(sorted(slugs)),
                "per_page": 100,
                "_fields": "slug,source_url",
            },
        )
        for item in json.loads(body):
            url = slugs.get(item.get("slug"))
            if url and item.get("source_url"):
                resolved[url] = item["source_url"]
        for slug, url in slugs.items():
            if url not in resolved:
                self.logger.warning(
                    f"{self.council_name}: {url} is not a media attachment; leaving it out"
                )
        return resolved
