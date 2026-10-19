import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.alyka import find_date
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.southgippsland.vic.gov.au"
_INDEX_URL = f"{_BASE_URL}/meetings"

# Jadu CMS's meetings module, three levels deep:
#
#   /meetings                                  index: one "committee" per year
#   /meetings/committee/29/council_..._2026    that year's meetings, by date
#   /meetings/meeting/388/council_..._2026     one meeting and its downloads
#
# The committee ids are not in year order (2021 is 25, 2022 is 21, 2023 is
# 17), so the year pages are found by the year in each link's slug, never
# built. Only Council meetings are published here; the council has no
# separate planning committee.
#
# The documents are only on the meeting pages, so a year costs one request
# per meeting: production (one year) is the index, the year page and about
# a dozen meeting pages. robots.txt disallows /jadu, /search, /preview and a
# few asset folders; /meetings and /download are open.
_YEAR_LINK = re.compile(r"/meetings/committee/\d+/[a-z0-9_]*?(\d{4})/?$")
_MEETING_LINK = re.compile(r"/meetings/meeting/\d+/")
_DOWNLOAD = re.compile(r"/download/meetings/id/\d+/")

# Download labels have changed over the years: "Agenda Council Meeting
# No.463", "Council Agenda Wednesday 11 December 2024", "Download the Council
# Agenda", "Minute Council Meeting No. 471", "Download the Minutes". Next to
# them sit attachments ("Attachment 5.1.1. ...", "Download Attachments -
# Agenda Items 5.2 & 5.5", "Download the Attachments – Open Council Meeting
# Agenda – ...") and the recording. An attachment label can say "agenda"
# or "minutes" too, so it is excluded first.
_ATTACHMENT = re.compile(r"attachment", re.IGNORECASE)
_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)
_MINUTES = re.compile(r"\bminutes?\b", re.IGNORECASE)
_ADDITIONAL = re.compile(r"\badditional\b", re.IGNORECASE)
_SPECIAL = re.compile(r"\bspecial\b", re.IGNORECASE)


@register_scraper
class SouthGippslandScraper(BaseScraper):
    # Measured 22 s for 2026 from a home connection (20 Oct 2026): eleven
    # requests—index, year page, nine meeting pages—at the 2 s host spacing.
    expected_seconds = 22.0

    def __init__(self):
        super().__init__("south_gippsland", "VIC", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _soup(self, url: str) -> BeautifulSoup:
        return BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")

    @staticmethod
    def _text(element) -> str:
        return re.sub(r"\s+", " ", element.get_text(" ", strip=True)).strip()

    def _meeting(self, url: str, date) -> Optional[ScraperReturn]:
        page = self._soup(url)
        agenda_url = minutes_url = None
        labels = []
        for link in page.find_all("a", href=True):
            if not _DOWNLOAD.search(link["href"]):
                continue
            label = self._text(link)
            if _ATTACHMENT.search(label):
                continue
            href = urljoin(url, link["href"])
            if minutes_url is None and _MINUTES.search(label):
                minutes_url = href
                labels.append(label)
            elif agenda_url is None and _AGENDA.search(label):
                agenda_url = href
                labels.append(label)
        if not agenda_url and not minutes_url:
            return None
        context = " ".join(labels)
        if _SPECIAL.search(context):
            name = "Special Council Meeting"
        elif _ADDITIONAL.search(context):
            name = "Additional Council Meeting"
        else:
            name = "Council Meeting"
        return ScraperReturn(
            name=name,
            date=date.isoformat(),
            time=None,
            webpage_url=url,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
        )

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        year_pages: dict[int, str] = {}
        for link in self._soup(_INDEX_URL).find_all("a", href=True):
            match = _YEAR_LINK.search(link["href"])
            if match:
                year_pages.setdefault(
                    int(match.group(1)), urljoin(_INDEX_URL, link["href"])
                )
        if not year_pages:
            raise ValueError(f"No yearly meeting pages linked from {_INDEX_URL}")

        meetings = []
        failures = []
        for year in sorted(wanted & set(year_pages), reverse=True):
            try:
                page = self._soup(year_pages[year])
            except Exception as e:
                self.logger.warning(f"South Gippsland: {year} page failed: {e}")
                failures.append(e)
                continue
            for link in page.find_all("a", href=True):
                if not _MEETING_LINK.search(link["href"]):
                    continue
                # "Wednesday,  16th September 2026"
                found = find_date(self._text(link))
                if found and found[0].year in wanted:
                    meetings.append((urljoin(_INDEX_URL, link["href"]), found[0]))

        results = []
        seen = set()
        for url, date in meetings:
            if url in seen:
                continue
            seen.add(url)
            # Not caught: a meeting's documents are only on its own page, so
            # a page that fails is a meeting silently missing from a list
            # that otherwise looks whole. Failing the council says so.
            meeting = self._meeting(url, date)
            if meeting:
                results.append(meeting)

        # A year page that failed is tolerated in a multi-year run, as
        # InfoCouncil tolerates a failed year, and logged above. A run that
        # read nothing at all—production's single year among them—fails
        # rather than reporting an empty year as a success.
        if failures and not results:
            raise failures[-1]
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
