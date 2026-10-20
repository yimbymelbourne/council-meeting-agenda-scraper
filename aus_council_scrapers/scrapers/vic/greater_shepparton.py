"""Greater Shepparton City Council—a page per year on the council's own CMS.

The index page links one page per year, 2016 onwards
(``/minutes-agendas/<YYYY>-agendas-and-minutes``). Each year page is a run
of collapsible sections (``div.content-fragment-toggle``), one per meeting,
headed by an ``h3`` that carries the date and the meeting type—"19 February
2019 - Ordinary Council Meeting", "15 September 2026 — Additional Council
Meeting"—and holding that meeting's files as a ``ul.files`` list.

A section holds the agenda, the minutes and one PDF per report item ("9.2
Councillor Gift Policy", "Item 8.1 - CFA Schedule 13 ..."). Only the two
papers are kept. Their labels lead with the paper ("Agenda - Council Meeting
- 24 February 2026"), except in 2019, where three put the meeting first
("Special Council Meeting - Agenda - 26 February 2019", "Agenda of Ordinary
Council Meeting - 17 December 2019"). Item papers lead with their number, and
some are themselves minutes—"10.1 Audit and Risk Management Committee -
Minutes - 11 February 2026" is a committee's minutes tabled as an item—so a
label that starts with an item number or "Item" is never the paper.

The date comes from the section heading, not the link text or filename. The
link text is hand-typed and has lost its day ("Minutes - Special Council
Meeting - Election of the Mayor and Deputy Mayor 2019"), and the CMS appends
a digit to a re-uploaded file ("Minutes_-_Council_Meeting_-_24_March_20261.pdf",
which the link text copies as "27 October 20221").

Production asks for one year: the index plus that year's page, two requests.
"""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://greatershepparton.com.au"
_INDEX_URL = f"{_BASE_URL}/council/governance/council-meetings/minutes-agendas"

# Read off the index rather than built, so a renamed year page is followed.
_YEAR_LINK = re.compile(r"/minutes-agendas/(\d{4})-agendas-and-minutes/?$")

_HEADING_DATE = re.compile(
    r"^\s*(\d{1,2}\s+(?:January|February|March|April|May|June|July|August"
    r"|September|October|November|December)\s+\d{4})\s*[-–—]\s*(.+?)\s*$",
    re.IGNORECASE,
)

# The paper's word first, or the meeting first and the paper after a dash.
_AGENDA = re.compile(r"^agenda\b|\bmeeting\s*-\s*agenda\b", re.IGNORECASE)
_MINUTES = re.compile(r"^minutes\b|\bmeeting\s*-\s*minutes\b", re.IGNORECASE)
# An item's own paper ("9.2 ...", "Item 4.3 - ...", and once "Iten 7.5"), or
# an attachment to one.
_ITEM = re.compile(r"^(?:\d+\.\d+|ite[mn]\b|attachment\b)", re.IGNORECASE)


@register_scraper
class GreaterSheppartonScraper(BaseScraper):
    # Refused from GitHub-hosted runners (403, 405 or a connection timeout,
    # measured 20 Oct 2026 by running every state shard from a runner) and
    # reachable from a home connection, so it goes through the residential
    # egress. See AGENTS.md, "Councils that block GitHub's runners".
    egress = "residential"

    def __init__(self):
        super().__init__("greater_shepparton", "VIC", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return {int(year) for year in years_filter}
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _year_pages(self) -> dict[int, str]:
        soup = BeautifulSoup(
            self.fetcher.fetch_with_requests(_INDEX_URL), "html.parser"
        )
        pages = {}
        for anchor in soup.find_all("a", href=True):
            match = _YEAR_LINK.search(anchor["href"])
            if match:
                pages[int(match.group(1))] = urljoin(_INDEX_URL, anchor["href"])
        if not pages:
            # The index is the only way to the year pages; without it every
            # year would come back empty and look like a quiet council.
            raise RuntimeError(f"{self.council_name}: no year pages on {_INDEX_URL}")
        return pages

    def _parse_year(self, html: str, page_url: str) -> list[ScraperReturn]:
        soup = BeautifulSoup(html, "html.parser")
        fragments = soup.find_all("div", class_="content-fragment-toggle")
        if not fragments or not soup.select(
            "div.content-fragment-toggle ul.files a.file-link[href]"
        ):
            # A year page is linked from the index only once it has meetings,
            # so one that parses to no sections or no files has changed its
            # markup; returning nothing would read as a year with no meetings.
            raise RuntimeError(
                f"{self.council_name}: no meeting sections with files on {page_url}"
            )
        results = []
        for fragment in fragments:
            heading = fragment.find("h3")
            files = fragment.find("ul", class_="files")
            if not heading or not files:
                continue
            match = _HEADING_DATE.match(heading.get_text(" ", strip=True))
            if not match:
                self.logger.warning(
                    f"{page_url}: section heading without a date, skipped: "
                    f"{heading.get_text(' ', strip=True)!r}"
                )
                continue
            date = parse_date(match.group(1)).date()
            name = re.sub(r"\s+", " ", match.group(2))

            agenda_url = minutes_url = None
            for anchor in files.find_all("a", class_="file-link", href=True):
                label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True))
                if _ITEM.match(label):
                    continue
                href = urljoin(page_url, anchor["href"])
                if minutes_url is None and _MINUTES.search(label):
                    minutes_url = href
                elif agenda_url is None and _AGENDA.search(label):
                    agenda_url = href

            if not agenda_url and not minutes_url:
                continue
            results.append(
                ScraperReturn(
                    name=name,
                    date=date.isoformat(),
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
        wanted = self._wanted_years()
        pages = self._year_pages()

        results: list[ScraperReturn] = []
        for year in sorted((y for y in pages if y in wanted), reverse=True):
            # A failed year page raises: in production it is the only page
            # with that year's meetings, and returning nothing would read as
            # a council that held none.
            html = self.fetcher.fetch_with_requests(pages[year])
            results.extend(
                r
                for r in self._parse_year(html, pages[year])
                if int(r.date[:4]) in wanted
            )

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
