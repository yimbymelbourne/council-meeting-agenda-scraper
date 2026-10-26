import datetime
import re
from typing import Optional

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://laverton.wa.gov.au"
# WordPress (Avada) renders every post of its "council-meeting" type on this
# one page as a post card, 2017 onwards: date and time, a code
# (OMC240926), the meeting type, a location, and Agenda/Minutes/Recording
# buttons straight to the PDFs. The shorter /governing/council-meetings/
# shows only recent cards. The REST API has the post type but not the
# document fields, so the page is the only source. robots.txt disallows the
# page's date and search filters (`?date_from=`, `?srch=`), never needed here.
_LISTING_URL = f"{_BASE_URL}/governing/council-meeting-minutes/"
_WHEN = re.compile(
    r"^[A-Za-z]+,\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})(?:\s*-\s*(\d{1,2}:\d{2}\s*[AP]M))?",
    re.IGNORECASE,
)


@register_scraper
class LavertonScraper(BaseScraper):
    def __init__(self):
        super().__init__("laverton", "WA", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _card(card) -> Optional[dict]:
        headings = [h.get_text(" ", strip=True) for h in card.select(".fusion-title-heading")]
        when = next((m for h in headings if (m := _WHEN.match(h))), None)
        if not when:
            # The page's navigation tiles are post cards too.
            return None
        date = parse_date(when.group(1)).date()
        time = when.group(2)
        # Old cards carry a placeholder midnight ("June 28, 2018 - 12:00 AM").
        if time and re.fullmatch(r"12:00\s*AM", time, re.IGNORECASE):
            time = None

        name = location = None
        for item in card.select(".fusion-li-item"):
            text = item.get_text(" ", strip=True)
            if item.select_one(".fa-map-marker-alt"):
                location = text
            elif item.select_one(".fa-comments"):
                name = text

        papers: dict[str, str] = {}
        for anchor in card.select("a.fusion-button[href]"):
            label = anchor.get_text(" ", strip=True).lower()
            href = anchor["href"].strip()
            if label in ("agenda", "minutes") and href.lower().endswith(".pdf"):
                papers.setdefault(label, href)
        return {
            "date": date,
            "time": time,
            "name": name,
            "location": location,
            "agenda": papers.get("agenda"),
            "minutes": papers.get("minutes"),
        }

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # Left to raise: this page is the only request, and failing quietly
        # would report the council as having no meetings.
        html = self.fetcher.fetch_with_requests(_LISTING_URL)
        soup = BeautifulSoup(html, "html.parser")

        results = []
        for card in soup.select("li.post-card"):
            meeting = self._card(card)
            if not meeting or meeting["date"].year not in wanted:
                continue
            if not (meeting["agenda"] or meeting["minutes"]):
                # A card with no papers (OMC150525) is a meeting with
                # nothing to read.
                continue
            results.append(
                ScraperReturn(
                    name=meeting["name"] or "Council Meeting",
                    date=meeting["date"].isoformat(),
                    time=meeting["time"],
                    webpage_url=_LISTING_URL,
                    agenda_url=meeting["agenda"],
                    minutes_url=meeting["minutes"],
                    download_url=meeting["agenda"] or meeting["minutes"],
                    location=meeting["location"],
                )
            )

        if not results:
            self.logger.warning(
                f"{self.council_name} found no meetings for {sorted(wanted)}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
