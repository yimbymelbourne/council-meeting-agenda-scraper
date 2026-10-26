"""Corangamite Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

The listing is "Minutes & Agendas" (``OC CL Public Meetings``), a child of
the Council Meetings landing page. The year filter offers 2013–2026 (no
2015); 2020 onwards is fetched.

Each payload is one flat Related Information list labelled "Agenda - Council
Meeting 22 September 2026" and "Minutes - Council Meeting 22 September 2026"
(filenames in early 2020), so `papers_by = "link_text"`. Late items, which
this council files beside the agenda ("Late Item 9.10 - S11A Instrument of
Appointment…"), and confidential item minutes (22 April 2025) are passed
over by the base class rules.

Every row is typed Council Meeting except five in January–May 2020 whose type
is blank. Their payloads say "Papers of the Ordinary Council Meeting", so
they are named Council Meeting like the rest. Four special meetings (14
February, 4 April and 14 November 2023, 24 September 2024) are typed Council
Meeting too; their papers say "Special Council Meeting" in label and
filename, so they are named from the filename (see `_paper_kind`). Nothing
is filtered. One
production year is one listing page (pagesize=100) plus one payload per
meeting: 10 requests for 2026.
"""

from bs4 import BeautifulSoup

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import ListingRow, OpenCitiesMeetingsScraper
from aus_council_scrapers.scrapers.vic._paper_kind import KIND, paper_kind


@register_scraper
class CorangamiteScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 19 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 19

    list_name = "OC CL Public Meetings"
    papers_by = "link_text"
    page_size = 100
    # The year-filtered page carries the full year dropdown (checked 20 Oct
    # 2026), so production reads its one year without the bare page first.
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "corangamite",
            "VIC",
            "https://www.corangamite.vic.gov.au/Council/Inside-Council/Council-Meetings/Minutes-Agendas",
        )
        # The name for the 2020 rows with a blank type.
        self.default_name = "Council Meeting"

    def meeting_name(
        self, row: ListingRow, content: BeautifulSoup, papers: dict[str, str]
    ) -> str:
        name = super().meeting_name(row, content, papers)
        if KIND.search(name):
            return name
        kind = paper_kind(papers.get("agenda"), papers.get("minutes"))
        return f"{kind} {name}" if kind else name
