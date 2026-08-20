"""Port Phillip publishes its meetings across two systems.

Recent meetings live in InfoCouncil, which is what `InfoCouncilScraper`
handles. Its ``ddlYear`` filter offers only 2026, 2025 and 2024 — asking for
an earlier year silently returns the default listing, so anything older was
simply missing.

The older meetings are on the council's own site instead, on a single
"previous meetings and agendas" page holding 2022 and 2023. Nothing before
2022 is published anywhere: the ``2021-`` and ``2022-`` URLs are aliases of
that same archive page, and ``2019-``/``2020-`` return 404.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import (
    InfoCouncilScraper,
    ScraperReturn,
    register_scraper,
)
from aus_council_scrapers.constants import EARLIEST_YEAR

_ARCHIVE_PATH = "/about-the-council/council-meetings/previous-meetings-and-agendas/"

# "Council Meeting 1 February 2023" — items without a date, such as
# "Affirmation of Office - Robbie Nyaguy", are not meetings we can record.
_TITLE_DATE = re.compile(
    r"\b\d{1,2}\s+"
    r"(?:January|February|March|April|May|June|July|August|September|October"
    r"|November|December)\s+20\d\d\b",
    re.IGNORECASE,
)


@register_scraper
class PortPhilipScraper(InfoCouncilScraper):
    def __init__(self):
        council = "port_phillip"
        state = "VIC"
        base_url = "https://www.portphillip.vic.gov.au/"
        infocouncil_url = "https://portphillip.infocouncil.biz/"
        super().__init__(council, state, base_url, infocouncil_url)

    def scraper(self) -> list[ScraperReturn]:
        results = super().scraper()

        # Only reach into the archive for years InfoCouncil does not carry, so
        # the two sources cannot produce the same meeting twice.
        years = {y for y in (_year_of(r.date) for r in results) if y}
        floor = min(years) if years else None

        for meeting in self._scrape_archive():
            year = _year_of(meeting.date)
            if year and year >= EARLIEST_YEAR and (floor is None or year < floor):
                results.append(meeting)

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results

    def _scrape_archive(self) -> list[ScraperReturn]:
        url = urljoin(self.base_url, _ARCHIVE_PATH)
        try:
            html = self.fetcher.fetch_with_requests(url)
        except Exception as e:
            self.logger.warning(f"Could not fetch the Port Phillip archive: {e}")
            return []

        soup = BeautifulSoup(html, "html.parser")
        meetings = []

        for item in soup.find_all(class_="i-accordion__item"):
            heading = item.find(class_="i-accordion__title")
            if not heading:
                continue
            title = heading.get_text(" ", strip=True)

            date_match = _TITLE_DATE.search(title)
            if not date_match:
                continue

            agenda_url = None
            minutes_url = None
            for link in item.find_all("a", href=True):
                label = link.get_text(" ", strip=True).lower()
                href = urljoin(self.base_url, link["href"])
                # Agendas appear as "Agenda (PDF …)" or "Agenda Contents (PDF …)";
                # everything else in the accordion is an individual report or
                # attachment, not the meeting's own papers.
                if label.startswith("agenda") and not agenda_url:
                    agenda_url = href
                elif label.startswith("minutes") and not minutes_url:
                    minutes_url = href

            if not agenda_url and not minutes_url:
                continue

            meetings.append(
                ScraperReturn(
                    name=_TITLE_DATE.sub("", title).strip(" -–") or title,
                    date=date_match.group(),
                    time=None,
                    webpage_url=url,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                    location=None,
                )
            )

        return meetings


def _year_of(date_str) -> int | None:
    try:
        return parse_date(str(date_str), fuzzy=True).year
    except Exception:
        return None
