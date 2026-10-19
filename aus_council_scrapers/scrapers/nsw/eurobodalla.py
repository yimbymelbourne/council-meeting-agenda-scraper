import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.alyka import filename_of, find_date
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.esc.nsw.gov.au"
_LISTING_URL = f"{_BASE_URL}/council/meetings/agendas-and-minutes"

# One static Squiz Matrix page per year. The listing above carries the
# current year and links every year's page: /agendas-and-minutes/2025 and so
# on, except the current year, which also has its own copy at
# /2026-council-meetings. The links are read off the page rather than built,
# so a renamed year page is followed instead of guessed at, and production
# (one year, the current one) is the listing alone: one request.
#
# robots.txt disallows only `?sq_content_src=` and Squiz's admin paths, none
# of which this touches. The site is behind Cloudflare; the identifying
# client passed every request when this was written.
_YEAR_LINK = re.compile(
    r"/council/meetings/agendas-and-minutes/(\d{4})(?:-council-meetings)?/?$"
)

# Each page is a Bootstrap accordion of months. Inside a month, every
# meeting is an `h3.media-heading` ("Ordinary Council Meeting 24 February
# 2026") followed by a `ul` of its PDFs. The same accordions hold councillor
# workshops and information sessions ("Councillor Workshop - 9 June 2026"),
# which are not meetings of the council and carry only a workshop agenda, so
# only headings naming a council meeting are kept.
_COUNCIL_MEETING = re.compile(r"council\s+meeting", re.IGNORECASE)
_MONTH_ONLY = re.compile(
    r"^(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*$", re.IGNORECASE
)
# Older headings leave the year off ("Ordinary Council Meeting 14 July"), so
# a day and month are enough there and the year comes from the page.
_DAY_MONTH = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*)\b",
    re.IGNORECASE,
)

# A meeting's list mixes the agenda and minutes with "Attachment to report
# ..." files, councillors' questions on agenda items, the public forum and
# Local Transport Forum minutes attached to a report. The paper itself is
# labelled by what it is first: "Agenda (6.0 MB)", "Extraordinary Council
# Meeting Agenda", "Minutes (731.3 KB)", "Amended Minutes - Extraordinary
# Council Meeting - 10 March 2026". Anchoring at the start of the label is
# what keeps "Councillor Agenda Item Questions" and "Attachment to report ...
# Minutes and attachments" out.
_MEETING_WORDS = (
    r"(?:(?:ordinary|extraordinary|special)\s+(?:council\s+)?(?:meeting\s+)?)?"
)
_AGENDA_LABEL = re.compile(rf"^{_MEETING_WORDS}agenda\b", re.IGNORECASE)
_MINUTES_LABEL = re.compile(
    rf"^(?:amended\s+|confirmed\s+|unconfirmed\s+)?{_MEETING_WORDS}minutes\b",
    re.IGNORECASE,
)


@register_scraper
class EurobodallaScraper(BaseScraper):
    # Refused from GitHub-hosted runners (403, 405 or a connection timeout,
    # measured 20 Oct 2026 by running every state shard from a runner) and
    # reachable from a home connection, so it goes through the residential
    # egress. See AGENTS.md, "Councils that block GitHub's runners".
    egress = "residential"

    def __init__(self):
        super().__init__("eurobodalla", "NSW", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _text(element) -> str:
        return re.sub(r"\s+", " ", element.get_text(" ", strip=True)).strip()

    @staticmethod
    def _page_year(soup: BeautifulSoup) -> Optional[int]:
        """The year a page lists, from the bare "2026" heading above it."""
        for heading in soup.find_all("h2"):
            text = heading.get_text(strip=True)
            if re.fullmatch(r"20\d{2}", text):
                return int(text)
        return None

    def _date(self, heading: str, links: list[tuple[str, str]], page_year: int):
        """The meeting's date, from its heading or, failing that, its papers.

        A full date in the heading wins. Without a year the page's year is
        used. One 2025 heading is just "June"; there the agenda's own
        filename ("Agenda-24-June-2025-compressed.pdf") is the only place
        the day is written, and it is used only if it is in that month.
        """
        found = find_date(heading)
        if found:
            return found[0]
        match = _DAY_MONTH.search(heading)
        if match:
            try:
                return parse_date(
                    f"{match.group(1)} {match.group(2)} {page_year}", dayfirst=True
                ).date()
            except (ValueError, OverflowError):
                return None
        if _MONTH_ONLY.match(heading):
            month = parse_date(f"1 {heading} {page_year}").month
            for _, href in links:
                found = find_date(filename_of(href).replace("-", " ").replace("_", " "))
                if found and found[0].month == month and found[0].year == page_year:
                    return found[0]
        return None

    @staticmethod
    def _meeting_name(heading: str, links: list[tuple[str, str]]) -> str:
        """The meeting type the heading names, less its date.

        Only a month-only heading ("June", 2025) names no type. That one is
        an ordinary meeting—its agenda's cover reads "Ordinary Meeting of
        Council 24 June 2025"—and an extraordinary meeting's papers say so
        in their labels, so the papers decide between the two.
        """
        name = _DAY_MONTH.sub("", heading)
        name = re.sub(r"\b20\d{2}\b", "", name).strip(" -–—")
        if not _COUNCIL_MEETING.search(name):
            papers = " ".join(f"{label} {filename_of(href)}" for label, href in links)
            if re.search(r"extraordinary", papers, re.IGNORECASE):
                return "Extraordinary Council Meeting"
            return "Ordinary Council Meeting"
        return re.sub(r"\s+", " ", name)

    def _parse(
        self, html: str, page_url: str, fallback_year: int
    ) -> list[ScraperReturn]:
        soup = BeautifulSoup(html, "html.parser")
        page_year = self._page_year(soup) or fallback_year
        results = []
        for heading in soup.find_all("h3", class_="media-heading"):
            text = self._text(heading)
            if not (_COUNCIL_MEETING.search(text) or _MONTH_ONLY.match(text)):
                continue
            papers = heading.find_next_sibling("ul")
            links = [
                (self._text(a), urljoin(page_url, a["href"]))
                for a in (papers.find_all("a", href=True) if papers else [])
            ]
            date = self._date(text, links, page_year)
            if date is None:
                self.logger.warning(
                    f"Eurobodalla: no date for {text!r} on {page_url}; skipped"
                )
                continue

            agenda_url = next(
                (h for label, h in links if _AGENDA_LABEL.match(label)), None
            )
            minutes_url = next(
                (h for label, h in links if _MINUTES_LABEL.match(label)), None
            )
            if not agenda_url and not minutes_url:
                continue
            results.append(
                ScraperReturn(
                    name=self._meeting_name(text, links),
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

        listing_html = self.fetcher.fetch_with_requests(_LISTING_URL)
        listing = BeautifulSoup(listing_html, "html.parser")
        listing_year = self._page_year(listing) or clock.current_year()

        year_pages: dict[int, str] = {}
        for link in listing.find_all("a", href=True):
            match = _YEAR_LINK.search(link["href"])
            if match:
                year_pages.setdefault(
                    int(match.group(1)), urljoin(_LISTING_URL, link["href"])
                )
        if not year_pages:
            self.logger.warning(
                "Eurobodalla's agendas page links no year pages; only the "
                "current year can be read"
            )

        pages = []
        if listing_year in wanted:
            pages.append((_LISTING_URL, listing_html, listing_year))
        failures = []
        for year in sorted(wanted, reverse=True):
            if year == listing_year or year not in year_pages:
                continue
            try:
                pages.append(
                    (
                        year_pages[year],
                        self.fetcher.fetch_with_requests(year_pages[year]),
                        year,
                    )
                )
            except Exception as e:
                self.logger.warning(
                    f"Eurobodalla: could not read {year_pages[year]}: {e}"
                )
                failures.append(e)
        if failures and len(pages) == 0:
            raise failures[-1]

        results: list[ScraperReturn] = []
        seen: set[tuple] = set()
        for url, html, year in pages:
            for meeting in self._parse(html, url, year):
                key = (meeting.name, meeting.date)
                if key in seen or meeting.cleaned_date.year not in wanted:
                    continue
                seen.add(key)
                results.append(meeting)

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
