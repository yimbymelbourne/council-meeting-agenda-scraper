import datetime
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.collie.wa.gov.au"
_INDEX_URL = f"{_BASE_URL}/council/agendas-minutes-by-year/"

# WordPress, with a TablePress table per year on a page of its own. The year
# pages have irregular slugs (/2026agendasminutes/, /2024-agendas-minutes/,
# /2023-agenda-minutes/), so they are read off the index rather than built.
#
# Each table row is one meeting: a label cell, then Agenda, Appendices,
# Minutes and (from 2026) a SoundCloud recording. The columns are not fixed—
# the 13 July 2021 row has Minutes before Appendices—so each link is
# classified by its own text ("Agenda", "Agenda & Appendices", "Confirmed
# Minutes"), with the column heading only as a fallback.
#
# The label cell holds the day and month, sometimes the year, and for
# anything other than an ordinary meeting, its type: "21 July - Special
# Meeting of Council", "Special Meeting of Council - 12 April", "4 May -
# Annual Electors Meeting", "6 December - Regional Joint Development
# Assessment Panel". Both "October 13" and "12 May" orders appear on one
# page.
_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    )
}
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
_DAY_MONTH = re.compile(r"(?<!\d)(\d{1,2})\s+" + _MONTH + r"(?:\s+(\d{4}))?", re.IGNORECASE)
_MONTH_DAY = re.compile(_MONTH + r"\s+(\d{1,2})(?!\d)(?:,?\s+(\d{4}))?", re.IGNORECASE)

_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)
_MINUTES = re.compile(r"\bminutes?\b", re.IGNORECASE)

# Councillor Forums are briefings where nothing is decided; their "notes"
# are not minutes.
_SKIP_ROW = re.compile(r"councillor forum", re.IGNORECASE)

# Rows whose date label is wrong, checked against the papers themselves.
# Ordinary meetings are on a Tuesday, and these were the only two rows from
# 2020 on that were not:
#   - "7 July 2024" (a Sunday) links an agenda headed "ORDINARY MEETING OF
#     COUNCIL to be held on Tuesday, 9 July 2024" and OCM-9Jul24-signed.pdf.
#   - "10 October 2024" (a Thursday) links an agenda and minutes both for
#     "Tuesday, 8 October 2024".
_DATE_CORRECTIONS = {
    datetime.date(2024, 7, 7): datetime.date(2024, 7, 9),
    datetime.date(2024, 10, 10): datetime.date(2024, 10, 8),
}


def _row_date(label: str, page_year: int) -> Optional[datetime.date]:
    label = label.replace("\xa0", " ")
    for pattern, day_group, month_group in ((_DAY_MONTH, 1, 2), (_MONTH_DAY, 2, 1)):
        match = pattern.search(label)
        if not match:
            continue
        year = int(match.group(3)) if match.group(3) else page_year
        try:
            date = datetime.date(
                year, _MONTHS[match.group(month_group)[:3].lower()], int(match.group(day_group))
            )
        except ValueError:
            continue
        return _DATE_CORRECTIONS.get(date, date)
    return None


def _meeting_name(label: str) -> str:
    lowered = label.lower()
    if "regional joint development assessment panel" in lowered:
        return "Regional Joint Development Assessment Panel"
    if "elector" in lowered:
        return "Annual Electors' Meeting" if "annual" in lowered else "Electors' Meeting"
    if "special" in lowered:
        return "Special Council Meeting"
    return "Ordinary Council Meeting"


@register_scraper
class CollieScraper(BaseScraper):
    def __init__(self):
        super().__init__("collie", "WA", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _year_pages(self, wanted: set[int]) -> dict[int, str]:
        html = self.fetcher.fetch_with_requests(_INDEX_URL)
        soup = BeautifulSoup(html, "html.parser")
        pages = {}
        for anchor in soup.find_all("a", href=True):
            text = anchor.get_text(strip=True)
            url = urljoin(_INDEX_URL, anchor["href"])
            if re.fullmatch(r"\d{4}", text) and urlparse(url).netloc == urlparse(_BASE_URL).netloc:
                pages.setdefault(int(text), url)
        if not pages:
            raise ValueError(f"{self.council_name}: no year pages linked from {_INDEX_URL}")
        return {year: url for year, url in pages.items() if year in wanted}

    def _document_url(self, href: str, page_url: str) -> Optional[str]:
        """The PDF behind a link, following WordPress attachment pages.

        Most links go straight to /wp-content/uploads/…pdf. Some recent ones
        (September and August 2026, September 2021) link the media item's
        attachment page instead (/0926-ocm-agenda-updated/), which holds one
        `p.attachment` link to the file. The wp-json media API that would
        resolve them in bulk answers 403, so each costs one request.
        """
        url = urljoin(page_url, href.strip())
        if url.lower().endswith(".pdf"):
            return url
        if urlparse(url).netloc != urlparse(_BASE_URL).netloc:
            return None  # SoundCloud recordings, mostly.
        # A failed fetch fails the council, as a failed year page does. These
        # pages carry current papers (in 2026, both agendas and minutes for
        # August and September), so dropping one would return a quietly short
        # list as a successful scrape. It would also change the meeting's
        # identity downstream: council-alerts keys a meeting by agenda_url,
        # then minutes_url, so a night that lost the agenda would file the
        # meeting under its minutes and the next good night would add it again.
        try:
            html = self.fetcher.fetch_with_requests(url)
        except Exception as error:
            self.logger.warning(f"{self.council_name}: could not read attachment page {url}: {error}")
            raise
        # A page that loads but holds no PDF is the council's own linking
        # (a Word file, an image), not a fetch failure, so only that paper
        # is dropped.
        link = BeautifulSoup(html, "html.parser").select_one("p.attachment a[href]")
        if not link or not link["href"].lower().endswith(".pdf"):
            self.logger.warning(f"{self.council_name}: no PDF on attachment page {url}")
            return None
        return urljoin(url, link["href"])

    def _meetings(self, html: str, page_url: str, year: int) -> list[ScraperReturn]:
        soup = BeautifulSoup(html, "html.parser")
        table = soup.select_one("table.tablepress") or soup.find("table")
        if not table:
            raise ValueError(f"{self.council_name}: no meetings table on {page_url}")
        rows = table.find_all("tr")
        headings = [c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"])] if rows else []

        results = []
        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            label = cells[0].get_text(" ", strip=True)
            if not label or _SKIP_ROW.search(label):
                continue
            date = _row_date(label, year)
            if not date:
                self.logger.warning(f"{self.council_name}: cannot date row {label!r} on {page_url}")
                continue

            papers: dict[str, str] = {}
            for index, cell in enumerate(cells[1:], start=1):
                heading = headings[index] if index < len(headings) else ""
                for anchor in cell.find_all("a", href=True):
                    text = anchor.get_text(" ", strip=True)
                    if _MINUTES.search(text):
                        kind = "minutes"
                    elif _AGENDA.search(text):
                        kind = "agenda"
                    elif not text and "minutes" in heading:
                        kind = "minutes"
                    elif not text and "agenda" in heading:
                        kind = "agenda"
                    else:
                        continue  # Appendices, budgets, recordings.
                    if kind in papers:
                        continue
                    url = self._document_url(anchor["href"], page_url)
                    if url:
                        papers[kind] = url
            if not papers:
                continue
            results.append(
                ScraperReturn(
                    name=_meeting_name(label),
                    date=date.isoformat(),
                    time=None,
                    webpage_url=page_url,
                    agenda_url=papers.get("agenda"),
                    minutes_url=papers.get("minutes"),
                    download_url=papers.get("agenda") or papers.get("minutes"),
                )
            )
        return results

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # Left to raise on failure: the index and each year page are the
        # only places the meetings are listed.
        results = []
        for year, page_url in sorted(self._year_pages(wanted).items()):
            html = self.fetcher.fetch_with_requests(page_url)
            results.extend(self._meetings(html, page_url, year))

        if not results:
            # Normal for a year with no page yet (January), so a warning.
            self.logger.warning(f"{self.council_name} found no meetings for {sorted(wanted)}")
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
