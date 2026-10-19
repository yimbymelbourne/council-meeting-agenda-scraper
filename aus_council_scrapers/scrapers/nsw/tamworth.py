"""Tamworth Regional Council—a Kentico document list, one row per file.

The Business Papers and Minutes page is a server-rendered table
(``table#tableDocList4438``) of every file the council has filed for its
meetings, ten to a page, newest first, paged by a plain GET
(``?PagingModule=4438&pg=N``) back to April 2019 (47 pages in October 2026).
Each row is one file—"Business Paper 13 October 2026", "Annexures 13 October
2026", "Minutes 13 October 2026", "Questions on Notice - ...", "Late Item -
Business Paper - ..."—with a Date column. The files are Kentico document
handlers (``/ArticleDocuments/474/<name>.pdf.aspx``) that serve the PDF.

**Rows are grouped by the date in the label, not the Date column.** The
column is when the file was filed, which is usually the meeting day but not
always: the agenda for 23 August 2022 is dated 19/08/22, and the minutes of
8 June 2021 are dated 11/06/21. Grouping by the column would put those
papers on meetings that never happened. Every agenda and minutes label in
the listing carries its meeting's date.

The agenda is the "Business Paper" (once "Open Agenda of Ordinary Council
Meeting"); "Annexures" are its attachments, and a "Late Item - Business
Paper" is a second paper for the same meeting, so neither is taken as the
agenda. Many 2021–2022 meetings have minutes and no business paper online.

Tamworth has no planning committee or panel in this list, so nothing is
filtered by meeting type; the only meetings are Council's own. A meeting is
"Extraordinary Council Meeting" when a paper's label says so and "Council
Meeting" otherwise—most labels name no type at all.

**Cost.** The listing is newest first, so it is paged only until a page
reaches back before the earliest wanted year. 2026 takes 7 pages (7
requests, 12 s); the whole history from 2020 takes 44.
"""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.tamworth.nsw.gov.au"
_LISTING_URL = (
    f"{_BASE_URL}/about/the-council/council-meetings/business-papers-and-minutes"
)
_PAGE_URL = _LISTING_URL + "?PagingModule=4438&pg={page}"

# A safety stop: the listing ended at page 47 in October 2026.
_MAX_PAGES = 120

_LABEL_DATE = re.compile(
    r"\b(\d{1,2})\s+(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?"
    r"|July?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+(\d{4})\b",
    re.IGNORECASE,
)

# "Business Paper - 10 June 2025", "Business Papers - ...", "Council Business
# Paper - ...", "Extraordinary Meeting Business Paper - ...", "Open Agenda of
# Ordinary Council Meeting - 23 August 2022.pdf".
_AGENDA = re.compile(
    r"^(?:council\s+|extraordinary\s+(?:meeting\s+)?)?business\s+papers?\b"
    r"|^open\s+agenda\b",
    re.IGNORECASE,
)
# "Minutes 13 October 2026", "Council Minutes - 10 October 2023".
_MINUTES = re.compile(r"^(?:council\s+)?minutes\b", re.IGNORECASE)
# "Business Paper - Late Item - 23 August 2022" leads with the agenda's words
# but is a second paper, filed after the agenda and so read before it.
_LATE_ITEM = re.compile(r"\blate\s+item\b", re.IGNORECASE)
_EXTRAORDINARY = re.compile(r"extraordinary", re.IGNORECASE)


@register_scraper
class TamworthScraper(BaseScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 7 requests,
    # 12 s. Orders dispatch only; see BaseScraper.expected_seconds.
    expected_seconds = 12

    def __init__(self):
        super().__init__("tamworth", "NSW", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return {int(year) for year in years_filter}
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _rows(html: str):
        """``(label, filed date, href)`` for each row, and whether the page
        links a next page."""
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table", id="tableDocList4438")
        if table is None:
            raise RuntimeError("Tamworth: document table missing from the listing")
        rows = []
        for tr in table.find_all("tr"):
            cells = tr.find_all("td")
            anchor = tr.find("a", href=True)
            if len(cells) < 3 or anchor is None:
                continue
            label = re.sub(r"\s+", " ", cells[1].get_text(" ", strip=True))
            filed = parse_date(cells[2].get_text(strip=True), dayfirst=True).date()
            rows.append((label, filed, anchor["href"]))
        has_next = any(
            a.get_text(strip=True) == "Next" for a in soup.find_all("a", href=True)
        )
        return rows, has_next

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        earliest = min(wanted)

        # date -> {"agenda": url, "minutes": url, "labels": [...]}
        meetings: dict = {}
        page = 1
        while page <= _MAX_PAGES:
            url = _PAGE_URL.format(page=page)
            # A failed page raises rather than ending the walk early: the
            # meetings on the pages after it would silently go missing.
            rows, has_next = self._rows(self.fetcher.fetch_with_requests(url))
            if page == 1 and not rows:
                # The table is there but no row parsed: its columns changed.
                # Page 1 always holds the latest filings, so empty is wrong.
                raise RuntimeError(f"Tamworth: no document rows on {url}")
            for label, filed, href in rows:
                is_agenda = bool(_AGENDA.search(label)) and not _LATE_ITEM.search(label)
                is_minutes = bool(_MINUTES.search(label))
                if not (is_agenda or is_minutes):
                    continue
                match = _LABEL_DATE.search(label)
                if not match:
                    self.logger.warning(f"Tamworth: no date in {label!r}, skipped")
                    continue
                date = parse_date(match.group(0)).date()
                meeting = meetings.setdefault(
                    date, {"agenda": None, "minutes": None, "labels": []}
                )
                key = "agenda" if is_agenda else "minutes"
                # The listing is newest first, so a paper filed twice (the
                # 24 September 2019 business paper) keeps its latest copy.
                if meeting[key] is None:
                    meeting[key] = urljoin(_LISTING_URL, href)
                    meeting["labels"].append(label)
            # Stop once a page's newest filing predates the earliest wanted
            # year: every later page is older still.
            if not has_next or (rows and max(r[1] for r in rows).year < earliest):
                break
            page += 1

        results = []
        for date in sorted(meetings, reverse=True):
            if date.year not in wanted:
                continue
            meeting = meetings[date]
            name = (
                "Extraordinary Council Meeting"
                if any(_EXTRAORDINARY.search(label) for label in meeting["labels"])
                else "Council Meeting"
            )
            results.append(
                ScraperReturn(
                    name=name,
                    date=date.isoformat(),
                    time=None,
                    webpage_url=_LISTING_URL,
                    agenda_url=meeting["agenda"],
                    minutes_url=meeting["minutes"],
                    download_url=meeting["agenda"] or meeting["minutes"],
                )
            )

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
