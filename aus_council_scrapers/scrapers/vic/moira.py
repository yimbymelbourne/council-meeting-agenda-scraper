"""Moira Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

Moira splits its meetings across two OpenCities lists, like Kingston:

* **Past**—``OC CL Public Past Meetings`` at ``/Past-Meetings``, from 2017.
* **Upcoming**—``OC CL Public Upcoming Meetings`` at
  ``/Meeting-Schedule-and-Upcoming-Meetings``, where a meeting's agenda first
  appears. Its three rows (28 October to 16 December 2026) had no papers on
  20 October 2026; they are fetched anyway, and skipped until they do.

Papers are filed under headings—"Agenda", "Minutes", "Unconfirmed Minutes"
—with every link labelled "Download PDF", so ``papers_by = "heading"``.
Beside them sit sections for single reports and plans ("Item 9.2.7 -
Attachment 3 - Budget 2025-2026", "Recording of Council Meeting"), which are
not the agenda or minutes and are passed over. A few headings put the date
first ("22 April 2020 Agenda"), which heading mode would not recognise, so
`papers` moves a leading date out of the way first.

Only meetings of the council are fetched (``meeting_types``): Scheduled,
Unscheduled and Ordinary Council Meetings, the 2021 and 2022 Mayoral
Elections and the 2024 Delegated Committee. Left out is the "Committee of
Council Meeting" type, which is the CEO Employment and Remuneration
Committee, budget submission hearings and a 2021 road discontinuance
hearing—about a quarter of each year's rows, and each a request.

One production year is the two list pages and a payload per kept meeting: 16
requests for 2026.
"""

import re

from bs4 import BeautifulSoup

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import Listing
from aus_council_scrapers.scrapers.vic._regional_opencities import (
    RegionalOpenCitiesScraper,
)

_BASE_URL = "https://www.moira.vic.gov.au/Our-Council/Council-Meetings"

_LEADING_DATE = re.compile(
    r"^\s*\d{1,2}\s+[A-Za-z]+\s+(?:19|20)\d\d\s+(?=(?:agenda|minutes)\b)",
    re.IGNORECASE,
)


@register_scraper
class MoiraScraper(RegionalOpenCitiesScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 29 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 29

    list_name = "OC CL Public Past Meetings"
    papers_by = "heading"
    meeting_types = re.compile(r"^(?!Committee of Council\b)")

    def __init__(self):
        super().__init__("moira", "VIC", f"{_BASE_URL}/Past-Meetings")

    def extra_listings(self, first_page_html: str) -> list[Listing]:
        return [
            Listing(
                f"{_BASE_URL}/Meeting-Schedule-and-Upcoming-Meetings",
                "OC CL Public Upcoming Meetings",
            )
        ]

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        content = BeautifulSoup(str(content), "html.parser")
        for heading in content.select("div.meeting-document > h3"):
            text = heading.get_text(" ", strip=True)
            stripped = _LEADING_DATE.sub("", text, count=1)
            if stripped != text:
                heading.string = stripped
        return super().papers(content)
