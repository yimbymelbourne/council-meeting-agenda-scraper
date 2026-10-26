import datetime
import re
from typing import Optional
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.forbes.nsw.gov.au"
_LISTING_URL = (
    f"{_BASE_URL}/council/about-council/council-meetings/council-meetings/"
    "council-meeting-agendas-and-minutes"
)

# Every meeting since February 2022 is one row of a single table on this
# page: Date | Business Paper | Minutes | Attachments. The CMS serves the
# papers from /ArticleDocuments/<id>/<name>.pdf.aspx.
#
# A documented robots.txt exception. www.forbes.nsw.gov.au/robots.txt has,
# under `User-agent: *`:
#
#     Disallow: /ArticleDocuments/
#
# (checked 26 Oct 2026; no Crawl-delay), and every agenda and minutes PDF is
# under it. The scraper itself requests only this listing page, which is
# allowed, but council-alerts downloads every document URL a scraper emits,
# so production does fetch the disallowed path. The maintainer decided on 26
# Oct 2026 to accept that, as he did for swan, because these papers are the
# council's official public record. The exception covers the emitted papers
# only: nothing here may request any other disallowed path, and any other
# host keeps its own robots.txt. See AGENTS.md before adding another.
#
# The date cell is the only reliable date. Labels and file names drift from
# it in both directions: the 18 June 2026 minutes are labelled "18 June 2025
# Minutes", the 19 December 2024 minutes "Minutes 20 December 2024", and the
# 2 October 2024 minutes are filed as "2 October 2022 DRAFT Minutes".
_DAY_MONTH_YEAR = re.compile(
    r"(?<!\d)(\d{1,2})\s+(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+(\d{4})(?!\d)",
    re.IGNORECASE,
)
# A supplementary business paper is a second document for a meeting that
# already has its agenda.
_SUPPLEMENTARY = re.compile(r"supplementary", re.IGNORECASE)
# Special meetings share a row with an ordinary one when they fall on the
# same night ("17 November 2022 Special Meeting Business Paper" beside the
# ordinary business paper), and sometimes say so only in the file name
# ("14 September 2023 Special Minutes.pdf").
_SPECIAL = re.compile(r"special", re.IGNORECASE)
# The 2 October 2024 meeting, after the local government elections, is filed
# as CO_20241002_AGN_5305_AT_EXTRA: an extraordinary meeting. Its minutes
# carry no such marker, so the type is taken from whichever paper has it.
_EXTRAORDINARY = re.compile(r"extraordinary|_EXTRA\b", re.IGNORECASE)

# A wanted year with no meetings is an error only once this much of it has
# passed, the rule CraftMeetingsModuleScraper uses.
_NEW_YEAR_GRACE_DAYS = 90


def _owed_papers(year: int) -> bool:
    """Whether a year has run long enough that it must have papers."""
    today = clock.today()
    return year < today.year or (
        year == today.year
        and (today - datetime.date(year, 1, 1)).days >= _NEW_YEAR_GRACE_DAYS
    )


def _row_date(text: str) -> Optional[datetime.date]:
    match = _DAY_MONTH_YEAR.search(text.replace("\xa0", " "))
    if not match:
        return None
    day, month, year = match.groups()
    return datetime.datetime.strptime(f"{day} {month} {year}", "%d %B %Y").date()


@register_scraper
class ForbesScraper(BaseScraper):
    def __init__(self):
        super().__init__("forbes", "NSW", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _columns(table) -> dict[str, int]:
        """Column index by role, read from the header row.

        Classifying a paper by its column rather than its label matters here:
        labels are hand-typed and often name neither ("18 December 2025 (
        PDF 94.2MB )" is the business paper, "16 October 2025 ( PDF 349.2KB
        )" the minutes).
        """
        header = table.find("tr")
        roles = {}
        for i, cell in enumerate(header.find_all(["th", "td"]) if header else []):
            text = cell.get_text(" ", strip=True).lower()
            if "business paper" in text or "agenda" in text:
                roles.setdefault("agenda", i)
            elif "minutes" in text:
                roles.setdefault("minutes", i)
        return roles

    @staticmethod
    def _papers(cell) -> list[tuple[str, str, str]]:
        """(url, label, file name) for each labelled link in a cell.

        A link with no text is an older upload left behind beside its
        replacement: the 17 September 2026 cell holds three blank links to
        earlier drafts before the labelled "DRAFT Minutes", and the 15 May
        2025 cell has two blank links to the 2024 business paper. Only the
        labelled link is the paper the council is showing.
        """
        papers = []
        for anchor in cell.find_all("a", href=True):
            label = anchor.get_text(" ", strip=True)
            if not label:
                continue
            url = urljoin(_LISTING_URL, anchor["href"].strip())
            papers.append((url, label, unquote(url.rsplit("/", 1)[-1])))
        return papers

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # Left to raise on failure: this page is the scraper's only request.
        html = self.fetcher.fetch_with_requests(_LISTING_URL)
        soup = BeautifulSoup(html, "html.parser")

        meetings: dict[tuple[datetime.date, bool], dict[str, str]] = {}
        extraordinary: set[tuple[datetime.date, bool]] = set()
        tables_read = 0
        oldest = clock.current_year()
        for table in soup.find_all("table"):
            columns = self._columns(table)
            if "agenda" not in columns or "minutes" not in columns:
                continue
            tables_read += 1
            for row in table.find_all("tr")[1:]:
                cells = row.find_all("td")
                if len(cells) <= max(columns.values()):
                    continue
                date = _row_date(cells[0].get_text(" ", strip=True))
                if not date:
                    continue
                oldest = min(oldest, date.year)
                if date.year not in wanted:
                    continue
                for kind, index in columns.items():
                    for url, label, filename in self._papers(cells[index]):
                        if kind == "agenda" and _SUPPLEMENTARY.search(label):
                            continue
                        text = f"{label} {filename}"
                        special = bool(_SPECIAL.search(text))
                        meetings.setdefault((date, special), {}).setdefault(kind, url)
                        if _EXTRAORDINARY.search(text):
                            extraordinary.add((date, special))

        results = []
        for (date, special), papers in sorted(meetings.items()):
            agenda_url = papers.get("agenda")
            minutes_url = papers.get("minutes")
            if special:
                name = "Special Council Meeting"
            elif (date, special) in extraordinary:
                name = "Extraordinary Council Meeting"
            else:
                name = "Ordinary Council Meeting"
            results.append(
                ScraperReturn(
                    name=name,
                    date=date.isoformat(),
                    time=None,
                    webpage_url=_LISTING_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        if not tables_read:
            # No table with Business Paper and Minutes columns: the page has
            # changed shape, which must not pass for a council with no
            # meetings.
            raise ValueError(
                f"{self.council_name}: no agendas-and-minutes table on {_LISTING_URL}"
            )
        if not results:
            # The table is there but has no row for these years. That is
            # normal in January, before the first meeting of the year, and
            # for years before the table starts (February 2022). It is an
            # error once a wanted year inside the table's span has run long
            # enough to owe papers.
            message = f"{self.council_name} found no meetings for {sorted(wanted)}"
            if any(_owed_papers(year) for year in wanted if year >= oldest):
                raise ValueError(message)
            self.logger.warning(message)
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
