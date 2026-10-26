import datetime
import re
from typing import Optional
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.victoriadaly.nt.gov.au"
_LISTING_URL = _BASE_URL + "/minutes-and-agendas/"

# One WordPress page, one table: Meeting Date | Meeting (type in bold, venue
# after it) | Agendas | Unconfirmed Minutes | Confirmed Minutes, from March
# 2022 to the next scheduled meeting. One request covers the whole history.
# Below it the page carries two stale copies of the same table, cut off at
# June and March 2026, some rows still with the unconfirmed minutes the first
# table has since replaced. Every row in them is also in the first table, so
# only the first is read.
#
# Older papers are in a WP Download Manager archive (/meetings/archived-
# documents/) filed by category with no meeting dates in the listing, and the
# Finance and Audit committees have pages of their own; neither is read, as
# this project tracks the Council's meetings.
_MONTHS = [
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
]
_DATE = re.compile(
    r"(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(20\d{2})",
    re.IGNORECASE,
)


def _parse(text: str) -> Optional[datetime.date]:
    match = _DATE.search(text)
    if not match:
        return None
    day, month, year = match.groups()
    try:
        return datetime.date(int(year), _MONTHS.index(month[:3].lower()) + 1, int(day))
    except ValueError:
        return None


def _document_url(href: str) -> Optional[str]:
    url = urljoin(_LISTING_URL, href.strip())
    parts = urlsplit(url)
    # One agenda href is a fragment of the venue text
    # ("/Ordinary%20Council Meeting 18 Pearce Street, Katherine"), not a file.
    if not parts.path.lower().endswith((".pdf", ".docx", ".doc")):
        return None
    # Most links are written http://; the site serves the same files over
    # https and redirects http to it.
    if parts.scheme == "http" and parts.netloc.endswith("victoriadaly.nt.gov.au"):
        url = urlunsplit(("https",) + tuple(parts[1:]))
    return url


@register_scraper
class VictoriaDalyScraper(BaseScraper):
    def __init__(self):
        super().__init__("victoria_daly", "NT", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _pick(cells, wanted: re.Pattern) -> Optional[str]:
        for cell in cells:
            for link in cell.find_all("a", href=True):
                if wanted.match(link.get_text(" ", strip=True)):
                    url = _document_url(link["href"])
                    if url:
                        return url
        return None

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        html = self.fetcher.fetch_with_requests(_LISTING_URL)
        soup = BeautifulSoup(html, "html.parser")

        table = next(
            (
                t
                for t in soup.find_all("table")
                if "meeting date" in t.get_text(" ").lower()
            ),
            None,
        )
        if table is None:
            raise ValueError(
                f"{self.council_name}: no meetings table on {_LISTING_URL}"
            )

        results: list[ScraperReturn] = []
        seen = set()
        rows_read = 0
        for row in table.find_all("tr"):
            cells = row.find_all("td", recursive=False)
            if len(cells) < 5:
                continue
            date = _parse(cells[0].get_text(" ", strip=True))
            if date is None:
                continue  # the header row
            rows_read += 1
            if date.year not in wanted:
                continue

            meeting_cell = cells[1]
            bold = meeting_cell.find("strong")
            name = re.sub(r"\s+", " ", bold.get_text(" ", strip=True)) if bold else ""
            if bold:
                bold.extract()
            location = ", ".join(
                part.strip(" ,")
                for part in meeting_cell.stripped_strings
                if part.strip(" ,")
            )
            if not name:
                name, location = location, None
            # The council writes both "Ordinary Meeting of Council" and
            # "Ordinary Council Meeting" for the same meeting type.
            if re.search(r"special", name, re.IGNORECASE):
                name = "Special Council Meeting"
            elif re.search(r"ordinary", name, re.IGNORECASE):
                name = "Ordinary Council Meeting"

            # The Agendas cell also holds supplementary reports; the agenda
            # is the link labelled "Agenda".
            agenda_url = self._pick(cells[2:3], re.compile(r"^agenda\b", re.IGNORECASE))
            # Confirmed minutes replace the unconfirmed draft once adopted.
            minutes_url = self._pick(
                cells[2:], re.compile(r"^confirmed minutes", re.IGNORECASE)
            ) or self._pick(
                cells[2:], re.compile(r"^unconfirmed minutes", re.IGNORECASE)
            )
            if not agenda_url and not minutes_url:
                continue  # upcoming, or a confidential meeting with no papers

            key = (date, name, agenda_url, minutes_url)
            if key in seen:
                continue
            seen.add(key)
            results.append(
                ScraperReturn(
                    name=name,
                    date=date.isoformat(),
                    time=None,
                    webpage_url=_LISTING_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                    location=location or None,
                )
            )

        if not rows_read:
            raise ValueError(f"{self.council_name}: no meeting rows on {_LISTING_URL}")
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
