"""Southern Grampians Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

The listing is the Council Meetings page itself (``OC CL Public Meetings``).
Its year filter offers 2024–2026 only. Papers for 2020–2023 are on a separate
content page, ``/About-Council/Council-Meetings/Archived-Council-Meetings``,
as direct PDF links under a heading per meeting date (see
`archive_meetings`): minutes only for 2020–2022, agenda and minutes for
2023. That page is read only for a wanted year before 2024, and the listing
only for 2024 on, so a production year costs what it did: one request for
2020–2023, the listing for 2024 onwards.

Each payload is one flat Related Information list, so
`papers_by = "link_text"`. The labels are often the raw filename
("Unconfirmed-Minutes-Council-Meeting-13-October-2026_1.pdf") and sometimes
put the meeting first ("Council Meeting - 14 July 2026 - Agenda"); matching
the words anywhere in the label handles both. Attachment books are passed
over, and on 10 April 2024 the Coleraine Sporting Grounds Committee's minutes
are listed after the Council's own, which win by coming first.

Types are Ordinary and Special Meeting, both of Council; the Statutory
meeting of 5 November 2025 is typed Ordinary, and is named Statutory Meeting
from its filenames (see `_paper_kind`). Nothing is filtered. One
production year is one listing page (pagesize=100) plus one payload per
meeting: 11 requests for 2026.
"""

import datetime
import re
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.opencities import ListingRow, OpenCitiesMeetingsScraper
from aus_council_scrapers.scrapers.vic._paper_kind import KIND, paper_kind

# The first year the meetings module has rows for; earlier years are on
# ARCHIVE_URL.
LISTING_FROM = 2024

ARCHIVE_URL = (
    "https://www.sthgrampians.vic.gov.au/About-Council/Council-Meetings"
    "/Archived-Council-Meetings"
)

_AGENDA_FILE = re.compile(r"\bagenda\b")
_MINUTES_FILE = re.compile(r"\bminutes\b")
_ATTACHMENT_FILE = re.compile(r"\battachments?\b")


def archive_meetings(html: str, years: set[int]) -> list[ScraperReturn]:
    """The meetings on the Archived Council Meetings page for `years`.

    Each meeting is an ``<h2>`` holding its date ("12 February 2020") over
    its PDFs, whose link text is the filename: "Minutes-Council-Meeting-12-
    February-2020.pdf", "Public-Agenda-Council-Meeting-8-February-2023.pdf",
    "Minutes-Unscheduled-Meeting-25-March-2022.pdf". The heading is the date;
    every filename on the page agreed with it when checked on 20 October
    2026. The filename says which paper it is and what kind of meeting.
    """
    content = BeautifulSoup(html, "html.parser").find("div", id="main-content")
    if content is None:
        raise RuntimeError(f"{ARCHIVE_URL}: no main content; the page has changed")

    meetings: dict[datetime.date, dict[str, str]] = {}
    date = None
    for element in content.find_all(["h2", "a"]):
        if element.name == "h2":
            try:
                date = datetime.datetime.strptime(
                    element.get_text(" ", strip=True), "%d %B %Y"
                ).date()
            except ValueError:
                date = None
            continue
        href = element.get("href", "").strip()
        if date is None or date.year not in years or not href.lower().endswith(".pdf"):
            continue
        filename = re.sub(
            r"[-_.]", " ", unquote(urlparse(href).path.rsplit("/", 1)[-1]).lower()
        )
        if _ATTACHMENT_FILE.search(filename):
            continue
        papers = meetings.setdefault(date, {})
        paper = (
            "minutes"
            if _MINUTES_FILE.search(filename)
            else "agenda" if _AGENDA_FILE.search(filename) else None
        )
        if paper and paper not in papers:
            papers[paper] = urljoin(ARCHIVE_URL, href)

    results = []
    for date, papers in meetings.items():
        if not papers:
            continue
        kind = paper_kind(papers.get("agenda"), papers.get("minutes"))
        results.append(
            ScraperReturn(
                # The listing's own types are "Ordinary Meeting" and "Special
                # Meeting"; the archive's "Council-Meeting" is the ordinary one.
                name=f"{kind or 'Ordinary'} Meeting",
                date=f"{date.day:02d} {date:%B %Y}",
                time=None,
                webpage_url=ARCHIVE_URL,
                agenda_url=papers.get("agenda"),
                minutes_url=papers.get("minutes"),
                download_url=papers.get("agenda") or papers.get("minutes"),
            )
        )
    # Newest first, as the listing returns them.
    results.sort(
        key=lambda r: datetime.datetime.strptime(r.date, "%d %B %Y"), reverse=True
    )
    return results


@register_scraper
class SouthernGrampiansScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 18 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 18

    list_name = "OC CL Public Meetings"
    papers_by = "link_text"
    page_size = 100
    # The year-filtered page carries the full year dropdown (checked 20 Oct
    # 2026), so production reads its one year without the bare page first.
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "southern_grampians",
            "VIC",
            "https://www.sthgrampians.vic.gov.au/About-Council/Council-Meetings",
        )
        self.default_name = "Council Meeting"

    def meeting_name(
        self, row: ListingRow, content: BeautifulSoup, papers: dict[str, str]
    ) -> str:
        name = super().meeting_name(row, content, papers)
        if KIND.search(name):
            return name
        kind = paper_kind(papers.get("agenda"), papers.get("minutes"))
        # "Statutory Meeting", in the listing's own "Special Meeting" form.
        return f"{kind} Meeting" if kind else name

    def scraper(self) -> list[ScraperReturn]:
        wanted = self._wanted_years()
        # The listing's year filter does not offer a year before 2024, so it
        # is not asked for one.
        results = super().scraper() if max(wanted) >= LISTING_FROM else []
        archive_years = {year for year in wanted if year < LISTING_FROM}
        if not archive_years:
            return results
        try:
            archived = archive_meetings(
                self.fetcher.fetch_with_requests(ARCHIVE_URL), archive_years
            )
            if not archived:
                # Every year 2020–2023 has a dozen meetings on the page, so
                # none means the page moved or changed shape.
                raise RuntimeError(
                    f"{ARCHIVE_URL}: no meetings for {sorted(archive_years)}"
                )
        except Exception as e:
            if not results:
                raise
            self.logger.warning(
                f"{self.council_name}: returning {len(results)} listed meeting(s) "
                f"without the 2020–2023 archive, which failed: {e}"
            )
            return results
        listed = {r.date for r in results}
        return results + [r for r in archived if r.date not in listed]
