import datetime
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.wentworth.nsw.gov.au"
_LISTING_URL = f"{_BASE_URL}/council/about-the-shire/council-meetings/minutes-agenda/"

# One WordPress (Enfold) page with a toggle per meeting, newest first. The
# toggle title carries the date and type ("21 October 2026 - Ordinary
# Meeting"); its panel has an h2 naming the meeting, a "Time / Location"
# paragraph and the documents.
#
# The council keeps only about twelve months online ("Council generally only
# keeps 12 months of meeting minutes and agendas"), so the fixture's history
# starts in February 2025 and older meetings drop off the page as new ones
# are added. Nothing older is published anywhere on the site.
_DAY_MONTH_YEAR = re.compile(
    r"(?<!\d)(\d{1,2})\s+(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+(\d{4})(?!\d)",
    re.IGNORECASE,
)
_MINUTES = re.compile(r"\bminutes\b", re.IGNORECASE)
_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)
# "Supplementary Late Agenda of Ordinary Meeting" and "Late Items Agenda of
# Ordinary Meeting" are extra reports filed beside the agenda, not it.
_NOT_THE_AGENDA = re.compile(r"supplementary|late items?", re.IGNORECASE)
# "4pm at Council Chambers – Wentworth Visitor Centre – 61 Darling Street"
_TIME_AT_PLACE = re.compile(r"^\s*(\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?)\s+at\s+(.+)$", re.IGNORECASE)


def _date(text: str) -> Optional[datetime.date]:
    match = _DAY_MONTH_YEAR.search(text.replace("\xa0", " "))
    if not match:
        return None
    day, month, year = match.groups()
    return datetime.datetime.strptime(f"{day} {month} {year}", "%d %B %Y").date()


@register_scraper
class WentworthScraper(BaseScraper):
    def __init__(self):
        super().__init__("wentworth", "NSW", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _name(title: str, panel) -> str:
        heading = panel.find("h2")
        if heading and heading.get_text(strip=True):
            return heading.get_text(" ", strip=True)
        # "21 October 2026 - Ordinary Meeting" -> "Ordinary Council Meeting"
        qualifier = re.sub(r"^.*?\d{4}\s*[-–—]\s*", "", title).strip()
        qualifier = re.sub(r"\s*meeting$", "", qualifier, flags=re.IGNORECASE)
        return f"{qualifier or 'Ordinary'} Council Meeting"

    @staticmethod
    def _time_and_place(panel) -> tuple[Optional[str], Optional[str]]:
        for heading in panel.find_all("h3"):
            if "location" not in heading.get_text(strip=True).lower():
                continue
            paragraph = heading.find_next_sibling("p")
            text = paragraph.get_text(" ", strip=True) if paragraph else ""
            match = _TIME_AT_PLACE.match(text)
            if match:
                return match.group(1), match.group(2)
            return None, text or None
        return None, None

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # Left to raise on failure: this page is the scraper's only request.
        html = self.fetcher.fetch_with_requests(_LISTING_URL)
        soup = BeautifulSoup(html, "html.parser")

        sections = soup.select("section.av_toggle_section")
        if not sections:
            raise ValueError(
                f"{self.council_name}: no meeting toggles on {_LISTING_URL}"
            )

        results = []
        for section in sections:
            toggler = section.select_one(".toggler")
            panel = section.select_one(".toggle_content")
            if not toggler or not panel:
                continue
            title = toggler.get("data-title") or toggler.get_text(" ", strip=True)
            date = _date(title)
            if not date or date.year not in wanted:
                continue

            agenda_url = None
            minutes_url = None
            for anchor in panel.find_all("a", href=True):
                label = anchor.get_text(" ", strip=True)
                url = urljoin(_LISTING_URL, anchor["href"].strip())
                if not url.lower().endswith(".pdf"):
                    continue
                if _MINUTES.search(label):
                    minutes_url = minutes_url or url
                elif _AGENDA.search(label) and not _NOT_THE_AGENDA.search(label):
                    agenda_url = agenda_url or url
            if not agenda_url and not minutes_url:
                continue

            time, location = self._time_and_place(panel)
            results.append(
                ScraperReturn(
                    name=self._name(title, panel),
                    date=date.isoformat(),
                    time=time,
                    webpage_url=_LISTING_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                    location=location,
                )
            )

        if not results:
            self.logger.warning(
                f"{self.council_name} found no meetings for {sorted(wanted)}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
