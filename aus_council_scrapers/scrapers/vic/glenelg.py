"""Glenelg Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

The listing is the "Council Meetings, Minutes and Agendas" page
(``OC CL Public Meetings``); ``/Our-Council/Council-Meetings`` is a landing
page that links to it. The year filter offers 2018 and 2020–2026, but only
2023 onwards has rows: 2018 and 2020–2022 answer with an empty list.

2020–2022 are minutes only, on a static content page,
``.../Previous-Years-Minutes`` (see `archive_meetings`). It is read only
for a wanted year before 2023, and the listing only for 2023 on, so a
production year costs what it did: one request for 2020–2022, the listing
for 2023 onwards.

Papers changed shape in mid-2025, and `papers_by = "heading"` reads both:

* **January 2023 to June 2025**: ``<h3>Agenda</h3>``, ``<h3>Attachments</h3>``
  and ``<h3>Minutes</h3>`` sections, every link "Download PDF". Until
  February 2024 the attachment book sits in the Agenda section after the
  agenda; heading mode takes the section's first PDF, which is the agenda.
* **July 2025 on**: no sections, one flat Related Information list labelled
  "Agenda - 22 September 2026", "Attachments - …", "Minutes - …". Heading
  mode reads a payload with no sections by link text, which is what this
  needs.

Every row is a Council meeting (types Council, Ordinary and Statutory), so
nothing is filtered. The unscheduled meeting of 20 October 2026 is typed
Council; its file is "unscheduled-council-meeting-agenda-…", so it is named
from the filename (see `_paper_kind`). One production year is one listing
page (pagesize=100 holds a whole year; 2023–2025 have 13 rows each) plus one
payload per meeting: 11 requests for 2026.
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
LISTING_FROM = 2023

ARCHIVE_URL = (
    "https://www.glenelg.vic.gov.au/Our-Council/Council-Meetings-Minutes-and-Agendas"
    "/Previous-Years-Minutes"
)

_ARCHIVE_YEAR = re.compile(r"^Minutes from (\d{4})$")
# "Ordinary Council Meeting 25 January", "Ordinary Council Meeting Public 26
# May", "Statutory Council Meeting 11 November"—the year is the heading's.
_ARCHIVE_LINK = re.compile(r"^(?P<kind>.*?)\s+(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]+)$")
# A full date in a filename: "council_meeting_tuesday_14_december_2021",
# "council-meeting-25-january-2021-minutes".
_FILE_DATE = re.compile(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})")
_MONTH_FIXES = {"novemeber": "november"}


def _parse_day(day: str, month: str, year: int) -> datetime.date | None:
    month = _MONTH_FIXES.get(month.lower(), month.lower())
    try:
        return datetime.datetime.strptime(f"{day} {month} {year}", "%d %B %Y").date()
    except ValueError:
        return None


def archive_meetings(html: str, years: set[int]) -> list[ScraperReturn]:
    """The minutes on the Previous Years Minutes page for `years`.

    Each year is an ``<h2>Minutes from 2021</h2>`` over a list of links
    whose text gives the day and month. Two of the 38 links disagree with
    their file, checked against the PDFs on 20 October 2026:

    * The first 2022 link, "Ordinary Council Meeting 25 January", is a file
      named "council-meeting-25-january-2021-minutes.pdf" whose cover says
      25 January 2022. The link text and heading are right.
    * The first 2021 link, "Ordinary Council Meeting 21 January", is
      "public_council_meeting_minutes_wednesday_27_january_2021.pdf", whose
      cover says Wednesday 27 January 2021. The filename is right.

    So a full date in the filename wins when its year is the heading's year,
    and otherwise the link text's day with the heading's year is the date.
    """
    content = BeautifulSoup(html, "html.parser").find("div", id="main-content")
    if content is None:
        raise RuntimeError(f"{ARCHIVE_URL}: no main content; the page has changed")

    results: list[ScraperReturn] = []
    year = None
    for element in content.find_all(["h2", "a"]):
        if element.name == "h2":
            match = _ARCHIVE_YEAR.match(element.get_text(" ", strip=True))
            year = int(match.group(1)) if match else None
            continue
        href = element.get("href", "").strip()
        if year not in years or not href.lower().endswith(".pdf"):
            continue
        text = re.sub(r"\s*\(PDF.*$", "", element.get_text(" ", strip=True))
        link = _ARCHIVE_LINK.match(text)
        if not link:
            continue
        date = _parse_day(link["day"], link["month"], year)
        filename = re.sub(
            r"[-_.]", " ", unquote(urlparse(href).path.rsplit("/", 1)[-1]).lower()
        )
        for day, month, file_year in _FILE_DATE.findall(filename):
            if int(file_year) == year:
                date = _parse_day(day, month, year) or date
                break
        if date is None:
            continue
        kind = KIND.search(link["kind"])
        url = urljoin(ARCHIVE_URL, href)
        results.append(
            ScraperReturn(
                name=(
                    f"{kind.group(1).capitalize()} Meeting"
                    if kind
                    else "Council Meeting"
                ),
                date=f"{date.day:02d} {date:%B %Y}",
                time=None,
                webpage_url=ARCHIVE_URL,
                agenda_url=None,
                minutes_url=url,
                download_url=url,
            )
        )
    # Newest first, as the listing returns them; the page runs January to
    # December within each year.
    results.sort(
        key=lambda r: datetime.datetime.strptime(r.date, "%d %B %Y"), reverse=True
    )
    return results


@register_scraper
class GlenelgScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 20 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 20

    list_name = "OC CL Public Meetings"
    papers_by = "heading"
    page_size = 100
    # The year-filtered page carries the full year dropdown (checked 20 Oct
    # 2026), so production reads its one year without the bare page first.
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "glenelg",
            "VIC",
            "https://www.glenelg.vic.gov.au/Our-Council/Council-Meetings-Minutes-and-Agendas",
        )
        self.default_name = "Council Meeting"

    def meeting_name(
        self, row: ListingRow, content: BeautifulSoup, papers: dict[str, str]
    ) -> str:
        name = super().meeting_name(row, content, papers)
        if KIND.search(name):
            return name
        kind = paper_kind(papers.get("agenda"), papers.get("minutes"))
        return f"{kind} {name}" if kind else name

    def scraper(self) -> list[ScraperReturn]:
        wanted = self._wanted_years()
        # The listing answers an empty page for every year before 2023, so it
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
                # Every year 2020–2022 has a dozen meetings on the page, so
                # none means the page moved or changed shape.
                raise RuntimeError(
                    f"{ARCHIVE_URL}: no minutes for {sorted(archive_years)}"
                )
        except Exception as e:
            if not results:
                raise
            self.logger.warning(
                f"{self.council_name}: returning {len(results)} listed meeting(s) "
                f"without the 2020–2022 archive, which failed: {e}"
            )
            return results
        listed = {r.date for r in results}
        return results + [r for r in archived if r.date not in listed]
