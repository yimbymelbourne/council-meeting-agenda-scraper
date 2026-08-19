import datetime
import re

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import (
    BaseScraper,
    ScraperReturn,
    register_scraper,
)
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.darebin.vic.gov.au"
_LISTING_URL = (
    "https://www.darebin.vic.gov.au"
    "/About-council/Council-structure-and-performance"
    "/Council-and-Committee-Meetings/Council-meetings"
    "/Meeting-agendas-and-minutes"
)
_YEAR_PAGE_URL = (
    _LISTING_URL + "/{year}-Council-meeting-agendas-and-minutes"
)

# Matches link text like "Council Meeting Agenda - 27 May 2024"
# or "Special Council Meeting Minutes - 18 April 2024"
_DOC_LINK_RE = re.compile(
    r"^(.+?)\s+(Agenda|Minutes)\s+-\s+(.+)$",
    re.IGNORECASE,
)

# Strip trailing "(PDF, 16MB)" style annotations from link text
_PDF_SIZE_RE = re.compile(r"\s*\(PDF[^)]*\)", re.IGNORECASE)


@register_scraper
class DarebinScraper(BaseScraper):

    def __init__(self):
        super().__init__("darebin", "VIC", _BASE_URL)

    def _date_from_url(self, href: str, year: int) -> str | None:
        """Try to extract a date matching `year` from a PDF URL path.

        The filename/folder often uses hyphens (e.g. "10-february-2026"), so
        replace hyphens and underscores with spaces before applying date_regex.
        """
        normalised = href.replace("-", " ").replace("_", " ")
        for m in self.date_regex.finditer(normalised):
            candidate = m.group()
            try:
                from dateutil.parser import parse as _parse
                if _parse(candidate, fuzzy=True).year == year:
                    return candidate
            except Exception:
                pass
        return None

    def _parse_year_page(self, year: int) -> list[ScraperReturn]:
        url = _YEAR_PAGE_URL.format(year=year)
        html = self.fetcher.fetch_with_selenium(url)
        soup = BeautifulSoup(html, "html.parser")

        # Collect agenda/minutes URLs keyed by (date_str, meeting_type).
        # dict value: {"agenda_url": ..., "minutes_url": ...}
        meetings: dict[tuple, dict] = {}
        # Preserve insertion order so results stay in page order (newest first).
        order: list[tuple] = []

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.lower().endswith(".pdf"):
                continue

            text = _PDF_SIZE_RE.sub("", a.get_text(strip=True)).strip()
            m = _DOC_LINK_RE.match(text)
            if not m:
                continue

            meeting_type = m.group(1).strip()
            doc_type = m.group(2).strip().lower()  # "agenda" or "minutes"
            raw_date = m.group(3).strip()
            # Some entries append a time (e.g. "30 June 2025 5.45pm"); extract
            # just the date portion using the shared date regex.
            date_match = self.date_regex.search(raw_date)
            date_str = date_match.group() if date_match else raw_date

            # If the date belongs to a different year (e.g. "adjourned from
            # 22 December 2025" on the 2026 page), try to recover the actual
            # meeting date from the PDF URL, which usually contains the real date.
            try:
                from dateutil.parser import parse as _parse
                extracted_year = _parse(date_str, fuzzy=True).year
            except Exception:
                extracted_year = None

            if extracted_year != year:
                url_date = self._date_from_url(href, year)
                if url_date:
                    date_str = url_date

            full_url = (_BASE_URL + href) if href.startswith("/") else href

            key = (date_str, meeting_type)
            if key not in meetings:
                meetings[key] = {"agenda_url": None, "minutes_url": None}
                order.append(key)

            if doc_type == "agenda" and not meetings[key]["agenda_url"]:
                meetings[key]["agenda_url"] = full_url
            elif doc_type == "minutes" and not meetings[key]["minutes_url"]:
                meetings[key]["minutes_url"] = full_url

        results = []
        for key in order:
            date_str, meeting_type = key
            docs = meetings[key]
            agenda_url = docs["agenda_url"]
            minutes_url = docs["minutes_url"]
            if not agenda_url and not minutes_url:
                continue
            results.append(
                ScraperReturn(
                    name=meeting_type,
                    date=date_str,
                    time=None,
                    webpage_url=url,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
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
            results = self._parse_year_page(year)
            all_results.extend(results)

        return all_results


if __name__ == "__main__":
    scraper = DarebinScraper()
    for r in scraper.scraper():
        print(r)
