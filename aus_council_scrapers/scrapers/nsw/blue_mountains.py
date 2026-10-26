import re
from typing import Optional
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import (
    BROWSER_USER_AGENT,
    BaseScraper,
    ScraperReturn,
    register_scraper,
)
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.bmcc.nsw.gov.au"
_MEETINGS_URL = f"{_BASE_URL}/council/council-meetings"
_SEARCH_URL = f"{_BASE_URL}/advanced-search"

# Blue Mountains (Drupal) keeps a page per year ("2026 Business Paper,
# Minutes & Video") with a table row per meeting: the date, a business-paper
# link, a minutes link and a recording. Neither link is the PDF:
#
# - the minutes link is a document node (/documents/2026-01-27-confirmed-
#   minutes) whose file field holds the PDF;
# - the business-paper link is usually a site search for the date, whose
#   results list the business paper beside every enclosure and erratum, and
#   only then its document node. The search key is sometimes only the month
#   ("keys=2025-02"), so it is not followed as given.
#
# Node slugs are not predictable ("2026-01-27-ordinary-council-meeting-
# business-paper", "2026-02-24-council-meeting-business-papers"), and are
# sometimes misdated (the 27 August 2024 minutes are
# /documents/2024-07-30-confirmed-minutes-0), so nodes are found by their
# titles and read by their h1, never by slug. One search for the year's
# business papers finds most of them in a single request; a meeting it misses
# is searched for by its own date. A meeting then costs two node requests, so
# one production year is about 21 requests.
#
# robots.txt disallows /search/ but not /advanced-search.
_YEAR_PAGE_LINK = re.compile(r"^(20\d\d)\s+business\s+papers?\b", re.I)
_BUSINESS_PAPER_TITLE = re.compile(
    r"^\s*(\d{4})[-_](\d{2})[-_](\d{2})\s*"
    r"(?:ordinary\s+|extraordinary\s+)?council\s+meeting\s*:\s*business\s+papers?\s*$",
    re.I,
)
_ISO_DATE = re.compile(r"\b(\d{4})[-_](\d{2})[-_](\d{2})\b")
_MINUTES = re.compile(r"minutes", re.I)


@register_scraper
class BlueMountainsScraper(BaseScraper):
    # CloudFront answers the identifying User-Agent with 403 on every page,
    # robots.txt included, and serves a browser-shaped one (measured 20 Oct
    # 2026 from a home IP). Not yet measured from a GitHub runner.
    user_agent = BROWSER_USER_AGENT

    # One full production year, measured 20 Oct 2026 from a home IP: 47 s
    # for 2025 (2026 so far took 41 s for 21 requests). Orders dispatch only.
    expected_seconds = 47

    def __init__(self):
        super().__init__("blue_mountains", "NSW", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _soup(self, url: str) -> BeautifulSoup:
        return BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")

    def _year_pages(self, wanted: set[int]) -> dict[int, str]:
        soup = self._soup(_MEETINGS_URL)
        pages = {}
        for link in soup.find_all("a", href=True):
            match = _YEAR_PAGE_LINK.match(link.get_text(" ", strip=True))
            if match and int(match.group(1)) in wanted:
                pages.setdefault(int(match.group(1)), urljoin(_BASE_URL, link["href"]))
        if clock.current_year() in wanted and clock.current_year() not in pages:
            raise ValueError(f"No {clock.current_year()} page linked from {_MEETINGS_URL}")
        return pages

    @staticmethod
    def _minutes_link(cell) -> Optional[str]:
        """The best minutes node in a row's minutes cell.

        2021 rows link the unconfirmed minutes under a bare date and the
        confirmed ones beside it; the confirmed minutes win. A recording
        labelled "Audio" that points at a minutes node (29 August 2023) is
        not taken.
        """
        best = None
        for link in cell.find_all("a", href=True):
            label = link.get_text(" ", strip=True)
            href = urljoin(_BASE_URL, link["href"])
            if "/documents/" not in href:
                continue
            if _MINUTES.search(label):
                rank = 0 if not re.search(r"unconfirmed", label, re.I) else 1
            elif _ISO_DATE.fullmatch(label.strip()) and _MINUTES.search(href):
                rank = 2
            else:
                continue
            if best is None or rank < best[0]:
                best = (rank, href)
        return best[1] if best else None

    def _rows(self, url: str) -> tuple[list[dict], Optional[str]]:
        soup = self._soup(url)
        table = soup.find("table")
        if table is None:
            raise ValueError(f"No meetings table on {url}")
        rows = table.find_all("tr")
        header = rows[0].get_text(" ", strip=True) if rows else ""
        time_match = self.time_regex.search(header)  # "7.30pm on the Following Dates"
        meetings = []
        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < 3:
                continue
            date_match = self.date_regex.search(cells[0].get_text(" ", strip=True))
            if not date_match:
                continue
            date = parse_date(date_match.group(), dayfirst=True).date()
            paper_link = cells[1].find("a", href=True)
            meetings.append(
                {
                    "date": date,
                    "paper": urljoin(_BASE_URL, paper_link["href"]) if paper_link else None,
                    "minutes": self._minutes_link(cells[2]),
                }
            )
        # "7.30pm" reads as 7 pm to dateutil; "7:30pm" does not.
        time = time_match.group().replace(".", ":") if time_match else None
        return meetings, time

    def _search_business_papers(self, keys: str) -> dict:
        """Business-paper nodes in one page of search results, by date."""
        soup = self._soup(f"{_SEARCH_URL}?keys={quote(keys)}&type=3")
        found = {}
        for link in soup.find_all("a", href=True):
            match = _BUSINESS_PAPER_TITLE.match(link.get_text(" ", strip=True))
            if match and "/documents/" in link["href"]:
                date = parse_date("-".join(match.groups())).date()
                found.setdefault(date, urljoin(_BASE_URL, link["href"]))
        return found

    def _node(self, url: str) -> tuple[Optional[str], str]:
        """(PDF URL, title) of a document node."""
        soup = self._soup(url)
        link = soup.select_one(".node--type-document .field--name-field-document a[href]")
        heading = soup.find("h1")
        title = heading.get_text(" ", strip=True) if heading else ""
        return (urljoin(_BASE_URL, link["href"]) if link else None), title

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        results: list[ScraperReturn] = []
        for year, page_url in sorted(self._year_pages(wanted).items()):
            meetings, time = self._rows(page_url)
            meetings = [
                m for m in meetings
                if m["date"].year in wanted and (m["paper"] or m["minutes"])
            ]
            if not meetings:
                continue

            searched = {}
            if any(m["paper"] and "/advanced-search" in m["paper"] for m in meetings):
                searched = self._search_business_papers(f'"{year}" business paper')

            for meeting in meetings:
                date = meeting["date"]
                paper_node = meeting["paper"]
                if paper_node and "/advanced-search" in paper_node:
                    paper_node = searched.get(date)
                    if paper_node is None:
                        paper_node = self._search_business_papers(date.isoformat()).get(date)
                    if paper_node is None:
                        self.logger.warning(f"No business paper found for {date}")

                agenda_url, paper_title = (
                    self._node(paper_node) if paper_node else (None, "")
                )
                minutes_url, minutes_title = (
                    self._node(meeting["minutes"]) if meeting["minutes"] else (None, "")
                )
                if not agenda_url and not minutes_url:
                    continue

                kinds = f"{paper_title} {minutes_title} {paper_node or ''} {meeting['minutes'] or ''}"
                name = (
                    "Extraordinary Council Meeting"
                    if re.search(r"extraordinary", kinds, re.I)
                    else "Ordinary Council Meeting"
                )
                results.append(
                    ScraperReturn(
                        name=name,
                        date=date.isoformat(),
                        time=time,
                        webpage_url=page_url,
                        agenda_url=agenda_url,
                        minutes_url=minutes_url,
                        download_url=agenda_url or minutes_url,
                    )
                )

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
